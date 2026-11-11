# FINAL TASK (v4, LOCAL ONLY): Upgrade the existing shorts-clipper into a layered, audience-aware, fully local pipeline with a live "quality threshold" slider

This file replaces every earlier version. You are working inside an ALREADY BUILT project (Klap.app-style: paste a YouTube link, the app finds every viral-worthy moment, cuts 9:16 shorts with captions, writes titles/descriptions/SEO/credits, makes a topic-based thumbnail). Do NOT rewrite from scratch. Inspect the repo first and modify it in place, on a git branch (`feature/final-local-layered`), committing in small steps. Do not stop to ask questions; choose sensible defaults and record them in `docs/CHANGES.md`.

## 0. Golden rules
1. **ZERO cloud AI at runtime.** Remove all Gemini/OpenAI/Anthropic/HF-Inference calls, keys and UI text. Only allowed internet at runtime: yt-dlp (video, metadata, comments, chat replay). Weights are downloaded once during setup; afterwards the app works offline (`HF_HUB_OFFLINE=1`). Add a network guard test that fails if any LLM-related outbound call is attempted (only `localhost:11434` Ollama allowed).
2. **Evidence beats opinion.** A small local LLM is a weak judge of virality. So the pipeline stacks independent evidence (audience data, audio events, emotion, text, vision) and lets math plus a bias-controlled head-to-head rerank decide, not one model's mood.
3. **Every layer is optional and fails soft.** If a model is missing or errors, skip that layer, log it, continue.
4. **Verify before trusting.** Model names, Ollama tags, licenses and sizes below came from web research in Nov 2026 and may be wrong or stale. Check Ollama library / Hugging Face / ModelScope yourself; record deviations in `docs/MODELS.md`.

## 0A. EXECUTION PROTOCOL (autonomous, phased, self-healing) - read this before anything else
This spec is large. Do NOT try to build it in one pass and do NOT wait for the user between phases. Build it in the phases below, strictly in order, and prove each phase works before starting the next.

**Setup of your own working memory**
1. Copy this whole file into the repo as `docs/SPEC.md`. Before each phase, re-read the sections that phase uses (context fades over a long job).
2. Extract every "must/never/default" requirement into `docs/CHECKLIST.md` as checkboxes, grouped by phase.
3. Keep `PROGRESS.md` (and `.state/progress.json`) updated after every step: phase, status (`pass` / `degraded` / `failed`), the checks you actually ran with real output excerpts, timings, peak VRAM, deviations from the spec. If you are restarted, read it and resume where you stopped.
4. Create `scripts/selftest.py --phase N` (and `--all`) that runs that phase's gate checks in one command, so the user can re-run them any time.

**Per-phase loop (mandatory)**
1. Implement the phase.
2. Run the phase gate checks below. A check passes ONLY if you actually executed it and saw the output; paste the evidence into `PROGRESS.md`. Never write "should work" or tick a box you did not verify.
3. If a check fails, run the **fix loop**: reproduce -> read the logs/traceback -> list at most 3 likely causes -> apply the smallest fix -> re-run the SAME failing check. Use the self-healing playbook below first. Try up to 5 genuinely different fixes per failure.
4. When the gate passes: commit (`phase-N: <summary>`), tag `phase-N-pass`, update `PROGRESS.md`, then go straight to the next phase.
5. If a gate still fails after the fix attempts: mark the phase `degraded`, turn the failing layer off via its config flag, write what broke and what the user must do in `docs/TROUBLESHOOTING.md`, and CONTINUE with the next phase (the project must stay usable). Never fake a pass, never remove a golden rule to make a check pass, and never use a cloud API as a workaround.
6. Self-review at the end of every phase: walk through that phase's spec bullets one by one; list anything not implemented explicitly in `PROGRESS.md` ("not done: X, because Y"). Silent skipping is not allowed.
7. Record every problem you solved in `docs/TROUBLESHOOTING.md` as symptom -> cause -> fix, so it is reusable.

**Test material:** use `samples/` if the user put a video there; otherwise fetch a short Creative Commons or public-domain video with yt-dlp (about 5 minutes with clear speech); for pure mechanics tests you may synthesize audio/video with ffmpeg. Later run one 60-minute video as a stress test. If YouTube blocks the download, accept a local file path and continue.

