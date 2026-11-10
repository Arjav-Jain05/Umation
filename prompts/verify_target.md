Does this cropped image clearly show the described target: "{{target_description}}"?
Return JSON only:
```json
{
  "shows_target": true,
  "confidence": 0.85,
  "reason": "short explanation"
}
```
If the described object is not clearly recognizable in the crop, return shows_target=false and confidence=0.0.
