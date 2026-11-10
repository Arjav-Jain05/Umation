# 07. Stage 5: Metadata, credit block, thumbnails, package

Contents: 1 Metadata prompt and schema · 2 Title rules · 3 Description template · 4 Hashtags/tags/SEO · 5 Credit block · 6 Thumbnail concept · 7 Thumbnail generation (3 tiers) · 8 Thumbnail composition · 9 Package folder and checklist

## 1. Metadata (`metadata.py`, `prompts/metadata_text.md`)

One Gemini call per clip (temperature 0.7). Inputs: clip transcript text, `topic`, `entities`, `hook_text`, `content_flags`, part info, source title/channel, `domain_description`.

```
You write titles and descriptions for a vertical short (YouTube Shorts and Instagram Reels).
Domain: {{domain_description}}.
Clip topic: {{topic}}. Entities: {{entities}}. Part: {{part_info}}.
Transcript of the clip:
{{clip_text}}

Write ONLY what is true to the clip. No fake claims, no promises the clip does not keep, no ALL-CAPS shouting, no emoji spam.
1. titles: exactly 3 options (different angles): "curiosity" (open question or gap), "direct" (clear statement of the moment), "bold" (strong opinion or reaction). Each <= 70 characters, front-load the key words, include "GTA 6" if the clip is about it and it fits naturally. For Part clips end with " (Part k)" only if part_total > 1.
2. hook_line: first sentence of the description (<= 110 characters).
3. context: 1-2 plain sentences explaining what happens and why it matters. No claims you cannot support from the transcript.
4. hashtags: 4-5 hashtags, lower-case, no spaces, relevant (include #shorts and the main topic tag, e.g. #gta6).
5. keywords: 6-10 short search phrases people might type (for tags).
6. instagram_caption: 1-2 lines (<= 150 characters) plus the same hashtags.
7. pinned_comment: one short comment that invites replies (a genuine question about the clip).
Return JSON: {titles:[{style,text}], hook_line, context, hashtags:[str], keywords:[str], instagram_caption, pinned_comment}
```
`metadata.json` schema:
```json
{"schema_version":1,"clip_id":"c03","titles":[{"style":"curiosity","text":"..."},{"style":"direct","text":"..."},{"style":"bold","text":"..."}],
 "hook_line":"...","context":"...","hashtags":["#gta6","#shorts"],"keywords":["..."],
 "instagram_caption":"...","pinned_comment":"...","credit_block":"...","description_youtube":"...",
 "description_instagram":"...","tags_youtube":"a,b,c","risk":"medium","risk_flags":["low_commentary"],
 "thumbnail":{"concept":{...},"files":{"yt_16x9":"thumb_16x9.jpg","cover_9x16":"cover_9x16.jpg"},"generator":"gemini|sdxl|pillow"}}
```
Validation in code: titles <= 100 chars (hard) and <= 70 (target; truncate at word boundary with no ellipsis if longer); remove duplicate titles; hashtags max 5, each matches `#[a-z0-9_]+`; `keywords` unique; tags string <= 450 characters total. If the model fails validation twice, use the template fallback: titles = `[hook_text, topic.title(), f"{topic.title()} - what happened"]`, hashtags `#shorts #gta6` (only if domain gta6).

## 2. Title rules (enforced by prompt + validator)

- <= 100 chars absolute; aim <= 70.
- No "clickbait the clip does not deliver". The validator cannot check truth; the review screen shows the clip next to the titles so the user judges.
- No quote marks at the ends, no trailing punctuation spam, at most one `!` or `?`.
- No profanity in titles (mask using the profanity list).

## 3. Description template (YouTube), assembled by code

```
{hook_line}
{context}

{credit_block}

{hashtags joined by space}
```
Instagram description: `{instagram_caption}` then a blank line, then the credit block in short form (section 5), then hashtags if not already in the caption. Never exceed 2,200 characters (Instagram) or 5,000 (YouTube).

## 4. Hashtags, tags, SEO

- Hashtags: 4-5 only. YouTube may ignore excess hashtags, so more is not better.
- `tags_youtube`: keywords joined by commas, each <= 30 chars, total <= 450 chars; include the main entity names and "GTA 6" variants ("GTA 6", "GTA VI", "Grand Theft Auto 6").
- SEO reality: for Shorts the first line, the title and the on-screen words matter most; do not stuff keywords.

## 5. Credit block (`credit.py`) — mandatory (N6)

Fields come from `source_info.json` only (never from the model, so it can never be invented):

YouTube/long form:
```
Original video: "{title}" by {channel}
Channel: {channel_url}
Full video: https://youtu.be/{video_id}?t={start_seconds_int}
Clip from {hh:mm:ss} to {hh:mm:ss} of the original.
All footage and rights belong to the original creator and to the game's publisher/owners.
```
Short form (Instagram):
```
Credit: {channel} - "{title}"
Full video: https://youtu.be/{video_id}?t={start_seconds_int}
```
Rules:
- `start_seconds_int` is the clip's source start (floor).
- If the channel name is missing, use `uploader`; if both missing, use "the original creator" and set `risk_flags += ["missing_channel"]`.
- Never write "fair use", "no copyright infringement intended", or any legal claim. See 10 for why.
- For Part clips, the timestamp is that part's own source start.
- A unit test asserts every `metadata.json` has a credit block containing the video id and the channel.