**PHASES AND GATES**
- **Phase 0 - Preflight and environment.** Audit the repo (find every LLM call, the render code, the UI). Create the branch. Check GPU/VRAM, free space on D:, Python/Node/ffmpeg/yt-dlp. Install dependencies into pinned environments (`requirements.lock`). Set the env vars, install/restart Ollama, download the CORE weights (`--core`: faster-whisper large-v3-turbo, `qwen3.5:9b`, `gemma4:e4b`) into `D:\Open_Source_Weights`, write `scripts/check_local_setup.py`. *Gate:* health check all PASS for core; Ollama model files physically under `D:\Open_Source_Weights\ollama`; a 10-second file transcribes ON THE GPU; `qwen3.5:9b` returns schema-valid JSON for a test prompt; `nvidia-smi` shows the processes on the NVIDIA GPU (this laptop also has an integrated GPU).
- **Phase 1 - Core clips (usable product).** Remove all cloud code and add the network guard. Layer 0 transcription, ONE proposer (Layer 2), boundary snapping (Layer 7), basic NVENC render with default captions, results saved to disk. *Gate:* end-to-end on the 5-minute sample produces at least 1 valid 9:16 clip with captions in sync; network-guard test passes with the network disabled; peak VRAM under 7.5 GB; no cloud import/key left (grep proves it).
- **Phase 2 - Slider, candidates store, caption presets.** Candidate database with full score breakdowns, scoring skeleton (Layer 6), the quality-threshold slider and results page (section 6), 7 caption presets, "Render selected". *Gate:* slider triggers zero model calls (assert in a test); moving it changes the clip count; only selected clips render; a browser smoke test (Playwright or equivalent) drives the slider; typecheck/build pass.
- **Phase 3 - Audience signals and sensors.** Section 4 signals (heatmap, comments, chat) plus Layer 1 sensors (SenseVoice, AST, loudness, text emotion, hype lexicon, scene cuts/motion, bge topics and dedup), hot-zone map, event timeline fed to Layer 2, fusion v1 with weight redistribution when a signal is missing. *Gate:* each sensor runs alone on a 2-minute sample and writes its track; a video with no heatmap/chat still works; fusion weights re-normalize.
- **Phase 4 - Multi-model quality.** Second proposer, critic, arc stitcher, head-to-head rerank, hardened local model manager (section 7), bake-off harness, feedback logging and `train_ranker.py`. *Gate:* manager failure tests pass (OOM, timeout, bad JSON, model missing); rerank position-bias test passes; ablation (Qwen-only vs two proposers vs full funnel) produces three clip lists with timings.
- **Phase 5 - Visual layer, metadata, thumbnails, polish.** Layer 5 (SigLIP 2, RapidOCR, optional SmolVLM2), Layer 8 metadata ensemble, Layer 9 thumbnails, game profile, Fast/Balanced/Best presets, all docs. *Gate:* full end-to-end on the 5-minute sample and the 60-minute stress test; peak VRAM under 7.5 GB; final report written.

