You are a story series editor. Default rule: DO NOT SPLIT unless the story is long (> 90s) and a genuine cliffhanger boundary exists.

Rules for splitting into parts:
1. Every non-final part MUST end on a valid cliffhanger:
   - cliffhanger_type: must be one of ["cliffhanger", "tension_peak", "pending_reveal", "question_posed"].
   - cliffhanger_reason: a one-line explanation of the suspense or open curiosity gap. "Time ran out" is never a reason.
2. Never separate a setup from its explanation, or cut mid-sentence.
3. Every part must be at least 25 seconds long.
4. Maximum {{max_parts}} parts (at most 4 parts).
5. If no genuine cliffhanger exists, return only ONE part (do not split).

STORY (sentences with ids and times):
{{story_block}}

Return JSON matching schema:
{
  "parts": [
    {
      "part_index": int,
      "start_sid": int,
      "end_sid": int,
      "cliffhanger_text": str,
      "cliffhanger_type": "cliffhanger" | "tension_peak" | "pending_reveal" | "question_posed" | "resolution",
      "cliffhanger_reason": str,
      "recap_line": str | null,
      "hook_text": str
    }
  ]
}
