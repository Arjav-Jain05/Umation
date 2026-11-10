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

Return JSON only:
```json
{
  "titles": [
    {"style": "curiosity", "text": "Can You Actually Enter This Building in GTA 6?"},
    {"style": "direct", "text": "GTA 6 Leaked Map Detail Revealed"},
    {"style": "bold", "text": "This GTA 6 Feature Changes Everything"}
  ],
  "hook_line": "Did you notice this incredible detail hidden in the new GTA 6 map?",
  "context": "A close inspection of the coordinates reveals an accessible interior not seen before. Here is why fans are excited.",
  "hashtags": ["#shorts", "#gta6", "#gaming", "#gtavicecity"],
  "keywords": ["GTA 6 leak", "GTA VI map", "Grand Theft Auto 6", "Vice City secrets"],
  "instagram_caption": "Did you catch this hidden detail in GTA 6? Drop your theories below! #shorts #gta6",
  "pinned_comment": "Do you think this building will be accessible on launch day?"
}
```