**SELF-HEALING PLAYBOOK (try these before anything exotic)**
| Symptom | Likely cause | Fix |
|---|---|---|
| Whisper falls back to CPU, or "cublas/cudnn could not be loaded" | faster-whisper (CTranslate2) needs CUDA 12 cuBLAS/cuDNN 9 even if PyTorch is CUDA 13 | `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`, add their `bin` folders with `os.add_dll_directory`/PATH, re-test on a 10 s file; last resort: smaller model on CPU int8, mark `degraded` |
| `torch.cuda.is_available()` is False | CPU-only torch wheel | read `nvidia-smi` CUDA version, reinstall torch from the matching CUDA wheel index |
| `ollama pull` says model not found | wrong tag | check `ollama list` and the Ollama library page, try alternates (`qwen3.5:9b-q4_K_M`, `gemma4:e4b-it-q4_K_M`, `qwen3.5:4b`); else import a Q4_K_M GGUF with `ollama create` and a Modelfile; update `config/models.yaml` and `docs/MODELS.md` |
| Models land on C: | env var not applied to the Ollama service | set `OLLAMA_MODELS`, fully quit and restart Ollama, move files, re-pull |
| CUDA out of memory or VRAM above 7.5 GB | two models loaded, big context, vision projector, other GPU apps | `ollama ps`; `keep_alive: 0`; unload Whisper first; `num_ctx` 8192 -> 4096; Q4 not Q8; skip the vision projector for text-only runs; make sure Ollama uses the NVIDIA GPU not the iGPU |
| Invalid JSON or schema errors | model drift, thinking text, long window | use JSON-schema `format`, `think: false`, lower temperature, shorter window, add one example, one repair retry, then switch model |
| Very slow or endless output | thinking tokens | disable thinking for bulk, cap `num_predict` |
| Captions drift after cutting | stream-copy or wrong seek | re-encode the cut, use absolute PTS, add a sync test |
| ffmpeg `subtitles`/`ass` filter fails on Windows | drive-letter and backslash escaping | use forward slashes, escape the colon (`C\:/...`) or run from the file's folder |
| NVENC not available | old driver or ffmpeg build | `ffmpeg -encoders` check; update driver; fall back to libx264 and note it |
| yt-dlp 403/signature error or no heatmap | outdated yt-dlp or video has no heatmap | `pip install -U yt-dlp`; treat a missing heatmap as "missing", not zero; else accept a local file |
| Weight download stalls | network or disk | resume with backoff, verify SHA256, check disk space |
| Dependency conflicts (torch vs onnxruntime, numpy 2, FunASR) | shared environment | pin versions in `requirements.lock`; run FunASR/RapidOCR in a separate venv and call them through a subprocess worker |
| Out of RAM (16 GB) | big batches or parallel renders | chunk audio, set `parallel_renders` to 1-2, stream frames |
| Slow stages | too many layers for the clip length | profile, shrink windows, switch to the Fast preset, log the bottleneck |
| UI build or type errors | front-end drift | run typecheck, lint, build and the browser smoke test |
| GPU thermal throttling | laptop heat | cool-down pause between long GPU stages |
| Windows path problems | spaces, unicode, long paths | `pathlib`, quote every path, avoid spaces in cache dirs |

**Definition of done:** Phases 0-5 are `pass` (or honestly `degraded` with reasons), `scripts/selftest.py --all` was run and its output is in `PROGRESS.md`, and a final report exists with: what works, what is degraded, models and versions with sizes, peak VRAM, per-layer timings, the ablation clip lists, and the exact commands the user runs day to day (start the app, paste a link, move the slider, render).

## 1. Machine (design for exactly this)
ASUS TUF F15, Windows, NVIDIA RTX 4060 **8 GB VRAM**, 16 GB RAM, 1 TB SSD.
- One heavy GPU model at a time; unload between stages. Keep any model to about 6.5 GB VRAM or less (leave room for context). 26B/31B models do not fit; do not use them.
- LLM context 8K default (up to 16K only if measured VRAM allows). Chunk long inputs.
- Render with `h264_nvenc` (fallback `libx264`). Download source as H.264 (avc1) mp4 up to 1080p (AV1 roughly doubles processing time).
- Watch thermals: configurable cool-down pause between long GPU stages.

## 2. Weights location: D:\Open_Source_Weights
```
D:\Open_Source_Weights\
  ollama\ (OLLAMA_MODELS)   huggingface\ (HF_HOME, HF_HUB_CACHE)   modelscope\ (MODELSCOPE_CACHE)
  torch\ (TORCH_HOME)       whisper\ (faster-whisper download_root)  onnx\ (ONNX/RapidOCR/face/speaker models)
  manifest.json  <- name, source URL, revision, size, SHA256, local path, date for every model
```
1. Check free space on D: first (need 60 GB free; abort with a clear message otherwise).
2. Set env vars persistently (`setx`) and again inside the app process from `.env`. For Ollama set `OLLAMA_MODELS`, fully restart Ollama, and VERIFY by pulling a small model and seeing files land there.
3. Never rely on default cache paths in code: pass `download_root=`, `cache_dir=`, `local_dir=` explicitly.
4. `scripts/download_weights.py`: idempotent, resumable, progress table, updates `manifest.json`, verifies each model loads. Flags: `--core` (minimum viable set), `--all`, `--only <layer>`.
5. Prefer `safetensors` over pickle `.bin` weights; never run code from a model repo without reading it (`trust_remote_code=False` by default).

