# 06. Stage 4: AI director and effects

Contents: 1 Concept · 2 Edit list schema · 3 Density rules · 4 Director prompt · 5 Validator · 6 Fallback director · 7 Target locator (arrows) · 8 Tracker · 9 Compositor · 10 Effect specs · 11 SFX · 12 Failure behaviour

## 1. Concept

Gemini never touches pixels. It writes an **edit list** (JSON). Deterministic code validates it, then the compositor draws the effects. If Gemini is unavailable or output is bad, a rule-based fallback director produces a safe edit list. Every overlay is stored so the review UI (M5) can show, move or delete it.

Pipeline: `words.json + layout + clip meta -> director (Gemini) -> validate -> locate targets (vision, arrows only) -> edit_list.json -> compositor -> fx.mp4 (+ sfx_mix.wav)`.

All times in the edit list are **clip-timeline seconds** after cuts. All coordinates are **output pixels** on the 1080x1920 canvas.

## 2. Edit list schema (`edit_schema.py`, `edit_list.json`)

```json
{
  "schema_version": 1, "clip_id": "c03", "fps": 30, "duration": 47.2,
  "layout": "gameplay",
  "caption_emphasis": ["word_index", 12, 33],
  "events": [
    {"id":"e01","type":"hook_card","t":0.0,"dur":2.4,"params":{"text":"THE PHYSICS ARE INSANE"}},
    {"id":"e02","type":"zoom_punch","t":3.1,"dur":0.9,"params":{"scale":1.12,"anchor":"center"}},
    {"id":"e03","type":"arrow","t":8.2,"dur":1.8,"params":{"bbox":[420,610,700,880],"label":null,"source":"vision","confidence":0.82}},
    {"id":"e04","type":"highlight_box","t":8.2,"dur":1.8,"params":{"bbox":[420,610,700,880]}},
    {"id":"e05","type":"emoji_pop","t":15.4,"dur":0.9,"params":{"emoji":"😱","x":820,"y":700}},
    {"id":"e06","type":"part_label","t":0.0,"dur":47.2,"params":{"text":"PART 1/3"}},
    {"id":"e07","type":"recap_line","t":0.0,"dur":2.0,"params":{"text":"Previously: the map leaked"}},
    {"id":"e08","type":"progress_bar","t":0.0,"dur":47.2,"params":{}},
    {"id":"e09","type":"sfx","t":0.0,"dur":0.4,"params":{"name":"whoosh","gain_db":-12}}
  ]
}
```
`caption_emphasis` = indices into `words.json` of words to colour orange (max 8 per clip). `bbox` = `[x1,y1,x2,y2]` px. Types allowed: `hook_card, zoom_punch, arrow, highlight_box, emoji_pop, part_label, recap_line, progress_bar, sfx`. Unknown types are dropped by the validator.

## 3. Density rules (`config/effects.yaml`, enforced by the validator)

```yaml
max_events_per_second: 0.4          # average over the clip, excluding progress_bar, part_label, sfx
max_simultaneous: 2                  # visual overlays at the same moment (excluding progress_bar, part_label)
hook_card: {t_max: 0.3, dur: [1.8, 2.8], max_words: 8, max_chars_per_line: 16, lines: 2}
zoom_punch: {min_gap_s: 4.0, scale: [1.06, 1.18], dur: [0.6, 1.2], max_per_clip: 6}
arrow: {dur: [1.2, 2.5], min_confidence: 0.6, max_per_clip: 4, min_gap_s: 3.0}
highlight_box: {only_with_arrow: true}
emoji_pop: {max_per_clip: 4, min_gap_s: 6.0, dur: [0.7, 1.1]}
part_label: {enabled_if_part: true}
recap_line: {only_for_part_index_gt: 1, dur: [1.6, 2.2], max_words: 8}
progress_bar: {enabled: true}
sfx: {max_per_clip: 8, min_gap_s: 0.5}
```
The validator clamps durations, shifts or drops events that violate gaps/limits, drops events outside `[0, duration - 0.2]`, drops arrows below confidence, and logs what it changed. Taste rule: **fewer, better effects**. If in doubt, drop.

## 4. Director prompt (`prompts/director_edit_list.md`)

