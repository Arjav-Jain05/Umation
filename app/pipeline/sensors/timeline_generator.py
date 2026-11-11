"""Hot-zone map and per-second event timeline generator for LLM prompt context."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from app.pipeline.s1_ingest.audience import AudienceSignalsData
from app.pipeline.sensors.audio_energy import AudioEnergyProfile
from app.pipeline.sensors.sound_events import SoundEventsProfile

logger = logging.getLogger("app.pipeline.sensors.timeline_generator")


def _format_time(sec: float) -> str:
    """Format seconds into MM:SS format."""
    m = int(sec // 60)
    s = int(sec % 60)
    return f"{m:02d}:{s:02d}"


@dataclass
class TimelineEvent:
    time_s: float
    time_str: str
    event_type: str  # e.g. "sound_event", "audio_burst", "chat_spike", "comment_peak", "silence_explosion"
    description: str


@dataclass
class HotZone:
    start_s: float
    end_s: float
    signals_involved: list[str]
    peak_score: float


def generate_timeline_and_hot_zones(
    duration_s: float,
    audio_energy: AudioEnergyProfile,
    sound_events: SoundEventsProfile,
    audience: AudienceSignalsData,
) -> tuple[list[TimelineEvent], list[HotZone]]:
    """Synthesize all sensors and audience signals into discrete timeline events and overlapping hot zones."""
    events: list[TimelineEvent] = []
    num_seconds = max(1, math.ceil(duration_s))

    # Per-second hit tracker for hot-zone detection
    second_hits: dict[int, list[str]] = {sec: [] for sec in range(num_seconds)}

    # 1. Sound events
    for ev in sound_events.events:
        sec = math.floor(ev.time_s)
        if 0 <= sec < num_seconds:
            second_hits[sec].append(f"sound:{ev.event}")
            events.append(TimelineEvent(
                time_s=ev.time_s,
                time_str=_format_time(ev.time_s),
                event_type="sound_event",
                description=f"{ev.event} sound effect (conf: {ev.confidence:.2f})",
            ))

    # 2. Audio energy bursts & silence-explosion payoffs
    for idx in audio_energy.silence_explosion_indices:
        t = float(idx)
        if 0 <= idx < num_seconds:
            second_hits[idx].append("silence_explosion")
            events.append(TimelineEvent(
                time_s=t,
                time_str=_format_time(t),
                event_type="silence_explosion",
                description="sudden explosion/jump after quiet suspense",
            ))

    if len(audio_energy.per_second_z) > 0:
        for sec in range(min(num_seconds, len(audio_energy.per_second_z))):
            z = audio_energy.per_second_z[sec]
            if z >= 2.2:
                second_hits[sec].append("audio_burst")
                # Only log distinct audio peaks
                if sec == 0 or audio_energy.per_second_z[sec - 1] < 2.0:
                    events.append(TimelineEvent(
                        time_s=float(sec),
                        time_str=_format_time(float(sec)),
                        event_type="audio_burst",
                        description=f"loud speech/action spike (z={z:.1f})",
                    ))

    # 3. Audience chat spikes
    if audience.has_chat and audience.chat_bins:
        for b, score in audience.chat_bins.items():
            if score >= 0.70:
                t = float(b * 10)
                sec = int(b * 10)
                if 0 <= sec < num_seconds:
                    second_hits[sec].append("chat_spike")
                hypes = audience.chat_hype_tags.get(b, [])
                hype_text = f" keywords: {', '.join(hypes)}" if hypes else ""
                events.append(TimelineEvent(
                    time_s=t,
                    time_str=_format_time(t),
                    event_type="chat_spike",
                    description=f"chat replay activity surge (intensity: {score:.2f}){hype_text}",
                ))

    # 4. Audience comment timestamps
    if audience.has_comments and audience.comments_bins:
        for b, score in audience.comments_bins.items():
            if score >= 0.75:
                t = float(b * 10)
                sec = int(b * 10)
                if 0 <= sec < num_seconds:
                    second_hits[sec].append("comment_peak")
                events.append(TimelineEvent(
                    time_s=t,
                    time_str=_format_time(t),
                    event_type="comment_peak",
                    description="viewers frequently bookmarked/quoted timestamp",
                ))

    # Sort events by time
    events.sort(key=lambda e: e.time_s)

    # 5. Extract hot zones: contiguous blocks of seconds with >= 2 distinct signals
    hot_zones: list[HotZone] = []
    in_zone = False
    zone_start = 0
    zone_signals: set[str] = set()

    for sec in range(num_seconds):
        second_hits.get(sec, [])
        # Check window of [sec-2, sec+2] for signal coincidence
        nearby_signals: set[str] = set()
        for w_s in range(max(0, sec - 2), min(num_seconds, sec + 3)):
            nearby_signals.update(second_hits.get(w_s, []))

        if len(nearby_signals) >= 2:
            if not in_zone:
                in_zone = True
                zone_start = max(0, sec - 2)
                zone_signals = set(nearby_signals)
            else:
                zone_signals.update(nearby_signals)
        else:
            if in_zone:
                in_zone = False
                zone_end = min(float(num_seconds), float(sec + 2))
                if zone_end - zone_start >= 5.0:
                    hot_zones.append(HotZone(
                        start_s=float(zone_start),
                        end_s=float(zone_end),
                        signals_involved=sorted(zone_signals),
                        peak_score=min(100.0, 50.0 + len(zone_signals) * 15.0),
                    ))
                zone_signals = set()

    if in_zone:
        hot_zones.append(HotZone(
            start_s=float(zone_start),
            end_s=float(num_seconds),
            signals_involved=sorted(zone_signals),
            peak_score=min(100.0, 50.0 + len(zone_signals) * 15.0),
        ))

    return events, hot_zones


def format_timeline_for_prompt(
    events: list[TimelineEvent],
    start_s: float,
    end_s: float,
    max_events: int = 12,
) -> str:
    """Format timeline events in [start_s, end_s] into a compact prompt string."""
    matching = [e for e in events if start_s <= e.time_s <= end_s]
    if not matching:
        return "No notable acoustic, visual, or audience spikes detected in this segment."

    # Subsample if too many events
    if len(matching) > max_events:
        step = len(matching) / float(max_events)
        matching = [matching[int(i * step)] for i in range(max_events)]

    lines = [f"[{e.time_str}] {e.description}" for e in matching]
    return ";\n".join(lines)