## 3. Reference projects (study for ideas; obey licenses)
Search the web and read these, plus look for more yourself. For each, record in `docs/REFERENCES.md`: what idea we took, license, and whether any code was copied.
| Project | What to learn |
|---|---|
| JayWebtech/autoshorts (Tauri/Rust, local-first) | 7 caption style presets (modern box, yellow outline, minimal shadow, cyan, yellow box, green, red/gaming), responsive font scaling to output width, Windows font fallback (Segoe UI Bold, Arial Bold), the absolute-timestamp fix so captions stay in sync after output seeking |
| ColinGPT9/clips-studio "Clips Kitty" (AGPL-3.0; local Ollama + faster-whisper) | Closest design to ours: audio/visual/reaction signals normalized WITHIN each video; LLM sees the transcript plus a timeline of those events; finalists compared head-to-head in one rerank call (relative judgment is easier for small models); score 0-100 with a quality bar and no clip cap; webcam+game layout for gaming; word-synced captions; non-destructive editor |
| JeremySNR/clip-forge (MIT) | hook-build-payoff micro-story clip selection, ending review, auto zoom/punch-ins, LR-ASD active-speaker detection on ONNX |
| mutonby/openshorts (MIT), fralapo/clippyme ("auditable virality scoring", outcome calibration), RafaelGodoyEbert/ViralCutter, Shaarav4795/ClippedAI, Anil-matcha/AI-Youtube-Shorts-Generator, FujiwaraChoki/supoclip (AGPL), nirvagold/stream-clipper (audio + chat overlap scoring), VideoHighlighter (offline scene/motion/audio/object detection with Ollama + Whisper) | face tracking, subtitles, auditable score breakdowns, chat-spike scoring, feedback calibration |
**License rule:** MIT/Apache/BSD code may be reused with attribution; AGPL, GPL or unknown-license code must NOT be copied (ideas only, rewrite from scratch). Never vendor code you have not license-checked.

## 4. Audience-first signals (free, human-validated, strongest evidence available)
Collect these with yt-dlp BEFORE any AI runs. They are real human behavior, so they outrank any model.
1. **YouTube "Most replayed" heatmap**: yt-dlp exposes `info["heatmap"]` (list of `start_time`, `end_time`, `value`) for videos that have it. Not all videos have one (needs enough views). Normalize to 0-1 per video.
2. **Timestamped comments**: `--write-comments`; parse timestamps like `3:42` or `1:03:10` in comment text, weight by likes, bucket into 10 s bins.
3. **Live-stream chat replay** (Twitch/YouTube VODs with replay): use `chat-downloader` (or TwitchDownloader JSON); compute messages/s and unique chatters/s per second, plus spikes and clip-request words ("clip it", "pog", "lol", "omg", "wtf").
4. **Source chapters** (`info["chapters"]`) as soft topic boundaries.
All four are optional per video: use what exists, mark the rest missing (never as zero).

## 5. THE LAYERED PIPELINE (funnel: cheap and whole-video first, expensive and shortlist-only later)

### Layer 0 - Transcription (once per video, cached by video id)
- **faster-whisper `large-v3-turbo`**, `compute_type="int8_float16"`, word timestamps ON, Silero VAD ON, `condition_on_previous_text=False` (avoids repetition loops).
- Pass a per-game **glossary** (character names, places, slang, streamer names) via `initial_prompt`/`hotwords` from `profiles/<game>.yaml` so names are spelled right.
- Optional (default OFF): WhisperX forced alignment for tighter word timing; Demucs vocal separation only if a test shows game audio is ruining the transcript.
- Alternatives: `distil-large-v3.5` (English, faster); NVIDIA Parakeet TDT 0.6B v3 (English, extremely fast). Free the GPU afterwards (`del`, `gc.collect()`, `torch.cuda.empty_cache()`).

