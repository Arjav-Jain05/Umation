# 03. Stage 1: Ingest

Contents: 1 URL validation · 2 source_check · 3 Two-phase download strategy · 4 Audio download · 5 Transcription · 6 Tidy transcript · 7 Long VOD handling · 8 Failure handling

## 1. URL validation (API layer and stage)

Accept exactly one video URL matching one of:
- `https://www.youtube.com/watch?v=<11 chars>` (extra params allowed, ignore `list`/`index`)
- `https://youtu.be/<11 chars>`
- `https://www.youtube.com/live/<11 chars>`
- `https://m.youtube.com/watch?v=...`
Reject playlists, channels, `/shorts/` links (too short to clip), other sites (v1). Normalise to `https://www.youtube.com/watch?v=<id>`. Error `InvalidUrl` with a plain message.

## 2. `source_check` stage

Use `yt_dlp.YoutubeDL({"quiet": True, "skip_download": True, "noplaylist": True}).extract_info(url, download=False)`. Map fields to `SourceInfo` (02 section 6):
`id, title, channel, channel_url, uploader, upload_date, duration, live_status, license, view_count, like_count, description[:600], chapters, heatmap`. Take width/height/fps from the best video format.

Rules, in order:
1. `live_status in {"is_live","is_upcoming"}` -> `LiveNotFinished` ("This livestream has not ended. Come back when it is a finished video.").
2. `live_status == "post_live"` -> `LiveNotFinished` with "YouTube is still processing the replay; try again later".
3. `duration` is None or > `MAX_SOURCE_HOURS * 3600` -> `TooLong`.
4. Source policy (`config/source_policy.yaml`, see 10): match channel by `channel_id`, then by lower-cased `channel` name. `block` -> `SourceBlocked`. `allow` -> record `source_policy.status="allow"`.
5. Heatmap: `info.get("heatmap")` is a list of `{start_time, end_time, value}` with value 0..1 (higher = more replays and watching). Store as `{start,end,value}`. Compute `heatmap_avg_seg_s = duration / len(heatmap)`. If missing or empty store `null`. Not every video has one; never fail.
6. `license`: store the raw string. Treat strings containing "Creative Commons" as CC.
7. If upload date is more than 7 days old and domain is `gta6`, add a `warning` event "Older video: possible duplicate content" (info only).
Write `source_info.json`. Publish a `warning` for: no heatmap; non-CC license (generic reminder text from 10); duration > 6 h (long job).

## 3. Two-phase download strategy (the key to handling 8-hour streams)

Downloading an 8-hour 1080p stream can take 15+ GB and a long time. We do not do that unless needed.

- **Phase A (always):** download **audio only**, convert to 16 kHz mono WAV (`audio.wav`). 8 h ≈ 0.9 GB as WAV 16-bit.
- **Phase B (after planning):** download only the **video sections** needed for planned clips (`segments` stage, spec in 05 section 1).
- If the source duration <= 40 minutes (`SMALL_VIDEO_MIN=40`), Phase B downloads the **full video once** instead (one segment covering everything) because it is simpler and fast. Both modes produce the same `segments.json` contract, so later stages do not care.

## 4. Audio download (`download.py: download_audio`)

yt-dlp options (verify names against the installed version):
```
format: "bestaudio/best"
outtmpl: <work>/audio_src.%(ext)s
postprocessors: [{"key":"FFmpegExtractAudio","preferredcodec":"wav"}]
postprocessor_args: ["-ar","16000","-ac","1"]
noplaylist: True, retries: 5, fragment_retries: 5, socket_timeout: 30,
concurrent_fragment_downloads: 4, quiet: True, no_warnings: True
progress_hooks: [publish progress 0..1 into SSE for this stage]
```
Result must be `audio.wav` mono 16 kHz. Verify with ffprobe (duration within 2 s of `source_info.duration_s`); otherwise `DownloadFailed`. Retry the whole download once after running the yt-dlp updater if it fails with an extraction error.

## 5. Transcription (`transcribe.py`)

- Library: `faster_whisper.WhisperModel(settings.whisper_model, device=settings.whisper_device, compute_type=settings.whisper_compute)`.
- Split long audio into **30-minute chunks with 15 s overlap** using ffmpeg stream copy of the WAV (`-ss/-t`), so a crash resumes at chunk granularity. Store finished chunk results in `data/work/<job>/asr/chunk_<n>.json`. Offset each chunk's timestamps by its start.
- `model.transcribe(path, ...)` arguments:
  - `beam_size=5`
  - `word_timestamps=True`
  - `vad_filter=True`, `vad_parameters={"min_silence_duration_ms": 500}`
  - `condition_on_previous_text=False` (prevents repetition loops)
  - `temperature=[0.0, 0.2, 0.4]` (fallback temperatures)
  - `language=None` for auto on the first chunk, then fix the detected language for all later chunks (log it). If `WHISPER_LANGUAGE != "auto"` use it.
  - `initial_prompt` = the domain prompt built from `config/glossary_gta6.yaml` terms (comma-separated, max 200 chars) when `PROJECT_DOMAIN=gta6`, else `None`.
- Overlap de-duplication: for chunk k > 0, discard words with `s < chunk_start + 7.5` (half the overlap) and discard from chunk k-1 words with `s >= next_chunk_start + 7.5`.
- Discard hallucinations: words whose probability `p < 0.30` AND which sit in a VAD-silence region are dropped; drop any run of >= 4 identical consecutive words.
- After the last chunk: `del model; gc.collect()` (VRAM release).
- Publish progress as processed audio seconds / total.
- OOM: retry per 01 section 4.

## 6. Tidy transcript (`tidy_transcript.py`)

Build `sentences`:
1. Start a new sentence after a word whose text ends in `. ? !` (and the next word starts with a capital letter or digit), or when the gap to the next word > 0.80 s.
2. If a sentence has > 30 words, split at the nearest comma or gap > 0.35 s to the middle; else at the middle word.
3. Merge a sentence with < 3 words into the previous one if the gap < 0.5 s.
4. `wpm = words / (e - s) * 60`.
Filler detection: words in `{"um","uh","erm","er","ah","hmm","uhm","mm"}` (lower-case, punctuation stripped) go into `fillers`. "like", "you know", "basically" are NOT fillers (never auto-removed).
Write `transcript.json`. Also write plain `transcript.txt` for debugging: one sentence per line with `[hh:mm:ss] id text`.

## 7. Long VOD handling

- Everything downstream is chunked or windowed; no stage may load the full word list into one LLM prompt. Chunking is defined in 04.
- Progress and ETA: report seconds processed per stage.
- Memory: the transcript for 8 h is about 70k words; keep as Python lists of small dicts; fine.
- Streams contain long dead stretches (waiting, intermissions, chat reading). Pre-filter in `chunker.py`: mark sentences in regions with `wpm < 40` for > 90 s or with > 80% filler/short-word content as `dead`; pass them to the LLM as `[...quiet...]` placeholders to save tokens (only text compression, timestamps untouched).

## 8. Failure handling

| Failure | Behaviour |
|---|---|
| Video unavailable/private/age-gated | `SourceUnavailable`: "This video is not publicly available." (no workaround) |
| yt-dlp extraction error | update yt-dlp once, retry once, else `DownloadFailed` with the last error line |
| Disk space | `DiskSpace` before download |
| Whisper CUDA problems | fall back per 01; continue with a warning |
| No speech found (< 20 words) | job fails with `NoCandidates` and message "No speech detected; this tool clips talking content" (for GTA, gameplay without commentary is not clippable by transcript) |
| Cancel | stop between chunks |
