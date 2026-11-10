Image is a vertical video frame. Find the object described: "{{target_description}}".
Return JSON only:
```json
{
  "found": true,
  "box_2d": [ymin, xmin, ymax, xmax],
  "label": "string description",
  "confidence": 0.85
}
```
Coordinates in box_2d must be normalised integers on a 0-1000 scale: [ymin, xmin, ymax, xmax].
If it is not clearly visible or ambiguous, return found=false and confidence=0.0. Do not guess.