### Layer 1 - Sensors (whole video; every output saved as a per-second track, normalized per video using robust percentiles)
1. **Voice emotion + events**: SenseVoice-Small (`FunAudioLLM/SenseVoiceSmall` via FunASR, about 234 MB): emotion tags and laughter/applause/cry events on the commentary. Supports en/zh/yue/ja/ko. Optional extra: `emotion2vec_plus_large/base`.
2. **Sound-event detection on the full mix (game audio matters for gaming)**: `MIT/ast-finetuned-audioset-10-10-0.4593` (Audio Spectrogram Transformer, 527 AudioSet classes, about 346 MB, BSD-3) on 10 s windows with 5 s hop. Track: Explosion, Gunshot/gunfire, Machine gun, Siren, Screaming, Laughter, Cheering, Applause, Skidding/tire squeal, Vehicle horn, Helicopter. Fast CPU alternative: YAMNet (3.7M params). Class list is configurable per game profile.
3. **Loudness/energy**: ffmpeg `ebur128` or librosa RMS: peaks, sudden jumps, silence-then-explosion payoff shapes.
4. **Text emotion** per sentence: `j-hartmann/emotion-english-distilroberta-base` (CPU ok); optional `SamLowe/roberta-base-go_emotions`.
5. **Hype lexicon + pace**: per-game configurable words/phrases, exclamation/question density, words-per-minute changes.
6. **Scene cuts** (PySceneDetect) and **motion energy** (OpenCV frame-difference or optical flow at 2 fps).
7. **Topic boundaries + dedup**: `BAAI/bge-small-en-v1.5` (about 130 MB, CPU) sentence embeddings; distance drops = topic shifts; cosine similarity for de-duplicating near-identical candidates.
8. **Facecam/speaker (optional)**: MediaPipe face detection; optional LR-ASD ONNX active-speaker (from ClipForge, MIT) to keep the crop on whoever is speaking.
Output: a **hot-zone map** (ranges where several sensors and audience signals overlap) and a per-second **timeline of events** in compact text form for the LLM ("00:41 crowd laughter, 00:43 loud + shouting, 00:44 explosion sound").

### Layer 2 - Proposers (two LLM families read transcript windows plus the event timeline)
- Windows of 6-8 min of speech (60-90 s overlap, under about 6K tokens), each with its hot-zone hints and event timeline attached.
- **Qwen3.5 9B Q4_K_M** (Ollama `qwen3.5:9b`; about 5.7-6.6 GB; 262K ctx; Apache 2.0) and **Gemma 4 E4B** (`gemma4:e4b`; about 5 GB Q4 plus about 1 GB multimodal projector; text, image AND audio input; Apache 2.0). Different families make different mistakes. NOTE: Ollama's default `gemma4` tag may pull a larger build than Q4; check size and prefer a Q4_K_M or QAT build.
- Ollama structured output (JSON schema) + pydantic validation. Thinking off for this bulk pass.
- Merge: candidates from both models overlapping more than 50 percent are the same candidate; set `agreement_count`. Also seed candidates from Layer 1 hot zones and audience peaks that no LLM proposed (the LLM may only ADD context or reject, never be the only gate).
- Run model A on all windows, unload (`keep_alive: 0`), run model B.
- Optional stretch (default OFF): Gemma 4 12B (QAT about 7.2 GB, "barely fits" on 8 GB): test with `num_ctx` 4096 and nothing else on the GPU; adopt only if the health check and bake-off (section 9) say it beats E4B.

### Layer 3 - Critic and arc stitcher (thinking mode ON; few calls)
- For each shortlisted candidate (about 3x the expected clip count): text plus about 20 s context each side. Narrow questions: strong first-3-seconds hook? makes sense alone? has payoff/ending? cut mid-sentence? boring setup? anything against platform rules?
- Prefer the model family that did NOT propose that candidate.
- **Arc stitcher**: gets only candidate summaries (small context); groups one story into Part 1/2/3, each ending on a beat or cliffhanger with its own hook.

### Layer 4 - Head-to-head rerank (the biggest quality trick for small models)
- Small models score everything in a narrow band; ranking is easier than rating. Take the finalists, split into shuffled batches of 5-6, ask each judge "rank these from most to least likely to hold a viewer, using only these criteria", repeat 3 times with different shuffles and with 2-3 different judges (Qwen3.5 9B, Gemma 4 E4B, optional third family **Ministral 3 8B** about 6.0 GB, Apache 2.0). Average ranks, convert to a `rerank_score` 0-100. Shuffling cancels position bias. Log every ranking for auditing.

### Layer 5 - Visual evidence (shortlist only, never the whole video)
1. **SigLIP 2** (`google/siglip2-base-patch16-224`, Apache 2.0) zero-shot frame labels at 1 fps inside candidate ranges. Labels from the game profile, e.g. "car explosion", "police chase", "helicopter", "shootout", "wanted level", "dramatic cutscene" vs negatives "menu screen", "loading screen", "map screen", "static scene". Output `visual_action` and a dead-footage flag.
2. **On-screen text triggers** with RapidOCR (ONNX, small): configurable trigger words per game ("WASTED", "BUSTED", "MISSION PASSED", etc.; user edits the list), sampled at 1 fps only inside candidate ranges, cropped to likely UI regions.
3. **SmolVLM2** (`HuggingFaceTB/SmolVLM2-2.2B-Instruct` or the 500M variant, about 4.5 GB in bf16) only as a tie-breaker that explains what is on screen; optional.
4. **Optional audio judge**: Gemma 4 E4B can take audio input; if (and only if) the installed runtime really supports audio input, let it rate the 10-30 s audio of the top candidates for energy and hook; otherwise skip.

