# 05. Stage 3: Build each clip (cut, layout, captions, audio, render)

Contents: 1 Segments download · 2 Cutter (dead air, fillers) · 3 Time remapping · 4 Face tracking and layout detection · 5 Layouts (pixel specs) · 6 Smoothing · 7 Captions · 8 Audio clean-up · 9 Final render · 10 Crispness rules · 11 Output verification

Canvas: **1080 x 1920**, fps = `min(source_fps, 60)` rounded to 24/25/30/50/60 (else 30). Safe zone (config `layout.yaml`): top 220 px, bottom 420 px, left/right 60 px, extra 100 px on the right side (platform buttons). Nothing important goes outside.

## 1. Segments download (`segments.py`)

Input: `plan.json` clips. For each clip request `[start - 6 s, end + 6 s]`. Merge ranges whose gap is < 20 s into segments. Write `segments.json`.

- If source duration <= `SMALL_VIDEO_MIN` (40 min): one segment = the full video.
- Else: for each segment, yt-dlp with `download_ranges=yt_dlp.utils.download_range_func(None, [(s, e)])` and `force_keyframes_at_cuts=True` (verify names in the installed version).
- Format selector for height H = `min(options.max_height, MAX_SOURCE_HEIGHT)` (default 1080; 1440 only if the user ticks "max quality"; 2160 never by default):
  `bv*[height<=H][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=H]+ba/b[height<=H]`, `merge_output_format: mkv`.
- Verify each segment with ffprobe: has video + audio, duration within 1.5 s of requested. Retry once; on failure mark that segment's clips `failed` with `DownloadFailed`.
- Publish progress per segment.

## 2. Cutter (`cutter.py`)

Goal: a tight, fluid clip. Input: segment file, clip `[start, end]`, the clip's words.

Step 1. **Initial range:** `[start, end]` from the plan.
Step 2. **Keep-interval list.** Start with one interval `[start, end]`, then remove:
 a. **Filler words** (`transcript.fillers`) inside the clip: remove `[w.s - 0.03, w.e + 0.03]`.
 b. **Dead air:** for every gap between consecutive words longer than `MIN_GAP_TO_CUT = 0.60 s`, measure RMS of the audio in the gap. If the gap's mean level is quieter than **-35 dBFS** (truly quiet), shorten it to `GAP_KEEP = 0.18 s` by removing the middle part (keep 0.09 s on each side). If the gap is louder (game audio, action, music, laughter) keep it untouched.
 c. Never remove the first 0.0 to the hook sentence end region's words; never remove inside a word.
 d. **Cap:** total removed <= 25% of the original duration; if exceeded, restore the largest-gap removals last-first until within the cap.
Step 3. Merge keep-intervals that are < 0.05 s apart. Minimum interval 0.25 s (drop shorter ones by merging into neighbours).
Step 4. Write `filter_complex` to a script file (`-filter_complex_script`) when intervals > 1:
```
[0:v]trim=start=S:end=E,setpts=PTS-STARTPTS[vN];
[0:a]atrim=start=S:end=E,asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.015,afade=t=out:st=(E-S-0.015):d=0.015[aN];
... [v0][a0][v1][a1]... concat=n=K:v=1:a=1[v][a]
```
(Times relative to the segment file: subtract `segment.s`.) For K > 150, process in batches of 100 into temp files, then concat the temp files the same way.
Step 5. Encode `cut.mkv`: `-c:v h264_nvenc -preset p5 -rc vbr -cq 15 -b:v 0 -pix_fmt yuv420p -c:a pcm_s16le -ar 48000` (PCM avoids AAC priming artefacts before later steps).
Step 6. Save `layout`-independent `cuts.json`: the keep-intervals (source time) for remapping.

If the 25% cap is hit or there are no removable gaps, the clip is still valid.

## 3. Time remapping (`utils/timecode.py`)

`remap(t_source)` returns clip-timeline seconds:
```
t_clip = sum(len(i) for each keep-interval entirely before t_source) + (t_source - interval.start) if t_source lies in interval
```
For a time inside a removed region return the clip time at that region's boundary. Create `words.json`: all words in the keep-intervals with `s_clip = remap(s)`, `e_clip = remap(e)`; drop filler words that were removed. Mark `emphasis` later (06). All captions and effects use `words.json` and clip-timeline seconds only.

## 4. Face tracking and layout detection (`face_track.py`, `layout.py`)