```
You are the editor of a viral vertical short (1080x1920). Plan tasteful on-screen effects as JSON. Do not overdo it: a few precise effects beat many.

Clip topic: {{topic}}. Domain: {{domain_description}}.
Layout: {{layout}}. Duration: {{duration}} s. Part: {{part_info}}.
Hook phrase suggestion: {{hook_text}}.
Needs-context caption suggestion (may be empty): {{context_fix}}.

Words with clip times (index, start, text):
{{words_block}}

Available effects and rules:
- hook_card: a short text card at the very start (t = 0). 3-8 words, ALL CAPS ok, truthful to the clip. One per clip. If context_fix is non-empty use it as the hook text if it is stronger.
- zoom_punch: quick punch-in on a key line, emphasis word, laugh or reveal. At the START of a sentence or on an emphasised word. Max 6 per clip, at least 4 seconds apart. scale 1.06-1.18.
- pointer moments: when the speaker refers to something that appears on screen ("look at this", "this car", "the map here", "that detail"), output a pointer item with t (when it should appear), dur 1.2-2.5 s, and target_description = a precise visual description of the thing to point at (colour, kind, position hint), max 12 words. Do NOT invent things that are not mentioned. If unsure, omit.
- emoji_pop: a single fitting emoji at an emotional beat. Max 4.
- caption_emphasis: pick 3-8 words (word indices) worth colouring: the key nouns/numbers/shocking words.
- sfx: whoosh with hook_card, pop with emoji_pop and arrow, ding on a reveal. Optional.
Never put events in the last 0.3 s. Prefer events that sit on sentence starts.

Return JSON only: {hook_text, zoom_punches:[{t,dur,scale}], pointers:[{t,dur,target_description}], emojis:[{t,emoji}], caption_emphasis:[int], sfx:[{t,name}]}
```
Code converts this into the `events` list (assigning ids, anchors, bbox after the locator runs).

## 5. Validator (`edit_schema.py: validate_and_fix`)

1. Parse into Pydantic models; invalid items dropped with a log line.
2. Snap each event time to the nearest word start within 0.25 s (so effects sit on speech), else keep.
3. Apply density rules (section 3) in this priority when trimming: keep hook_card > arrow > zoom_punch > emoji_pop > sfx.
4. Ensure `hook_card.text` is <= 8 words and has no profanity (mask like captions).
5. Ensure all coordinates are integers within the canvas and inside the **safe zone** (top >= 220 except hook_card region 300-520 which is allowed, bottom <= 1500).
6. Return the fixed list plus a list of change messages.

## 6. Fallback director (rule-based, used when Gemini fails or `effects=false` is not set but the model output is invalid)

- `hook_card` with `judged.hook_text` (or the first 6 words of the clip uppercased).
- `zoom_punch` at the start of every 3rd sentence plus at each emphasis word in the top 3 by `speech energy` (RMS at that word), respecting gaps.
- `caption_emphasis`: numbers and capitalised proper nouns found in glossary terms, max 8.
- `progress_bar`, `part_label`, `recap_line` as applicable.
- No arrows, no emoji.
Log `director=fallback` into `edit_list.json` meta.

## 7. Target locator for arrows (`target_locator.py`, `prompts/locate_target.md`)

For each pointer item:
1. Grab the **framed** frame (1080x1920 output) at time `t + dur/2` (clip timeline) via ffmpeg `-ss`, save as JPEG max side 1280.
2. Send to Gemini as an image with:
```
Image is a vertical video frame. Find the object described: "{{target_description}}".
Return JSON {found: bool, box_2d: [ymin, xmin, ymax, xmax], label: string, confidence: 0-1} with coordinates normalised 0-1000.
If it is not clearly visible or ambiguous, return found=false. Do not guess.
```
(Verify the current coordinate convention in the installed SDK docs; this spec assumes `[ymin, xmin, ymax, xmax]` on a 0-1000 scale. If different, adapt in ONE function `parse_box` and log in DECISIONS.md.)
3. Convert: `x1 = xmin/1000*1080`, `y1 = ymin/1000*1920`, etc. Reject if area < 1.5% or > 60% of the frame, or the box lies fully outside the safe zone, or `confidence < 0.6`.
4. **Verification pass** (cheap): crop the box (+15% padding) from the frame and ask Gemini "Does this crop clearly show: <description>? yes/no + confidence". Require yes and >= 0.6. Skip this pass in fast mode.
5. Create `arrow` + `highlight_box` events with the bbox; `source="vision"`.
Rejected pointers are silently dropped (no arrow is better than a wrong arrow).

## 8. Tracker (`tracker.py`)

If the target may move (layout gameplay): initialise `cv2.TrackerCSRT_create()` on the frame at `t` with the bbox, track frames until `t+dur`. Per frame store the bbox. If the tracker fails or the box area changes by > 2.2x or centre jumps > 25% of frame width in one frame, stop tracking and freeze the last good box. Store tracked boxes under `params.track = [[t, x1,y1,x2,y2], ...]` (sampled at 10 Hz and interpolated). Static targets (user can mark `static=true`) skip tracking.

## 9. Compositor (`compositor.py`, `apply_effects.py`)

- Decode `framed.mp4` with an ffmpeg subprocess to raw BGR frames on stdout (`-f rawvideo -pix_fmt bgr24`), process each frame as a NumPy array with OpenCV/Pillow, and pipe to an ffmpeg encoder subprocess (`h264_nvenc -cq 16 -preset p5 -pix_fmt yuv420p`) writing `fx.mp4` (video only). Use a bounded queue/threads so decode, draw and encode overlap.
- Frame time `t = frame_index / fps`. For each frame, active events = those with `t0 <= t < t0+dur`. Apply in this order (bottom to top): zoom_punch (transforms the whole frame), highlight_box, arrow, emoji_pop, hook_card, recap_line, part_label, progress_bar.
- Captions are NOT drawn here; they are burned in the final render so they do not zoom.
- Pre-render sprites once (hook card background, arrow image rotated per angle) and cache.
- Performance target: >= 20 frames/s; a 45 s clip in under 3 minutes. If slower, reduce Python overhead (avoid per-frame allocations, use `cv2.addWeighted` on ROIs only).
- If there are **no visual events** except progress bar/part label, skip the compositor: use `framed.mp4` directly.