### Layer 6 - Fusion and the quality score (0-100)
`quality = w_aud*audience + w_ev*audio_events + w_emo*emotion + w_hype*text_hype + w_llm*llm_consensus + w_crit*critic + w_rank*rerank + w_vis*visual + w_agree*agreement + w_pers*personal_ranker`
- Weights live in `config/scoring.yaml`, editable. Starting values: audience 0.18 (only when present; redistribute the weight when missing), audio_events 0.12, emotion 0.10, text_hype 0.05, llm_consensus 0.12, critic 0.13, rerank 0.15, visual 0.08, agreement 0.04, personal_ranker 0 until trained.
- Every signal is normalized WITHIN the video (a quiet podcast and a screaming stream both get meaningful peaks).
- Store EVERY candidate above a floor (default 35) with its full score breakdown in the project database, so the slider can go low without re-analysis.
- Tiers: S 85+, A 70-84, B 55-69, C below 55.

### Layer 7 - Boundaries and edit planning
- Snap start/end to sentence boundaries using word timestamps (+0.3 s padding); never mid-word. Target 20-60 s; up to 90 s only for a story that needs it; reject under 12 s. Start on the hook, not the setup. Ending review: does it end on a beat? A clip must make sense alone, otherwise widen it or mark it multi-part.
- Layout: gameplay centered over a blurred copy of itself, facecam on top if found; or plain crop. Optional auto punch-in zooms on the loudest/most emotional word (subtle, never jittery). Optional "callout arrow" pointing at the highest-motion region (OpenCV motion centroid); default OFF.

### Layer 8 - Metadata ensemble
- 3-5 title candidates from Gemma 4 E4B and Qwen3.5 9B, plus optional `csankalp21/headlinegpt` (Qwen2.5-1.5B LoRA tuned for engaging titles; needs its base model; quality unverified). Use real viral hook examples as few-shot (dataset `benxh/tiktok-hooks-finetune` was referenced by the `ryu34/viralcut-agent` model card; verify it exists and check its license before using it). A judge pass picks the title (under 70 characters, curiosity or emotion, no false claims, true to the clip).
- Description: summary, hashtags/SEO keywords, and a **credits block** naming the original creator with the source link. Add `docs/SOURCE_POLICY.md` explaining that credit alone does not make reuse fair use, and a per-clip field `source_risk_notes` so the user can record the creator's clip policy.
- Thumbnail prompt from the clip's TOPIC (never a screenshot).

### Layer 9 - Thumbnails
SDXL (Turbo/Lightning variant, fits 8 GB) draws background art from the topic prompt; unload; then Pillow draws the headline (diffusion models misspell text). Fallback: gradient + Pillow text. Optional slow quality mode: FLUX.1 schnell GGUF Q4 (roughly 60-90 s per image on 8 GB). Sizes: 1280x720 and 1080x1920 cover.

### Things NOT to do
- No big LLM "voting" beyond the rerank in Layer 4. No QVHighlights-trained research models (Moment-DETR, QD-DETR, VideoLights/Lighthouse) as the main detector (vlog/news domain mismatch); optional experimental layer, default OFF. No cloud fallback of any kind.

## 6. THE QUALITY THRESHOLD SLIDER (UI requirement)
A horizontal slider labelled "Minimum clip quality" (0-100, step 1) on the results page, default 65.
- **Instant, no recompute**: the pipeline stored all candidates above the floor, so moving the slider only re-filters stored data in the browser. Test that dragging the slider triggers ZERO model calls.
- Live readout: "N clips will be rendered", estimated render time, and a small histogram of all candidate scores with the threshold line and tier colors (S/A/B/C). Preset buttons: Strict 80, Balanced 65, Loose 50. A "Suggest" button picks the knee/elbow of the score distribution (e.g. Otsu or largest gap).
- Toggle "Relative mode": keep the top X percent of this video instead of an absolute score.
- Candidates just below the line appear in a dimmed "Borderline" list, each with a checkbox to pin it in; any selected clip has an exclude checkbox. Show per-clip score breakdown (which layers pushed it up) on hover or in a drawer.
- Only the selected clips are rendered ("Render selected"). Persist slider value per project and as the global default. Backend: `GET /projects/{id}/candidates`, `POST /projects/{id}/render {threshold, mode, pins, excludes}`.
- Also keep a config default `CLIP_MIN_SCORE` for headless runs.

