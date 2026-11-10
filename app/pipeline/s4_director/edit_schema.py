"""Edit list Pydantic schemas, validation, snapping, and density rule enforcement."""

from __future__ import annotations

import logging
import re
from typing import Any

import yaml
from pydantic import BaseModel, Field

from app.core import paths

logger = logging.getLogger("app.pipeline.s4_director.edit_schema")

VALID_EVENT_TYPES = {
    "hook_card",
    "zoom_punch",
    "arrow",
    "highlight_box",
    "emoji_pop",
    "part_label",
    "recap_line",
    "progress_bar",
    "sfx",
}


class EditEvent(BaseModel):
    """A single director event or on-screen overlay."""

    id: str
    type: str
    t: float
    dur: float
    params: dict[str, Any] = Field(default_factory=dict)


class EditList(BaseModel):
    """Complete edit list for a single vertical clip."""

    schema_version: int = 1
    clip_id: str
    fps: int = 30
    duration: float
    layout: str = "gameplay"
    caption_emphasis: list[int] = Field(default_factory=list)
    events: list[EditEvent] = Field(default_factory=list)


def _load_profanity_words() -> list[str]:
    prof_file = paths.config_dir() / "profanity.yaml"
    if not prof_file.is_file():
        return []
    try:
        data = yaml.safe_load(prof_file.read_text(encoding="utf-8"))
        return [w.lower() for w in data.get("words", [])]
    except Exception:
        return []


def _mask_profanity(text: str, prof_words: list[str]) -> str:
    if not prof_words:
        return text
    pattern = re.compile(rf"\b({'|'.join(re.escape(w) for w in prof_words)})\b", re.IGNORECASE)

    def repl(m: re.Match) -> str:
        w = m.group(0)
        return w[0] + "*" * (len(w) - 1)

    return pattern.sub(repl, text)


def _snap_to_word_start(t: float, words: list[dict[str, Any]] | list[Any], max_delta: float = 0.25) -> float:
    """Snap timestamp t to nearest word start time if within max_delta seconds."""
    best_t = t
    best_dist = max_delta
    for w in words:
        start = float(w["start"] if isinstance(w, dict) else getattr(w, "start", 0.0))
        dist = abs(start - t)
        if dist < best_dist:
            best_dist = dist
            best_t = start
    return round(best_t, 3)


