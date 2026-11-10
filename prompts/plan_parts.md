You split one strong story into Parts for a short-form series.
Each part must be 30-60 seconds, start on a sentence boundary, and have its OWN hook so a viewer who only sees that part is still pulled in.
Part 1 ends on a cliffhanger or open question (the last sentence should create curiosity). The final part ends on the payoff.
Parts must be contiguous, in order, and together cover only sentences from the story (you may drop weak sentences between parts).
For parts 2+, write recap_line: max 8 words, plain, to show on screen at the start ("Previously: ...").
Use only the provided sentence ids. Between 2 and {{max_parts}} parts. If the story cannot be split cleanly, return one part.

STORY (sentences with ids and times):
{{story_block}}

Return JSON: {parts:[{part_index, start_sid, end_sid, cliffhanger_text, recap_line|null, hook_text}]}