## 7. Local model manager (no cloud router)
`llm/` package: `LLMProvider` interface (`generate_json(task, prompt, schema, max_tokens)`), `OllamaProvider` (`http://localhost:11434`), `LocalModelManager` with chains in `config/models.yaml`. Tasks: `clip_proposal`, `critic`, `arc_stitching`, `rerank`, `metadata`, `title_judge`, `thumbnail_prompt`, `vision_check`.
- Default chains: proposal `qwen3.5:9b` -> `gemma4:e4b` -> `qwen3.5:4b` -> `gemma4:e2b`; critic `gemma4:e4b` -> `qwen3.5:9b` -> `qwen3.5:4b`; rerank judges `qwen3.5:9b`, `gemma4:e4b`, optional `ministral-3:8b`; metadata `gemma4:e4b` -> `qwen3.5:9b` -> `gemma4:e2b`. (Verify tags with `ollama list`; other 4B options if needed: `nemotron-3-nano:4b`, `phi4-mini`.)
- Failure handling: CUDA OOM or load failure -> unload everything, retry once with smaller `num_ctx` (8192 -> 4096), then next model, then partial CPU offload as last resort. Timeout/connection -> 2 retries with backoff and jitter, then next model; if Ollama is down, try to start it, else show the exact fix. Bad JSON -> one repair retry, then next model. Model not pulled -> show the exact `ollama pull` command; other layers continue.
- Never loop forever. If a task's whole chain fails: `AllLocalModelsFailed` with reasons; optional layers are skipped; for a bad window mark "needs review" (no cloud).
- Log per call: task, model, latency, tokens/s, peak VRAM; store the model names in each clip's metadata.
- Ollama settings: `keep_alive: 0` between GPU-hungry stages, JSON-schema `format`, thinking off for bulk and on for critic.

## 8. Personal "fine-tuning" loop (the realistic fine-tuned model)
No off-the-shelf fine-tuned model exists for "viral gaming clip from a stream" (research found only adjacent ones: `ryu34/viralcut-agent` Qwen2.5-3B QLoRA for editing tool-calls and TikTok hooks, a Qwen3-8B QLoRA that predicts news-headline virality (domain mismatch), a HistGradientBoosting video-virality predictor trained on about 10,000 records (provenance unverified), and `csankalp21/headlinegpt` for titles). So build the user's own:
1. Thumbs up/down on every finished clip (and an optional import of real 48 h view/retention numbers from a YouTube Studio CSV) saved to `feedback/ratings.jsonl` together with ALL layer scores.
2. `scripts/train_ranker.py`: scikit-learn HistGradientBoosting (or LightGBM) on those features, CPU-only, runs in seconds. After at least 150 labeled clips, feed its output into the fusion as `personal_ranker` (weight starts at 0.10 and is tunable) and show feature importances so the scoring stays auditable.
3. Phase 2 (document only, do not build now): QLoRA fine-tune of a 3-4B model (e.g. Qwen3.5-4B) on the user's best hooks/titles with Unsloth.

## 9. Model bake-off harness (so models are chosen by evidence)
`scripts/bakeoff.py`: runs candidate LLMs (qwen3.5:9b, gemma4:e4b, ministral-3:8b, optional gemma4 12B) on 3-5 saved transcript windows that the user has rated, and reports JSON validity rate, agreement with the user's ratings (Spearman), tokens/s and peak VRAM. Before downloading anything new, do a quick web check of Ollama/Hugging Face for newer small models (Nov 2026) and add any that fit under 6.5 GB to the bake-off; adopt only if they win.

