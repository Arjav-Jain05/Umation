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

Return JSON only:
```json
{
  "hook_text": "HOOK TEXT HERE",
  "zoom_punches": [{"t": 3.1, "dur": 0.9, "scale": 1.12}],
  "pointers": [{"t": 8.2, "dur": 1.8, "target_description": "the red sports car in the center"}],
  "emojis": [{"t": 15.4, "emoji": "😱"}],
  "caption_emphasis": [12, 33],
  "sfx": [{"t": 0.0, "name": "whoosh"}]
}
```
