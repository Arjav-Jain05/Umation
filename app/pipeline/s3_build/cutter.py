"""Stage 3: Fluid video cutting, filler removal, dead air compression, and timeline remapping."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from app.core.schemas import CutInterval, CutsArtifact, Word, WordClip, WordsClipArtifact
from app.utils.ffmpeg import has_encoder, run_ffmpeg
from app.utils.timecode import Remapper

logger = logging.getLogger("app.pipeline.s3_build.cutter")


@dataclass
class Removal:
    s: float
    e: float
    reason: str
    gap_duration: float


def _measure_gap_db(audio_path: Path | None, s: float, e: float) -> float:
    """Measure mean RMS dBFS in audio slice [s, e]. Returns -80 if quiet/missing."""
    if not audio_path or not audio_path.is_file():
        return -80.0
    try:
        with sf.SoundFile(str(audio_path)) as f:
            sr = f.samplerate
            f_start = max(0, int(s * sr))
            f_end = min(len(f), int(e * sr))
            if f_start >= f_end:
                return -80.0
            f.seek(f_start)
            block = f.read(f_end - f_start, dtype="float32")
            if len(block) == 0:
                return -80.0
            rms = float(np.sqrt(np.mean(block**2) + 1e-12))
            return 20.0 * np.log10(max(1e-4, rms))
    except Exception as exc:
        logger.debug("Failed measuring gap dB: %s", exc)
        return -80.0


def compute_keep_intervals(
    clip_start: float,
    clip_end: float,
    words: list[Word],
    fillers: list[int] | None = None,
    audio_path: Path | None = None,
    hook_end: float | None = None,
    max_removal_pct: float = 0.25,
) -> list[tuple[float, float]]:
    """Calculate keep intervals by removing hesitation fillers and quiet dead-air gaps."""
    clip_dur = clip_end - clip_start
    if clip_dur <= 0:
        return []

    filler_indices = set(fillers or [])
    hook_boundary = hook_end if hook_end is not None else clip_start

    # Filter words strictly inside [clip_start, clip_end]
    clip_words = [w for w in words if w.s >= clip_start - 0.2 and w.e <= clip_end + 0.2]
    clip_words.sort(key=lambda w: w.s)

    candidate_removals: list[Removal] = []

    # 1. Filler word removals: remove [w.s - 0.03, w.e + 0.03]
    for w in clip_words:
        if w.i in filler_indices and w.s >= hook_boundary:
            rem_s = max(clip_start, w.s - 0.03)
            rem_e = min(clip_end, w.e + 0.03)
            if rem_e > rem_s:
                candidate_removals.append(
                    Removal(s=rem_s, e=rem_e, reason="filler", gap_duration=rem_e - rem_s)
                )

    # 2. Dead air gaps: between consecutive words > 0.60s
    for idx in range(len(clip_words) - 1):
        w_curr = clip_words[idx]
        w_next = clip_words[idx + 1]
        gap_s = w_curr.e
        gap_e = w_next.s
        gap_dur = gap_e - gap_s

        if gap_dur > 0.60 and gap_s >= hook_boundary:
            mean_db = _measure_gap_db(audio_path, gap_s, gap_e)
            if mean_db < -35.0:  # Truly quiet dead air
                # Keep 0.09s on each side, remove middle
                rem_s = gap_s + 0.09
                rem_e = gap_e - 0.09
                if rem_e > rem_s:
                    candidate_removals.append(
                        Removal(s=rem_s, e=rem_e, reason="dead_air", gap_duration=rem_e - rem_s)
                    )

    # Sort removals chronologically
    candidate_removals.sort(key=lambda r: r.s)

    # Enforce 25% cap on total removed duration
    max_removable_s = clip_dur * max_removal_pct
    total_rem_s = sum(r.e - r.s for r in candidate_removals)

    if total_rem_s > max_removable_s:
        # Restore largest gap removals first until within cap
        candidate_removals.sort(key=lambda r: r.gap_duration, reverse=True)
        kept_removals: list[Removal] = []
        accum = 0.0
        for r in candidate_removals:
            dur = r.e - r.s
            if (accum + dur) <= max_removable_s:
                kept_removals.append(r)
                accum += dur
        candidate_removals = sorted(kept_removals, key=lambda r: r.s)

    # Build keep intervals from remaining removals
    keep: list[tuple[float, float]] = []
    curr_t = clip_start

    for r in candidate_removals:
        if r.s > curr_t:
            keep.append((curr_t, r.s))
        curr_t = max(curr_t, r.e)

    if curr_t < clip_end:
        keep.append((curr_t, clip_end))

    # Step 3: Merge keep-intervals < 0.05s apart; enforce min interval 0.25s
    if not keep:
        return [(clip_start, clip_end)]

    merged: list[tuple[float, float]] = []
    for s, e in keep:
        if not merged:
            merged.append((s, e))
            continue
        prev_s, prev_e = merged[-1]
        if (s - prev_e) < 0.05:
            # Merge
            merged[-1] = (prev_s, e)
        else:
            merged.append((s, e))

    # Clean small intervals (< 0.25s) by merging into neighbors
    final_keep: list[tuple[float, float]] = []
    for s, e in merged:
        dur = e - s
        if dur < 0.25 and final_keep:
            prev_s, prev_e = final_keep[-1]
            final_keep[-1] = (prev_s, e)
        elif dur >= 0.25:
            final_keep.append((s, e))

    return final_keep if final_keep else [(clip_start, clip_end)]


def build_filter_script(
    intervals: list[tuple[float, float]],
    seg_start: float = 0.0,
) -> str:
    """Generate ffmpeg -filter_complex_script content with video/audio trims and audio crossfades."""
    v_parts: list[str] = []
    a_parts: list[str] = []
    concat_inputs: list[str] = []

    for idx, (s, e) in enumerate(intervals):
        rel_s = max(0.0, s - seg_start)
        rel_e = max(rel_s + 0.01, e - seg_start)
        dur = rel_e - rel_s

        v_parts.append(f"[0:v]trim=start={rel_s:.3f}:end={rel_e:.3f},setpts=PTS-STARTPTS[v{idx}];")

        fade_dur = min(0.015, dur / 2.0)
        fade_out_st = max(0.0, dur - fade_dur)
        a_parts.append(
            f"[0:a]atrim=start={rel_s:.3f}:end={rel_e:.3f},asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d={fade_dur:.3f},afade=t=out:st={fade_out_st:.3f}:d={fade_dur:.3f}[a{idx}];"
        )
        concat_inputs.append(f"[v{idx}][a{idx}]")

    concat_str = "".join(concat_inputs) + f"concat=n={len(intervals)}:v=1:a=1[v][a]"
    return "\n".join(v_parts + a_parts + [concat_str])


def cut_clip(
    seg_path: Path,
    seg_start: float,
    intervals: list[tuple[float, float]],
    out_dir: Path,
    words: list[Word],
    fillers: list[int] | None = None,
) -> tuple[Path, CutsArtifact, WordsClipArtifact]:
    """Execute ffmpeg trim/concat script to produce cut.mkv, cuts.json, and words.json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cut_video = out_dir / "cut.mkv"

    # Single contiguous interval fast path
    if len(intervals) == 1:
        s, e = intervals[0]
        rel_s = max(0.0, s - seg_start)
        rel_dur = e - s

        v_enc = [
            "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "15", "-b:v", "0",
        ] if has_encoder("h264_nvenc") else ["-c:v", "libx264", "-preset", "fast", "-crf", "15"]

        args = [
            "-ss", f"{rel_s:.3f}",
            "-i", str(seg_path),
            "-t", f"{rel_dur:.3f}",
            *v_enc,
            "-pix_fmt", "yuv420p",
            "-c:a", "pcm_s16le",
            "-ar", "48000",
            str(cut_video),
        ]
        run_ffmpeg(args, check=True)
    else:
        # Complex cut script
        script_path = out_dir / "cut_script.txt"
        script_content = build_filter_script(intervals, seg_start=seg_start)
        script_path.write_text(script_content, encoding="utf-8")

        v_enc = [
            "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "15", "-b:v", "0",
        ] if has_encoder("h264_nvenc") else ["-c:v", "libx264", "-preset", "fast", "-crf", "15"]

        args = [
            "-i", str(seg_path),
            "-filter_complex_script", str(script_path),
            "-map", "[v]",
            "-map", "[a]",
            *v_enc,
            "-pix_fmt", "yuv420p",
            "-c:a", "pcm_s16le",
            "-ar", "48000",
            str(cut_video),
        ]
        run_ffmpeg(args, check=True)

    # Build cuts.json
    total_cut_dur = sum(e - s for s, e in intervals)
    clip_id = out_dir.name
    cuts_art = CutsArtifact(
        clip_id=clip_id,
        intervals=[CutInterval(s=s, e=e, dur=round(e - s, 3)) for s, e in intervals],
        total_source_duration=round(intervals[-1][1] - intervals[0][0], 3),
        total_cut_duration=round(total_cut_dur, 3),
        removed_duration=round((intervals[-1][1] - intervals[0][0]) - total_cut_dur, 3),
    )

    # Remap words to clip timeline
    remapper = Remapper(intervals)
    filler_set = set(fillers or [])
    clip_words: list[WordClip] = []

    for w in words:
        if w.i in filler_set:
            continue
        # Check if word falls inside any keep interval
        if any(s <= w.s and w.e <= e for s, e in intervals):
            s_clip = remapper.remap(w.s)
            e_clip = remapper.remap(w.e)
            if e_clip > s_clip:
                clip_words.append(WordClip(w=w.w, s_clip=s_clip, e_clip=e_clip))

    words_art = WordsClipArtifact(clip_id=clip_id, words=clip_words)
    return cut_video, cuts_art, words_art