Detector: MediaPipe Tasks `FaceDetector` with `assets/models/blaze_face_short_range.tflite`, `min_detection_confidence=0.5`. If MediaPipe fails to load, fall back to OpenCV Haar (`haarcascade_frontalface_default.xml`) and log it.

Sampling for **layout detection**: one frame every 2 s of `cut.mkv`, minimum 12 samples, run the detector. Compute for faces with confidence >= 0.5: normalised box (x,y,w,h in 0..1), area ratio `r = w*h`, centre `(cx,cy)`.

Decision (use the most common face = largest median area across samples; ignore faces in < 40% of samples):
1. No stable face -> `gameplay`.
2. Median `r >= 0.06` and median centre within x in [0.2,0.8], y in [0.15,0.85] -> `talking_head`.
3. Median `r` in [0.004, 0.06) and centre in the outer 30% border (cx < 0.3 or cx > 0.7 or cy < 0.25 or cy > 0.75) and centre standard deviation < 0.03 -> `facecam`; the cam rectangle = face box expanded 1.7x (clamped to frame), aspect forced to the target region's aspect.
4. Otherwise -> `gameplay`.
User option `layout` overrides (`auto|gameplay|talking_head|facecam`). Save `layout.json {layout, cam_rect|null, samples, confidence}`.

## 5. Layouts (exact pixels, `config/layout.yaml`)

All layouts output 1080x1920 `framed.mp4` (video only, NVENC `-cq 16`, `-preset p5`), no captions or effects yet.

**A. `gameplay` (stack_blur)** — the default for GTA gameplay:
- Background: source frame scaled to **cover** 1080x1920 (`scale=-2:1920,crop=1080:1920`), then `boxblur=40:6` (or `gblur=sigma=28`), then `eq=brightness=-0.12:saturation=1.1`.
- Foreground: full source frame scaled to width 1080 (`scale=1080:-2`; for 16:9 this is 1080x608). Placed at x=0, **y=560** (bottom y=1168). Never crop the foreground; the HUD stays visible. If the source is narrower than 16:9 (e.g. 4:3), scale to height 608 max and centre.
- Caption anchor centre y = **1330**. Hook card region y 300-520. Part label y 240.
- Because the foreground is at or below 1:1 scale of a 1080p source, there is no upscale blur (crisp).

**B. `talking_head`:**
- Crop window: height = source height, width = `height * 9/16`; centre x follows the smoothed face centre x (section 6); clamp inside the frame; scale to 1080x1920 with `lanczos`.
- If the source is < 1080 px tall, the result is upscaled; log a quality warning and apply a light `unsharp=5:5:0.6`.
- Caption anchor centre y = **1250**.
- Implemented per-frame in Python (OpenCV read via ffmpeg pipe, crop with the per-frame x path) because the pan is dynamic. Static-crop fast path when the pan range < 40 px over the clip.

**C. `facecam` (gameplay + cam):**
- Gameplay panel: full frame scaled to width 1080, height 608, at x=0, **y=300** (300-908).
- Cam panel: `cam_rect` cropped from the source and scaled to **1080 x 560** at **y=930** (930-1490). Draw nothing between (black gap replaced by the blurred background as in A).
- Background as in A. Caption anchor centre y = **915** (at the seam, centred between panels), so captions never cover the face.
- If the cam crop is smaller than 540 px wide in the source, upscale with lanczos and note quality warning.

Compose A and C with ffmpeg `filter_complex` (static). B uses the Python compositor path.

## 6. Smoothing (face-follow pan)

- Face centre x per sampled frame (detect every 3rd frame at source fps; interpolate between).
- Exponential smoothing `x_s = x_s + 0.15*(x_target - x_s)` per frame at 30 fps (scale alpha by `fps/30`).
- Dead zone: do not move while `|x_target - x_s| < 0.04 * crop_width`.
- Velocity limit: 0.5 * crop_width per second.
- Face lost: hold the last position for 1.5 s, then ease to the previous median position over 1 s.
- Multiple faces: follow the one with the largest area; switch only if another stays largest for > 1.2 s (hysteresis).

## 7. Captions (`captions.py`)

Output `captions.ass` (burn-in) and `captions.srt` (export).