## 10. Rendering and captions
- Word-synced burned-in captions through ASS subtitles with **7 style presets** (modern box, classic yellow outline, minimal shadow, cyan, yellow box, neon green, red/gaming). Font size and padding scale with output width. Fonts: bundle open-licensed fonts (e.g. Montserrat, Anton, Bangers; check OFL) with Windows fallback Segoe UI Bold then Arial Bold. Per-word highlight, 2-4 words per line, safe margins for Shorts/Reels UI.
- Absolute-timestamp alignment: write a test proving captions stay in sync after a cut (seek offset bug).
- Audio: `loudnorm` to about -14 LUFS; no copyrighted music added.
- Export: clean filenames, folder per video, per clip: mp4, metadata JSON (all scores and model names), title/description text, thumbnails.
- Non-destructive edit data: keep trim/caption edits as stored operations so the user can fix a caption typo and re-render without reprocessing.

## 11. GPU scheduler (critical on 8 GB)
Strict order, VRAM released between stages, every stage cached on disk (crash = resume):
1. yt-dlp: video, info JSON (heatmap, chapters), comments, chat replay -> ffmpeg 16 kHz mono audio
2. L0 transcription (GPU) -> unload
3. L1 sensors (SenseVoice and AST on GPU or CPU; the rest CPU)
4. L2 proposer A -> unload -> proposer B -> unload
5. L3 critic and arc stitcher; L4 rerank (models loaded one at a time)
6. L5 visual (SigLIP 2, RapidOCR, optional SmolVLM2) -> unload
7. L6 fusion (CPU) -> results page shows the slider
8. On "Render selected": L8 metadata, L9 thumbnails (SDXL -> unload -> Pillow), L7 render with NVENC
Log VRAM and time per stage; peak VRAM must stay under 7.5 GB. Add presets in the UI: **Fast** (L0, L1, L2 one proposer, L6), **Balanced** (adds second proposer, critic, rerank), **Best** (everything). Per-layer on/off toggles.
Windows: faster-whisper on GPU needs CUDA 12 runtime libs (cuBLAS, cuDNN 9); follow its README (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12` via pip) and verify on a 10-second file.

## 12. Game profiles
`profiles/gaming_gta6.yaml` (user-editable, copyable for other games): glossary (names/places/slang), hype words, AST class list and weights, SigLIP positive/negative labels, OCR trigger words, scoring weight overrides. Ship a generic `profiles/default.yaml` too.

## 13. Setup, health check, docs
1. `scripts/check_local_setup.py`: PASS/FAIL for Python, GPU and free VRAM, free space on D:, env vars point to `D:\Open_Source_Weights`, ffmpeg and NVENC, Ollama running, every model present and loadable, yt-dlp works (heatmap field present for a test video), offline mode works. Print the exact fix for each FAIL.
2. `scripts/setup_windows.md` (or `.ps1`) with verified commands. `.env.example`: `WEIGHTS_DIR`, `OLLAMA_HOST`, model names, `CLIP_MIN_SCORE`, per-layer flags. No API keys anywhere.
3. Update `SKILL.md` and `AGENTS.md` (guidelines, layer flowchart, required downloads, steps), add a README section "Offline / unlimited mode", and keep `docs/MODELS.md` (model, job, size, license, URL) and `docs/REFERENCES.md`.

## 14. Tests and acceptance (run them at each phase gate in section 0A, not only at the end)
- Local model manager unit tests with a mock provider: OOM, timeout, connection refused, bad JSON, model-not-found; assert fallback order and context reduction.
- Each layer runs alone on a 2-minute sample; deleting one layer's model must NOT crash the pipeline.
- Network guard: full pipeline with the network disabled (after weights are downloaded) must finish with no LLM-related outbound request.
- Slider test: changing the threshold changes the clip count and triggers zero model calls.
- Rerank test: same finalists in different input orders produce nearly the same ranking (position-bias check).
- End-to-end on a real 5-10 minute video, then a 60-minute one: captioned 9:16 clips, titles, descriptions with credits, hashtags, topic-based thumbnails.
- **Ablation report on the same video**: (a) Qwen only, (b) two proposers, (c) full funnel. List the clips each variant picks plus timings so the user can judge. Do not claim improvement without showing this.
- Final report: files changed, models and versions with sizes, peak VRAM, per-layer timings, anything replaced because a name or tag did not exist.

## 15. Constraints
Everything free and offline. No secrets in git. Keep existing features and the app's other input/output formats. Remove nothing the user relies on without noting it in `docs/CHANGES.md`.
