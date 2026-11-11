"""Audio transcription using faster-whisper on CUDA with chunked processing and VRAM release."""

from __future__ import annotations

import contextlib
import gc
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Compatibility fix for newer PyAV (v14+) where metadata_errors was removed from av.open
try:
    import av
    _orig_av_open = av.open
    def _compat_av_open(*args: Any, **kwargs: Any) -> Any:
        kwargs.pop("metadata_errors", None)
        return _orig_av_open(*args, **kwargs)
    av.open = _compat_av_open
except Exception:
    pass

from app.core.errors import NoCandidates, TranscribeFailed
from app.core.schemas import Transcript, Word
from app.pipeline.context import JobContext
from app.pipeline.s1_ingest.tidy_transcript import build_sentences, detect_fillers, write_debug_txt
from app.utils.ffmpeg import probe, run_ffmpeg

logger = logging.getLogger("app.pipeline.s1_ingest.transcribe")


@dataclass
class AudioChunk:
    index: int
    start_s: float
    duration_s: float
    path: Path


def split_audio_chunks(
    audio_path: Path,
    work_dir: Path,
    chunk_s: int = 1800,
    overlap_s: int = 15,
) -> list[AudioChunk]:
    """Split audio into 30-minute chunks with 15s overlap for incremental ASR and resume."""
    p_info = probe(audio_path)
    total_dur = p_info.duration

    chunks_dir = work_dir / "asr_chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    if total_dur <= (chunk_s + 60):
        # Small file: single chunk without slicing
        return [AudioChunk(index=0, start_s=0.0, duration_s=total_dur, path=audio_path)]

    chunks: list[AudioChunk] = []
    start = 0.0
    idx = 0

    while start < total_dur:
        dur = min(float(chunk_s + overlap_s), total_dur - start)
        out_chunk = chunks_dir / f"chunk_{idx:03d}.wav"

        # Extract chunk via ffmpeg if not already extracted
        if not out_chunk.exists() or out_chunk.stat().st_size < 1000:
            cmd = [
                "-ss",
                f"{start:.3f}",
                "-t",
                f"{dur:.3f}",
                "-i",
                str(audio_path),
                "-c",
                "copy",
                str(out_chunk),
            ]
            run_ffmpeg(cmd, check=True)

        chunks.append(AudioChunk(index=idx, start_s=start, duration_s=dur, path=out_chunk))
        start += chunk_s
        idx += 1

    return chunks


def release_model(model: Any) -> None:
    """Explicitly release Whisper model instance and reclaim GPU VRAM."""
    if model is not None:
        with contextlib.suppress(Exception):
            del model
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    logger.info("Released Whisper model and cleared GPU cache")


def merge_chunks(
    chunk_results: list[tuple[AudioChunk, list[Word]]],
) -> list[Word]:
    """Deduplicate words in overlap regions and remove repetitive hallucinations."""
    if not chunk_results:
        return []

    merged_words: list[Word] = []

    for i, (chunk, words) in enumerate(chunk_results):
        is_first = i == 0
        is_last = i == len(chunk_results) - 1

        half_overlap = 7.5
        min_allowed_s = 0.0 if is_first else (chunk.start_s + half_overlap)
        max_allowed_s = 9999999.0 if is_last else (chunk.start_s + chunk.duration_s - half_overlap)

        for w in words:
            # Word times are absolute video timeline seconds
            if w.s >= min_allowed_s and w.s < max_allowed_s:
                merged_words.append(w)

    # Filter repetitive hallucination loops (>= 4 identical consecutive words)
    filtered_words: list[Word] = []
    for w in merged_words:
        token = w.w.strip().lower()
        if len(filtered_words) >= 3:
            prev3 = [prev.w.strip().lower() for prev in filtered_words[-3:]]
            if prev3[0] == prev3[1] == prev3[2] == token:
                continue
        filtered_words.append(w)

    # Re-index words sequentially
    for new_i, w in enumerate(filtered_words):
        w.i = new_i

    return filtered_words