- **Chunks:** group `words.json` words into caption chunks of **2 to 4 words**, max 20 characters per line, 1 line (2 lines only if > 20 chars), break at punctuation or gaps > 0.35 s. Text upper-case.
- **ASS header:** `PlayResX: 1080`, `PlayResY: 1920`. Style `Cap`: font `Montserrat ExtraBold` (fallback `Arial Black`), size **84**, primary white `&H00FFFFFF`, outline black `&H00000000`, outline width **6**, shadow 0, bold on, alignment 5 (centre), spacing 1, margins L/R 60.
- **Position:** `\pos(540, <anchor_y>)` where anchor depends on layout (section 5).
- **Word highlight:** one `Dialogue` event per word: it displays the whole chunk with the active word coloured yellow `{\c&H00FFFF&}WORD{\r}` (ASS colours are BGR). Event start/end = that word's `s_clip` / next word start (last word: its end). Emphasis words (06) use orange `&H0088FF&` permanently within the chunk.
- **Pop-in:** first word event of each chunk gets `{\fscx85\fscy85\t(0,90,\fscx100\fscy100)}`.
- **Profanity mask:** apply `config/profanity.yaml` (list of words): replace middle letters with `*` in captions and SRT only (audio unchanged). Option `mask_profanity` default true.
- **Gaps:** never show a caption for a word with `e_clip - s_clip < 0.05` longer than 0.10 s.
- **Collisions:** a caption must never overlap a `hook_card` (top region) or part label; they live in different y bands by design.
- SRT: cue per chunk, no styling, UTF-8.
- Validation: parse the ASS back; assert every event time is within `[0, duration]` and monotonic.

## 8. Audio clean-up (`audio_clean.py`)

From `cut.mkv` audio produce `audio_clean.wav` (48 kHz stereo):
1. Optional denoise only for talking_head (`afftdn=nf=-25`), off for gameplay (it harms game audio).
2. Light compression: `acompressor=threshold=-18dB:ratio=3:attack=5:release=80`.
3. Loudness is applied in the final render (two-pass, section 9).
Never time-stretch audio.

## 9. Final render (`final_render.py`)

Inputs: `fx.mp4` if it exists else `framed.mp4`; `audio_clean.wav`; optional `sfx_mix.wav` (06); `captions.ass`.
Run ffmpeg with `cwd = clip work dir` and **relative** filenames, because absolute Windows paths with a drive colon break the `subtitles` filter. Copy fonts to `<clip dir>/fonts/` first and use `fontsdir=fonts`.

Pass 1 (measure loudness):
`ffmpeg -i audio_mix.wav -af loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json -f null -` -> parse `measured_I, measured_TP, measured_LRA, measured_thresh, offset`.

Pass 2 (render):
```
ffmpeg -y -i fx_or_framed.mp4 -i audio_mix.wav
 -vf "ass=captions.ass:fontsdir=fonts"
 -af "loudnorm=I=-14:TP=-1.5:LRA=11:measured_I=..:measured_TP=..:measured_LRA=..:measured_thresh=..:offset=..:linear=true"
 -c:v h264_nvenc -preset p5 -tune hq -rc vbr -cq 19 -b:v 0 -maxrate 16M -bufsize 32M
 -profile:v high -pix_fmt yuv420p -r <fps> -g <2*fps>
 -c:a aac -b:a 192k -ar 48000 -movflags +faststart -shortest clip.mp4
```
If `audio_mix.wav` has SFX, it is `audio_clean.wav` + `sfx_mix.wav` mixed with `amix=inputs=2:normalize=0` with SFX at -12 dB relative.
If NVENC fails, fall back to `libx264 -preset medium -crf 18` and warn.

## 10. Crispness rules

1. Prefer layouts that do not upscale (gameplay stack at 1080p source = 1:1).
2. For `talking_head` from 1080p, the 9:16 crop is 608x1080 stretched 1.78x. Mitigate: download 1440p when `options.max_height >= 1440`, apply `unsharp=5:5:0.6`, and keep bitrate high. Optional Real-ESRGAN (M5, approved clips only) via `requirements-optional.txt`.
3. Intermediate files use `-cq 15-16`; final `-cq 19`, max 16 Mbps.
4. Never scale with `bilinear`; use `lanczos` (`flags=lanczos`).
5. Even dimensions only. Never leave black bars (background fill covers them).

## 11. Output verification (`final_render.py` runs these checks, fails the clip on violation)

ffprobe: width 1080, height 1920, codec h264, audio aac 48 kHz; `abs(video_duration - audio_duration) <= 0.15`; duration between 12 and 95 s; measured integrated loudness within -14 ±1 LUFS (measure again with `ebur128` or the pass-2 report); no frame is entirely black for > 0.3 s (sample 1 fps); file size > 300 KB. A **pop check** for audio: at each cut time, compare the sample-to-sample absolute difference at the boundary; flag if > 0.3 of full scale.
