You write titles and descriptions for a vertical short (YouTube Shorts and Instagram Reels).
Domain: {{domain_description}}.
Clip topic: {{topic}}. Entities: {{entities}}. Part: {{part_info}}.
Transcript of the clip:
{{clip_text}}

Write ONLY what is true to the clip. No fake claims, no promises the clip does not keep, no ALL-CAPS shouting, no emoji spam.
1. titles: exactly 3 options (different angles): "curiosity" (open question or gap), "direct" (clear statement of the moment), "bold" (strong opinion or reaction). Each <= 70 characters, front-load the key words, include the main topic or entity if it fits naturally. For Part clips end with " (Part k)" only if part_total > 1.
2. hook_line: first sentence of the description (<= 110 characters).
3. context: 1-2 plain sentences explaining what happens and why it matters. No claims you cannot support from the transcript.
4. hashtags: 4-5 hashtags, lower-case, no spaces, relevant (include #shorts and the main topic tag, e.g. #shorts, #viral, #highlight).
5. keywords: 6-10 short search phrases people might type (for tags).
6. instagram_caption: 1-2 lines (<= 150 characters) plus the same hashtags.
7. pinned_comment: one short comment that invites replies (a genuine question about the clip).

Return JSON only:
```json
{
  "titles": [
    {"style": "curiosity", "text": "Did Anyone Else Notice This Hidden Detail?"},
    {"style": "direct", "text": "The Moment Everything Changed"},
    {"style": "bold", "text": "This Explains Why It Happened"}
  ],
  "hook_line": "Did you catch this unbelievable moment in the footage?",
  "context": "A close look at the sequence reveals an unexpected detail not seen before. Here is why viewers are reacting.",
  "hashtags": ["#shorts", "#viral", "#highlight", "#trending"],
  "keywords": ["viral moment", "hidden detail", "unbelievable clip", "reaction", "breakdown"],
  "instagram_caption": "Did you catch this detail? Drop your thoughts below! #shorts #viral",
  "pinned_comment": "What was your favorite part of this moment?"
}
```