def run(ctx: JobContext) -> None:
    """Execute Stage 1: transcribe."""
    if ctx.artifact_ok("transcript.json", Transcript):
        logger.info("[%s] transcript.json already exists and validates; skipping transcribe", ctx.job_id)
        return

    audio_path = ctx.work_dir / "audio.wav"
    if not audio_path.exists():
        raise TranscribeFailed(f"Audio file not found at {audio_path}")

    ctx.progress("transcribe", 0.02, "Preparing audio for Whisper transcription...")
    chunks = split_audio_chunks(audio_path, ctx.work_dir)
    total_audio_s = sum(ch.duration_s for ch in chunks)

    # Setup initial domain prompt for GTA 6
    initial_prompt: str | None = None
    if ctx.settings.project_domain == "gta6":
        glossary_path = ctx.settings.project_root / "config" / "glossary_gta6.yaml"
        if glossary_path.exists():
            import yaml

            try:
                with open(glossary_path, encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                terms = cfg.get("terms", [])
                if terms:
                    prompt_str = ", ".join(terms)
                    initial_prompt = prompt_str[:200]
            except Exception as e:
                logger.warning("Could not load glossary prompt: %s", e)

    # Setup faster-whisper model
    model = None
    try:
        from faster_whisper import WhisperModel

        model_target = ctx.settings.whisper_model
        whisper_root = ctx.settings.weights_dir / "whisper"
        if whisper_root.exists():
            for cand in [
                whisper_root / f"models--mobiuslabsgmbh--faster-whisper-{ctx.settings.whisper_model}",
                whisper_root / f"models--Systran--faster-whisper-{ctx.settings.whisper_model}",
                whisper_root / "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo",
                whisper_root / "models--Systran--faster-whisper-large-v3",
                whisper_root / "models--Systran--faster-whisper-tiny",
            ]:
                if cand.exists():
                    snapshots = [
                        s for s in (cand / "snapshots").glob("*")
                        if (s / "model.bin").is_file() and (s / "model.bin").stat().st_size > 70_000_000
                        and ("large" not in cand.name or (s / "model.bin").stat().st_size > 1_500_000_000)
                    ]
                    if snapshots:
                        model_target = str(snapshots[0])
                        break

        logger.info(
            "Loading WhisperModel(%s, device=%s, compute_type=%s)",
            model_target,
            ctx.settings.whisper_device,
            ctx.settings.whisper_compute,
        )
        model = WhisperModel(
            model_target,
            device=ctx.settings.whisper_device,
            compute_type=ctx.settings.whisper_compute,
        )
    except Exception as e:
        logger.error("Failed to initialize WhisperModel: %s", e)
        raise TranscribeFailed(
            f"Failed to load Whisper model on {ctx.settings.whisper_device}: {e}",
            hint="Ensure nvidia-cublas and nvidia-cudnn are installed or set WHISPER_DEVICE=cpu",
        ) from e

    chunk_results: list[tuple[AudioChunk, list[Word]]] = []
    asr_cache_dir = ctx.work_dir / "asr_cache"
    asr_cache_dir.mkdir(parents=True, exist_ok=True)

    detected_lang: str | None = (
        None if ctx.settings.whisper_language == "auto" else ctx.settings.whisper_language
    )

    try:
        processed_seconds = 0.0
        for chunk in chunks:
            ctx.check_cancel()
            cache_file = asr_cache_dir / f"words_{chunk.index:03d}.json"

            # Check if this chunk was previously transcribed (resume)
            if cache_file.exists():
                try:
                    words_raw = json.loads(cache_file.read_text(encoding="utf-8"))
                    chunk_words = [Word.model_validate(w) for w in words_raw]
                    chunk_results.append((chunk, chunk_words))
                    processed_seconds += chunk.duration_s
                    frac = min(0.95, processed_seconds / max(1.0, total_audio_s))
                    ctx.progress("transcribe", frac, f"Loaded transcribed chunk {chunk.index + 1}/{len(chunks)}")
                    continue
                except Exception:
                    pass

            # Run transcription for chunk
            logger.info("Transcribing chunk %d (start: %.1fs, dur: %.1fs)...", chunk.index, chunk.start_s, chunk.duration_s)
            segments_gen, info = model.transcribe(
                str(chunk.path),
                beam_size=5,
                word_timestamps=True,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                condition_on_previous_text=False,
                temperature=[0.0, 0.2, 0.4],
                language=detected_lang,
                initial_prompt=initial_prompt,
            )

            # Lock in detected language
            if detected_lang is None and info.language:
                detected_lang = info.language
                logger.info("Whisper detected source language: '%s' (prob %.2f)", detected_lang, info.language_probability)

            chunk_words: list[Word] = []
            word_idx = 0
            for seg in segments_gen:
                if not seg.words:
                    continue
                for w in seg.words:
                    abs_start = round(chunk.start_s + w.start, 3)
                    abs_end = round(chunk.start_s + w.end, 3)
                    # Discard words with very low probability in quiet regions
                    prob = float(w.probability) if hasattr(w, "probability") else 1.0
                    if prob < 0.25:
                        continue
                    chunk_words.append(
                        Word(
                            i=word_idx,
                            w=w.word.strip(),
                            s=abs_start,
                            e=abs_end,
                            p=round(prob, 3),
                        )
                    )
                    word_idx += 1

            # Cache chunk result
            cache_file.write_text(
                json.dumps([w.model_dump() for w in chunk_words], ensure_ascii=False),
                encoding="utf-8",
            )
            chunk_results.append((chunk, chunk_words))

            processed_seconds += chunk.duration_s
            frac = min(0.95, processed_seconds / max(1.0, total_audio_s))
            ctx.progress("transcribe", frac, f"Transcribed {processed_seconds:.0f}s of audio ({chunk.index + 1}/{len(chunks)})")

    finally:
        release_model(model)

    # Merge all chunk words
    words = merge_chunks(chunk_results)
    if len(words) < 20:
        logger.error("[%s] Insufficient speech found in source audio (%d words)", ctx.job_id, len(words))
        raise NoCandidates("No speech detected; this tool clips talking content")

    # Run sentence segmentation and filler identification
    sentences = build_sentences(words)
    fillers = detect_fillers(words)

    duration_s = words[-1].e if words else 0.0
    transcript = Transcript(
        language=detected_lang or "en",
        model=ctx.settings.whisper_model,
        duration_s=round(duration_s, 3),
        words=words,
        sentences=sentences,
        fillers=fillers,
    )

    ctx.write_artifact("transcript.json", transcript)
    write_debug_txt(sentences, ctx.work_dir / "transcript.txt")

    ctx.progress(
        "transcribe",
        1.0,
        f"Transcription complete: {len(words)} words, {len(sentences)} sentences, {len(fillers)} fillers",
    )