## 6. Thumbnail concept (`thumbnail_concept.py`, `prompts/thumbnail_concept.md`)

The thumbnail is **generated artwork that references the clip's topic**, never a frame of the video (N9). It must not contain real people's likenesses, official logos, official key art or game screenshots.

```
You design a thumbnail for a short video. Output a concept for an ORIGINAL illustration (not a screenshot).
Topic: {{topic}}. Entities: {{entities}}. Hook: {{hook_text}}. Mood of the clip: {{mood}}.
Domain: {{domain_description}}.
Rules:
- Describe a bold, simple scene with ONE clear focal subject that symbolises the topic (objects, vehicles, landscapes, silhouettes, icons, abstract shapes). No real people, no faces of real or famous people, no logos, no copyrighted characters, no official artwork.
- For GTA 6 topics you may use the visual mood of a neon Florida-inspired coastal city (palm trees, sunset, sports cars, retro neon) as an ORIGINAL stylised scene, without any game logo or character.
- High contrast, saturated, readable at small size. Leave the top third or the left third calmer for text.
- text: a 1-3 word overlay (ALL CAPS) that does not repeat the whole title.
Return JSON: {scene, focal_subject, style, palette:[3 hex colors], text, text_position:"top|left|bottom", avoid:[str]}
```
Fallback if Gemini fails: `scene = "bold abstract neon gradient with a large symbolic icon for " + topic`, `text = first two words of hook_text`.

## 7. Thumbnail generation (`thumbnail_generate.py`), three tiers

Try in order; record `generator` used.
1. **Gemini image model** (`GEMINI_MODEL_IMAGE`) via `GeminiClient.generate_image(prompt, aspect)`. Prompt = `"{style}. {scene}. Focal subject: {focal_subject}. Palette: {palette}. No text, no letters, no logos, no people's faces. Clean composition with calm space for text on the {text_position}."` Generate once for 16:9 and once for 9:16, or generate 16:9 and extend/crop for 9:16 if the API cannot do 9:16. Rate limits per 02. Never include text in the generated image (text is added by code; image models misspell).
2. **Local SDXL** (only if `diffusers` and `torch` are installed and the user enabled `LOCAL_IMAGE_FALLBACK=true`): 8 GB VRAM works with `enable_model_cpu_offload()`, fp16, 1024x576 generation, then upscale/crop. Slow; used only when tier 1 fails.
3. **Pillow-only graphic** (always available): vertical/diagonal gradient from the palette, large geometric shapes (circles/sun, stripes, grid lines) and a symbolic shape; deterministic seeded by `clip_id`. It must look intentional, not broken.

Anti-frame guarantee (N9): after generation compute a perceptual hash (average hash 16x16 via Pillow+NumPy) of the thumbnail; compute the same for 12 sample frames of the clip; assert Hamming distance > 40 of 256 for all. If violated, regenerate once with an extra "abstract, not photographic" instruction, else fall back to tier 3.

## 8. Thumbnail composition (`thumbnail_compose.py`)

Outputs:
- `thumb_16x9.jpg` 1280x720 (YouTube), JPEG quality 90, < 2 MB.
- `cover_9x16.jpg` 1080x1920 (Reels/Shorts cover), keep key content inside the central 1080x1350 area.
Text overlay (Pillow): font `Anton`, auto-fit size (start 190 px for 16:9, 170 px for 9:16, shrink until width <= 88% of canvas), fill white (or `#FFD400` if background luminance is high), stroke 14 px black (stroke_fill black), drop shadow offset 6 px black 60%. Position per `text_position`: top = y 8% from top; left = x 6%, vertically centred; bottom = y 70%. Contrast check: sample mean luminance behind the text box; if contrast ratio < 4.5 against the fill, add a semi-transparent dark rounded box behind the text (`rgba(0,0,0,0.45)`). Text never exceeds 3 words.

## 9. Package folder (`package.py`) and checklist

For each clip, create `output/<slug>-<video_id>/<clip_id>_<tier>[_partKofN]/` containing:
```
clip.mp4            final render (05)
thumb_16x9.jpg      YouTube thumbnail
cover_9x16.jpg      vertical cover
metadata.txt        human copy-paste sheet (sections below)
metadata.json       machine-readable (section 1)
captions.srt        subtitles
edit_list.json      effects used (06)
credit.txt          the credit block alone
notes.txt           risk level, risk flags, score breakdown, warnings
```
`metadata.txt` layout (UTF-8, plain, easy to copy):
```
=== YOUTUBE TITLE OPTIONS ===
1. ...
2. ...
3. ...

=== YOUTUBE DESCRIPTION ===
...

=== YOUTUBE TAGS (comma separated) ===
...

=== INSTAGRAM CAPTION ===
...

=== PINNED COMMENT ===
...
```
Checklist run by `package.py` before marking `packaged` (any failure marks the clip `failed` with the reason): `clip.mp4` passes 05 section 11; both thumbnail files exist with correct sizes and the anti-frame check passed; `metadata.json` validates and contains the credit block; `description_youtube` contains `https://youtu.be/<video_id>`; titles count is 3; `captions.srt` non-empty. Update the clip DB row (`folder`, `status`) and publish a `clip_update` SSE event so the UI shows the clip as soon as it is ready (do not wait for the whole job).
Zip export (`GET /api/clips/.../zip`) uses `zipfile` streaming; the folder is also openable via the open-folder endpoint.
