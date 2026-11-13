You design a thumbnail for a short video. Output a concept for an ORIGINAL illustration (not a screenshot).
Topic: {{topic}}. Entities: {{entities}}. Hook: {{hook_text}}. Mood of the clip: {{mood}}.
Domain: {{domain_description}}.
Rules:
- Describe a bold, simple scene with ONE clear focal subject that symbolises the topic (objects, vehicles, landscapes, silhouettes, icons, abstract shapes). No real people, no faces of real or famous people, no logos, no copyrighted characters, no official artwork.
- You may use the thematic mood and aesthetic of the topic as an ORIGINAL stylized scene, without any official logos, copyrighted characters, or real faces.
- High contrast, saturated, readable at small size. Leave the top third or the left third calmer for text.
- text: a 1-3 word overlay (ALL CAPS) that does not repeat the whole title.

Return JSON only:
```json
{
  "scene": "A retro neon-lit coastal highway at sunset with vibrant pink and violet sky",
  "focal_subject": "A sleek 80s sports car silhouette driving towards the sunset",
  "style": "Synthwave vector illustration with bold contrast and neon glow",
  "palette": ["#FF007F", "#7928CA", "#00F0FF"],
  "text": "SECRET LEAK",
  "text_position": "top",
  "avoid": ["people faces", "game logos", "text in image"]
}
```