## 10. Effect specs (`app/pipeline/s4_director/effects/*.py`, each implements `render(frame, t_local, params, ctx)`)

Easing functions in `utils/easing.py`: `ease_out_cubic(x) = 1-(1-x)^3`, `ease_in_out(x) = 3x^2-2x^3`, `ease_out_back(x)` with overshoot 1.4.

**zoom_punch:** `u = t_local/dur`. Scale `s = 1 + (S-1) * ease_out_cubic(min(1, t_local/0.12))` during the first 0.12 s, hold, then ease back to 1 during the last 0.25 s. Anchor: `center` = frame centre of the **foreground region** (for gameplay layout y centre 864; otherwise canvas centre); `face` = tracked face centre if available. Implementation: crop `w/s x h/s` around the anchor (clamped), resize back with `INTER_CUBIC`. Background blur layers zoom along (simple whole-frame zoom is fine).

**hook_card:** rounded rectangle (radius 28), fill `rgba(0,0,0,0.62)`, thin white 3 px border at 25% alpha, centred horizontally at y=300..520 (height auto by lines). Text: font `Anton` (fallback Montserrat ExtraBold), size 96, white, uppercase, line spacing 1.05, stroke 4 px black. Max width 960 px; wrap by words; if the text needs a third line, reduce size by 8 until it fits (min 64). Animation: scale 0.85 -> 1.0 with `ease_out_back` over 0.18 s; fade out over the last 0.2 s.

**arrow:** sprite `assets/overlays/arrow.png` (bright yellow `#FFD400` with 6 px black outline, pointing right, 220 px long; generated by `scripts/make_overlays.py` with Pillow, no download). Place at the bbox edge with the most free space inside the safe zone (test left, right, top, bottom in that order of tie preference: left, top, right, bottom). Rotate so the tip touches the bbox edge midpoint with a 14 px gap. Animation: pop scale 0.7 -> 1.1 -> 1.0 over 0.25 s, then bob +-8 px along its axis at 2 Hz; fade out last 0.2 s. If bbox moves (track), the arrow follows with smoothing alpha 0.35.

**highlight_box:** rounded rectangle outline `#FFD400`, width 6 px, corner radius 18, expanded 10 px beyond the bbox; draw-in by growing from 85% to 100% scale over 0.2 s; alpha pulses 0.75-1.0 at 3 Hz.

**emoji_pop:** Pillow with `NotoColorEmoji.ttf` at size 109 (bitmap font; `embedded_color=True`), rendered to RGBA then scaled to 200 px. Position `(x,y)` default: right side `x=820`, `y` at 28% from the top of the foreground; must stay inside safe zone. Animation: scale 0 -> 1.15 -> 1.0 `ease_out_back` over 0.25 s, float up 40 px over the duration, fade out last 0.2 s. If the emoji font cannot render, skip emoji events (log).

**part_label:** chip at top-left `x=60, y=240`, height 64, padding 24, background `rgba(255,212,0,1)`, text black Montserrat ExtraBold 40, "PART k/n". Visible the whole clip.

**recap_line:** text under the hook area at y=540-620, size 52, white with 4 px black stroke, fade in 0.2 s, fade out 0.2 s. Only parts 2+.

**progress_bar:** full-width bar at y=204 (just above the top safe edge), height 8, track `rgba(255,255,255,0.25)`, fill `#FFD400`, width = `t/duration * 1080`.

## 11. SFX (`effects/sfx.py`, `scripts/make_sfx.py`)

Synthesise WAV files (48 kHz mono, NumPy, no downloads): `whoosh` = band-limited noise with a rising then falling filter envelope, 0.35 s; `pop` = 80 ms sine sweep 700 -> 300 Hz with fast decay; `ding` = 880 Hz + 1760 Hz partial with exponential decay, 0.45 s. Save to `assets/sfx/`. `sfx_mix.wav` = silence of clip length with each sfx placed at its time, gain from params (default -12 dB), summed and limited to -1 dBFS. Duck nothing; the loudness pass handles final level.

## 12. Failure behaviour

| Failure | Behaviour |
|---|---|
| Gemini director fails 3 times | fallback director (section 6) |
| Locator returns not found / low confidence | drop that pointer |
| Compositor crashes | retry once; then use `framed.mp4` and mark clip `fx_failed` warning; clip still packages |
| Emoji/font missing | skip that effect |
| Effect timing outside clip | validator drops it |
| Cancel | compositor checks the flag every 30 frames |

The user may toggle `effects=false` per job; then stage `direct` writes an `edit_list.json` with only progress bar + part label and skips the compositor.