def validate_and_fix(
    edit_list: EditList,
    words: list[dict[str, Any]] | list[Any] | None = None,
    cfg: dict[str, Any] | None = None,
    layout: str | None = None,
) -> tuple[EditList, list[str]]:
    """Validate edit list against density rules, snap to words, clamp bounds, and fix conflicts.

    Returns the fixed EditList and a human-readable list of changes made.
    """
    messages: list[str] = []
    dur_total = edit_list.duration
    eff_cfg = cfg or {}

    words_list = words or []
    prof_words = _load_profanity_words()

    # 1. Filter out unknown event types
    valid_events: list[EditEvent] = []
    for ev in edit_list.events:
        if ev.type not in VALID_EVENT_TYPES:
            messages.append(f"Dropped event {ev.id}: unknown type '{ev.type}'")
            continue
        valid_events.append(ev)

    # 2. Word snapping for applicable events
    for ev in valid_events:
        if ev.type in ("zoom_punch", "emoji_pop", "sfx") and words_list:
            snapped = _snap_to_word_start(ev.t, words_list, max_delta=0.25)
            if snapped != ev.t:
                messages.append(f"Snapped {ev.type} {ev.id} from t={ev.t:.2f}s to {snapped:.2f}s")
                ev.t = snapped

    # 3. Clamp timing inside clip bounds [0.0, dur_total - 0.2]
    in_bounds_events: list[EditEvent] = []
    for ev in valid_events:
        if ev.type in ("progress_bar", "part_label"):
            ev.t = 0.0
            ev.dur = dur_total
            in_bounds_events.append(ev)
            continue

        if ev.t < 0.0 or ev.t >= dur_total - 0.2:
            messages.append(f"Dropped {ev.id} ({ev.type}): starts at {ev.t:.2f}s outside bounds [0, {dur_total - 0.2:.2f}]")
            continue

        max_dur = dur_total - ev.t - 0.1
        if ev.dur > max_dur:
            ev.dur = max(0.2, max_dur)
            messages.append(f"Clamped {ev.id} dur to {ev.dur:.2f}s to stay inside clip duration")

        in_bounds_events.append(ev)

    # 4. Per-type duration & parameter clamping
    processed: list[EditEvent] = []
    seen_hook_card = False

    for ev in in_bounds_events:
        t = ev.t
        p = ev.params

        if ev.type == "hook_card":
            if seen_hook_card:
                messages.append(f"Dropped duplicate hook_card {ev.id}")
                continue
            seen_hook_card = True
            t_max = float(eff_cfg.get("hook_card", {}).get("t_max", 0.3))
            ev.t = min(t, t_max)
            d_min, d_max = eff_cfg.get("hook_card", {}).get("dur", [1.8, 2.8])
            ev.dur = min(max(float(d_min), ev.dur), float(d_max))

            text = str(p.get("text", "")).strip()
            w_tokens = text.split()
            max_w = int(eff_cfg.get("hook_card", {}).get("max_words", 8))
            if len(w_tokens) > max_w:
                text = " ".join(w_tokens[:max_w])
                messages.append(f"Truncated hook_card text to {max_w} words")
            text = _mask_profanity(text, prof_words)
            ev.params["text"] = text

        elif ev.type == "zoom_punch":
            d_min, d_max = eff_cfg.get("zoom_punch", {}).get("dur", [0.6, 1.2])
            ev.dur = min(max(float(d_min), ev.dur), float(d_max))
            s_min, s_max = eff_cfg.get("zoom_punch", {}).get("scale", [1.06, 1.18])
            scale = float(p.get("scale", 1.12))
            ev.params["scale"] = min(max(float(s_min), scale), float(s_max))
            if "anchor" not in p:
                ev.params["anchor"] = "center"

        elif ev.type == "arrow":
            d_min, d_max = eff_cfg.get("arrow", {}).get("dur", [1.2, 2.5])
            ev.dur = min(max(float(d_min), ev.dur), float(d_max))
            min_conf = float(eff_cfg.get("arrow", {}).get("min_confidence", 0.6))
            conf = float(p.get("confidence", 1.0))
            if conf < min_conf:
                messages.append(f"Dropped arrow {ev.id}: confidence {conf:.2f} < {min_conf}")
                continue

        elif ev.type == "emoji_pop":
            d_min, d_max = eff_cfg.get("emoji_pop", {}).get("dur", [0.7, 1.1])
            ev.dur = min(max(float(d_min), ev.dur), float(d_max))
            # Coordinate defaults & bounds
            x = int(p.get("x", 820))
            y = int(p.get("y", 700))
            ev.params["x"] = max(60, min(1080 - 260, x))
            ev.params["y"] = max(220, min(1500 - 200, y))

        elif ev.type == "recap_line":
            d_min, d_max = eff_cfg.get("recap_line", {}).get("dur", [1.6, 2.2])
            ev.dur = min(max(float(d_min), ev.dur), float(d_max))

        processed.append(ev)

    # 5. Highlight boxes: keep only if matching arrow exists
    arrow_times = [ev.t for ev in processed if ev.type == "arrow"]
    kept_with_highlight: list[EditEvent] = []
    for ev in processed:
        if ev.type == "highlight_box":
            # Check if there is an arrow close in time (within 0.5s)
            has_matching_arrow = any(abs(ev.t - at) <= 0.5 for at in arrow_times)
            if not has_matching_arrow:
                messages.append(f"Dropped highlight_box {ev.id}: no accompanying arrow")
                continue
        kept_with_highlight.append(ev)

    # 6. Enforce min gaps and max counts per event type
    # Priority order when resolving: hook_card > arrow > zoom_punch > emoji_pop > sfx
    def filter_by_gap_and_count(events: list[EditEvent], ev_type: str, min_gap: float, max_count: int) -> list[EditEvent]:
        matching = [e for e in events if e.type == ev_type]
        other = [e for e in events if e.type != ev_type]
        matching.sort(key=lambda e: e.t)

        accepted: list[EditEvent] = []
        last_t = -999.0
        for e in matching:
            if len(accepted) >= max_count:
                messages.append(f"Dropped {e.id} ({ev_type}): exceeded max count {max_count}")
                continue
            if e.t - last_t < min_gap:
                messages.append(f"Dropped {e.id} ({ev_type}): gap {e.t - last_t:.2f}s < min {min_gap}s")
                continue
            accepted.append(e)
            last_t = e.t

        return other + accepted

    events_filtered = kept_with_highlight
    events_filtered = filter_by_gap_and_count(
        events_filtered,
        "zoom_punch",
        min_gap=float(eff_cfg.get("zoom_punch", {}).get("min_gap_s", 4.0)),
        max_count=int(eff_cfg.get("zoom_punch", {}).get("max_per_clip", 6)),
    )
    events_filtered = filter_by_gap_and_count(
        events_filtered,
        "arrow",
        min_gap=float(eff_cfg.get("arrow", {}).get("min_gap_s", 3.0)),
        max_count=int(eff_cfg.get("arrow", {}).get("max_per_clip", 4)),
    )
    events_filtered = filter_by_gap_and_count(
        events_filtered,
        "emoji_pop",
        min_gap=float(eff_cfg.get("emoji_pop", {}).get("min_gap_s", 6.0)),
        max_count=int(eff_cfg.get("emoji_pop", {}).get("max_per_clip", 4)),
    )
    events_filtered = filter_by_gap_and_count(
        events_filtered,
        "sfx",
        min_gap=float(eff_cfg.get("sfx", {}).get("min_gap_s", 0.5)),
        max_count=int(eff_cfg.get("sfx", {}).get("max_per_clip", 8)),
    )

    # 7. Global density limit (max_events_per_second)
    max_rate = float(eff_cfg.get("max_events_per_second", 0.4))
    max_visual_events = max(1, round(dur_total * max_rate))

    visual_events = [e for e in events_filtered if e.type not in ("progress_bar", "part_label", "sfx")]
    non_visual_events = [e for e in events_filtered if e.type in ("progress_bar", "part_label", "sfx")]

    if len(visual_events) > max_visual_events:
        type_priority = {"hook_card": 5, "arrow": 4, "highlight_box": 3, "zoom_punch": 2, "emoji_pop": 1}
        visual_events.sort(key=lambda e: (type_priority.get(e.type, 0), -e.t), reverse=True)
        dropped_events = visual_events[max_visual_events:]
        for d in dropped_events:
            messages.append(f"Dropped {d.id} ({d.type}): exceeded rate limit of {max_visual_events} events per clip")
        visual_events = visual_events[:max_visual_events]

    # Reassemble and sort chronologically
    final_events = visual_events + non_visual_events
    final_events.sort(key=lambda e: e.t)

    # Limit caption emphasis to max 8 items
    capped_emphasis = edit_list.caption_emphasis[:8]
    if len(edit_list.caption_emphasis) > 8:
        messages.append("Capped caption emphasis words to 8")

    fixed_list = EditList(
        schema_version=edit_list.schema_version,
        clip_id=edit_list.clip_id,
        fps=edit_list.fps,
        duration=edit_list.duration,
        layout=layout or edit_list.layout,
        caption_emphasis=capped_emphasis,
        events=final_events,
    )

    return fixed_list, messages
