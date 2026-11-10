"""Stage 3: Word-by-word animated ASS karaoke subtitles and SRT export."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.core import paths
from app.core.schemas import WordClip
from app.utils.text import mask_profanity

logger = logging.getLogger("app.pipeline.s3_build.captions")


@dataclass
class CaptionChunk:
    words: list[WordClip]
    s: float
    e: float
    text: str


def _load_profanity_words() -> list[str]:
    prof_path = paths.project_root() / "config" / "profanity.yaml"
    if prof_path.is_file():
        try:
            with open(prof_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                return [str(w).lower() for w in data.get("words", [])]
        except Exception as e:
            logger.warning("Could not load profanity words: %s", e)
    return []


def chunk_words(words: list[WordClip], max_chars: int = 20) -> list[CaptionChunk]:
    """Group sequential words into display chunks of 2-4 words, bounded by pauses and max chars."""
    if not words:
        return []

    chunks: list[CaptionChunk] = []
    curr_words: list[WordClip] = []
    curr_chars = 0

    for idx, w in enumerate(words):
        is_last = idx == len(words) - 1
        w_len = len(w.w)

        # Break condition: gap > 0.35s, ends in punctuation, or exceeding 4 words / 20 chars
        gap = (words[idx + 1].s_clip - w.e_clip) if not is_last else 0.0
        ends_punct = bool(re.search(r"[.?!]+$", w.w))

        curr_words.append(w)
        curr_chars += w_len + 1

        should_break = (
            is_last
            or len(curr_words) >= 4
            or curr_chars >= max_chars
            or gap > 0.35
            or ends_punct
        )

        if should_break and curr_words:
            chunk_s = curr_words[0].s_clip
            chunk_e = curr_words[-1].e_clip
            chunk_text = " ".join(item.w for item in curr_words).strip().upper()
            chunks.append(
                CaptionChunk(
                    words=curr_words,
                    s=round(chunk_s, 3),
                    e=round(chunk_e, 3),
                    text=chunk_text,
                )
            )
            curr_words = []
            curr_chars = 0

    return chunks


def _fmt_ass_time(seconds: float) -> str:
    """Format seconds into ASS timestamp H:MM:SS.cc (centiseconds)."""
    s_clamped = max(0.0, seconds)
    total_cs = round(s_clamped * 100)
    cs = total_cs % 100
    total_sec = total_cs // 100
    s = total_sec % 60
    total_min = total_sec // 60
    m = total_min % 60
    h = total_min // 60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _fmt_srt_time(seconds: float) -> str:
    """Format seconds into SRT timestamp HH:MM:SS,mmm (milliseconds)."""
    s_clamped = max(0.0, seconds)
    total_ms = round(s_clamped * 1000)
    ms = total_ms % 1000
    total_sec = total_ms // 1000
    s = total_sec % 60
    total_min = total_sec // 60
    m = total_min % 60
    h = total_min // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_ass(
    chunks: list[CaptionChunk],
    layout: str = "gameplay",
    out_path: Path | str = "captions.ass",
    mask_profanity_flag: bool = True,
    emphasis_indices: list[int] | None = None,
) -> Path:
    """Generate ASS subtitle file with Montserrat font and yellow karaoke word highlighting."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    emphasis_set = set(emphasis_indices or [])

    # Determine anchor Y position based on layout
    anchor_y = 1330
    if layout == "talking_head":
        anchor_y = 1250
    elif layout == "facecam":
        anchor_y = 915

    prof_words = _load_profanity_words() if mask_profanity_flag else []

    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Montserrat ExtraBold,84,&H00FFFFFF,&H00000000,&H00000000,&H00000000,-1,0,0,0,100,100,1,0,1,6,0,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    dialogue_lines: list[str] = []
    global_word_idx = 0

    for chunk in chunks:
        n_words = len(chunk.words)
        for w_idx, active_word in enumerate(chunk.words):
            # Timing: active word start to next word start (or chunk end for last word)
            w_start = active_word.s_clip
            w_end = chunk.words[w_idx + 1].s_clip if w_idx + 1 < n_words else active_word.e_clip
            if w_end <= w_start:
                w_end = w_start + 0.10

            t_start_ass = _fmt_ass_time(w_start)
            t_end_ass = _fmt_ass_time(w_end)

            # Build line text with active word highlighted yellow &H00FFFF& (BGR)
            rendered_words: list[str] = []
            for k, w_obj in enumerate(chunk.words):
                clean_w = w_obj.w.upper()
                if mask_profanity_flag:
                    clean_w = mask_profanity(clean_w, prof_words)

                word_pos = getattr(w_obj, "idx", global_word_idx + k)
                if k == w_idx:
                    # Highlighted active word
                    rendered_words.append(f"{{\\c&H00FFFF&}}{clean_w}{{\\r}}")
                elif w_obj.emphasis or (word_pos in emphasis_set):
                    # Permanent orange emphasis within chunk
                    rendered_words.append(f"{{\\c&H0088FF&}}{clean_w}{{\\r}}")
                else:
                    rendered_words.append(clean_w)

            text_body = " ".join(rendered_words)

            # Pop-in scale effect on the first word of each chunk
            if w_idx == 0:
                effect_tag = r"{\pos(540," + str(anchor_y) + r")\fscx85\fscy85\t(0,90,\fscx100\fscy100)}"
            else:
                effect_tag = r"{\pos(540," + str(anchor_y) + r")}"

            dialogue_lines.append(
                f"Dialogue: 0,{t_start_ass},{t_end_ass},Cap,,0,0,0,,{effect_tag}{text_body}"
            )
        global_word_idx += n_words

    full_ass = header + "\n".join(dialogue_lines) + "\n"
    p.write_text(full_ass, encoding="utf-8")
    return p


def write_srt(
    chunks: list[CaptionChunk],
    out_path: Path | str = "captions.srt",
    mask_profanity_flag: bool = True,
) -> Path:
    """Generate standard clean SRT subtitles without formatting tags."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    prof_words = _load_profanity_words() if mask_profanity_flag else []
    srt_blocks: list[str] = []

    for idx, ch in enumerate(chunks):
        t_start = _fmt_srt_time(ch.s)
        t_end = _fmt_srt_time(ch.e)

        clean_text = ch.text
        if mask_profanity_flag:
            words_in_text = clean_text.split()
            masked_words = [mask_profanity(tw, prof_words) for tw in words_in_text]
            clean_text = " ".join(masked_words)

        block = f"{idx + 1}\n{t_start} --> {t_end}\n{clean_text}\n"
        srt_blocks.append(block)

    p.write_text("\n".join(srt_blocks), encoding="utf-8")
    return p


def validate_ass(ass_path: Path | str, max_duration: float) -> bool:
    """Assert all ASS events are monotonic and bounded within [0, max_duration]."""
    p = Path(ass_path)
    if not p.is_file():
        return False

    content = p.read_text(encoding="utf-8")
    lines = content.splitlines()

    for line in lines:
        if line.startswith("Dialogue:"):
            parts = line.split(",", 9)
            if len(parts) >= 10:
                s_str = parts[1]
                e_str = parts[2]

                # Parse H:MM:SS.cc
                try:
                    s_parts = s_str.split(":")
                    s_sec = int(s_parts[0]) * 3600 + int(s_parts[1]) * 60 + float(s_parts[2])

                    e_parts = e_str.split(":")
                    e_sec = int(e_parts[0]) * 3600 + int(e_parts[1]) * 60 + float(e_parts[2])

                    if s_sec < 0 or e_sec < s_sec or e_sec > max_duration + 0.10:
                        return False
                except Exception:
                    return False

    return True
