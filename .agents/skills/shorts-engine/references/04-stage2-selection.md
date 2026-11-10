# 04. Stage 2: Finding every viral-worthy moment

Contents: 1 Design · 2 Chunker · 3 Nominate (prompt A) · 4 Refine · 5 Judge (prompt B) · 6 Signals · 7 Blend · 8 Planner (variable count) · 9 Part splitter (prompt C) · 10 Risk · 11 Fast lane · 12 `scoring.yaml` · 13 GTA 6 domain config · 14 Honesty rules

## 1. Design

Nothing here predicts views. The system estimates which moments have the traits that correlate with retention, and combines three independent signals. Weak spots (noisy LLM scores) are handled by rubrics, two-run averaging, caching and later calibration with the user's real results (09).

Flow: `chunker -> nominate (LLM) -> merge+refine (code) -> judge (LLM, 2 runs) -> signals (code) -> blend -> planner -> part_splitter (LLM, only for stories) -> risk`.

Do NOT score every possible window (an 8 h stream would create tens of thousands). The LLM nominates regions; code refines them.

## 2. Chunker (`chunker.py`)

- Input: `transcript.sentences`.
- Chunks of **20 minutes** with **90 s overlap**, cut on sentence boundaries. `chunks.json` as in 02.
- Render each chunk to prompt text, one line per sentence: `[<sid>] <mm:ss> <text>` where `mm:ss` is relative to the **video** start (`h:mm:ss` if > 1 h). Replace dead regions with a single `[... quiet N s ...]` line.
- Max prompt text per chunk about 12k tokens; if larger, shorten the chunk to 15 min.

## 3. Nominate (prompt A, `prompts/nominate_candidates.md`)

System + user template. Placeholders `{{...}}` are filled by code. Output validated against schema `NominationOut`.

```
You are a short-form video editor who finds the most viral-worthy moments in a transcript.
Domain: {{domain_description}}.
Known terms: {{glossary_terms}}.

You get a transcript chunk. Each line is "[sentence_id] time text".
Replay peaks from YouTube (times where viewers replayed most, may be empty): {{heat_peaks}}.

TASK: nominate EVERY moment that could work as a standalone short, 20 to 75 seconds long.
There is NO fixed number. Return 0 candidates if nothing is good. Do not pad.

A great moment has:
1. A hook in its first 3 seconds: a surprising claim, a question, a reaction, a reveal, a conflict, or a promise ("watch what happens").
2. A complete mini-story: setup, tension, payoff. It ends on the payoff, a punchline or a cliffhanger, never mid-thought.
3. It makes sense to someone who has not seen the rest of the video.
4. Emotional energy: laughter, shock, hype, anger, awe.
5. Novelty: first reactions, discoveries, glitches, hidden details, news, leaks, comparisons, strong opinions people will argue about.

REJECT: intros, outros, sponsor reads, "like and subscribe", chat housekeeping, long silence, rambling, moments that need earlier context to be understood, repeated points.

RULES:
- Use ONLY sentence ids that exist in the chunk. Do not invent text or ids.
- start_sid is the first sentence of the moment. end_sid is the last. hook_sid is the sentence containing the hook (usually start_sid). If the real hook is a later sentence, set start_sid to the hook sentence so the clip opens on it.
- Moments may be up to 150 seconds long ONLY if they are one continuous story (set is_story true).
- Moments must not overlap each other by more than 25%.
- reason: one sentence stating why a viewer would keep watching.
- hint_score: your 0-100 confidence that this keeps viewers watching.

Return JSON only matching the schema.

CHUNK:
{{chunk_text}}
```
`NominationOut = {candidates: [{start_sid:int, end_sid:int, hook_sid:int, reason:str, hint_score:int, is_story:bool}]}`.

Code validation per candidate: ids exist inside the chunk; `start_sid <= hook_sid <= end_sid`; duration 15-150 s; else drop and count in a log line.

**Merge across chunks:** two candidates are duplicates if their time overlap > 50% of the shorter one. Keep the one with the higher `hint_score`. Assign `cid = n01, n02...` in time order. Write `candidates.json`.

## 4. Refine (`refine.py`), deterministic boundary clean-up

For each candidate, in this order:
1. Convert sentence ids to times: `s = sentences[start_sid].s`, `e = sentences[end_sid].e`.
2. **Hook trim:** while the first sentence has < 4 words, or starts (case-insensitive) with one of `so, um, uh, yeah, okay, ok, alright, well, and, but, anyway, right` AND the next sentence exists AND start moves less than 8 s total: drop the first sentence. Never drop the `hook_sid`.
3. **Tail trim:** drop trailing sentences that start with `thanks, thank you, anyway, so yeah, alright, subscribe, see you`.
4. **Padding:** `s -= 0.15 s` (not before previous sentence end), `e += 0.35 s` (not after next sentence start).
5. **Length fit:** target <= `max_clip_s` (option, default 60). If the duration is longer and `is_story` is false: remove sentences from the START (never `hook_sid`, never the last sentence, which is the payoff) one at a time until the duration <= `max_clip_s`. If the duration is still too long because `hook_sid` is the first sentence, set `is_story = true`; it then goes to the part splitter if its final score is >= 70, otherwise the planner drops it with reason `too_long`.
6. Minimum duration 15 s: if shorter, extend forward sentence by sentence up to 25 s if the added sentences have wpm > 80; else discard.
Output is the input to the judge.

## 5. Judge (prompt B, `prompts/judge_candidate.md`)

Batch **4 candidates per call**. Run **twice** (temperature 0.2, different cache keys by run number) and average scores. If the two runs disagree on `needs_context` use true.

```
You are a strict viral short-form editor. Score each candidate clip using the rubric. Be harsh: most clips are average (4-6). Reserve 8-10 for truly exceptional.

Domain: {{domain_description}}. Known terms: {{glossary_terms}}.

RUBRIC (0-10 each, decimals allowed):
- hook: how strongly the FIRST 3 SECONDS make a stranger stop scrolling. 0 = bland greeting or context-dependent. 5 = interesting statement. 9-10 = shocking, funny, or irresistible curiosity gap.
- payoff: does it deliver a satisfying punchline, reveal, conclusion or strong cliffhanger by the end?
- clarity: is it fully understandable alone, with no prior context, clear speech, clear subject? (10 = perfectly standalone)
- emotion: intensity of laughter, shock, hype, anger, awe, tension.
- novelty: new information, first reactions, discoveries, leaks, glitches, hot takes.
- shareability: would people comment, argue, quote or send it to a friend?
- pace: density of interesting content; 10 = no dead air or filler.

Also decide:
- needs_context: true if a viewer would be confused without earlier parts of the video.
- context_fix: if needs_context is true and a 1-line on-screen caption (max 10 words) would fix it, write it; else null.
- is_story: true if this is one continuous story/argument that needs more than 75 seconds.
- topic: 3-6 words naming the subject.
- entities: up to 6 named things (people, places, games, features).
- content_flags: any of ["profanity","violence","spoiler","sensitive_topic","none"].
- hook_text: a 3-8 word on-screen hook phrase for the opening (punchy, truthful, in the speaker's spirit, no clickbait that the clip does not deliver).
- one_line_reason per score group (hook, payoff, overall).

Use only information in the candidate text. Do not invent facts.

CANDIDATES (JSON list: cid, start_time, end_time, text lines with ids):
{{candidates_block}}

Return JSON only matching the schema: {results:[{cid, scores:{hook,payoff,clarity,emotion,novelty,shareability,pace}, needs_context, context_fix, is_story, topic, entities, content_flags, hook_text, reasons:{hook,payoff,overall}}]}
```
Candidate text lines: `[sid] mm:ss text` for sentences from `start_sid..end_sid`, plus 2 sentences before and after marked `(context before)`/`(context after)` so the judge can assess standalone clarity.

`llm_score = 10 * (0.25*hook + 0.20*payoff + 0.15*clarity + 0.15*emotion + 0.10*novelty + 0.10*shareability + 0.05*pace)` using weights from `scoring.yaml`. Store `runs` and per-run scores.

## 6. Signals

### 6.1 Heatmap (`signal_heatmap.py`)
- If `heatmap` is null: `heat = null`.
- `avg_seg = heatmap_avg_seg_s`. If `avg_seg > 90` the data is too coarse: set `heat_weight_override = 0.05`, else normal weight.
- For candidate `[s, e]`: time-weighted mean of `value` over overlapping heatmap segments = `m`. Over the whole video: `median_v`, `max_v`. `heat = 100 * clamp((m - median_v) / (max_v - median_v + 1e-6), 0, 1)`.
- Document: replays can mean skipping, so the signal is a soft prior.

### 6.2 Audio energy (`signal_audio.py`)
- Read `audio.wav` with `soundfile` in streaming blocks. Frame = 0.5 s; compute RMS in dBFS (floor -80).
- Baseline per frame: rolling median and MAD over +-300 s. `z = (db - median) / (1.4826*MAD + 1e-3)`.
- Window features: `energy = mean of the top 20% z values` and `bursts = count of frames with z > 2.0`, `burst_density = bursts / (duration / 10)`.
- `audio = 100 * clamp(0.6*clamp(energy/3,0,1) + 0.4*clamp(burst_density/3,0,1), 0, 1)`.
- This proxies laughter, shouting and hype; it does not detect laughter explicitly.

### 6.3 Speech ratio and topicality (`signal_speech.py`)
- `speech_ratio = sum(word durations in window) / window duration`, capped at 1.
- `topical_hits` = number of distinct glossary terms found (case-insensitive, whole word) in the window text.

Write `signals.json` keyed by `cid`.

## 7. Blend (`blend.py`)

```
w_llm, w_heat, w_audio = scoring.yaml weights (default 0.65, 0.20, 0.15)
if heat is null: renormalise: w_llm = 0.80, w_audio = 0.20, w_heat = 0
if heat_weight_override: w_heat = 0.05; renormalise the other two to sum 0.95
final = w_llm*llm_score + w_heat*(heat or 0) + w_audio*audio
final += min(5, 2.5 * topical_hits)           # GTA topical boost, only when PROJECT_DOMAIN=gta6
penalties:
  needs_context and context_fix is null         -> final -= 15
  needs_context and context_fix not null        -> final -= 4
  speech_ratio < 0.35                           -> final -= 20   (little commentary; also raises risk, section 10)
  scores.hook < 5                               -> final = min(final, 69)   # cannot reach tier A or B by other signals
  duration > 75 and not is_story                -> final -= 5
final = clamp(final, 0, 100)
```

## 8. Planner (`planner.py`): variable clip count

1. Drop candidates with `final < min_final` (default **60**).
2. **Tier:** A >= 80, B 70-79.99, C 60-69.99. The option `min_tier` (default "C") drops lower tiers.
3. **Overlap/dup removal:** sort by `final` desc. Keep a candidate only if: its time overlap with each kept clip is < 30% of the shorter, AND `rapidfuzz.fuzz.token_set_ratio` of the texts vs each kept clip < 85.
4. **Soft cap:** `MAX_CLIPS_SOFT = 40` per job (setting). If exceeded keep the 40 highest and record a warning. There is no per-video fixed count; 1 hour may yield 1 clip or 25.
5. Zero clips is a valid result: job ends `review` with message "No moments passed the quality bar (best score X). Lower the minimum tier to see weaker candidates." and the UI offers that option (re-plan from existing `judged.json` without re-running Gemini).
6. Order clips by `final` desc for building. Assign ids `c01...` in **time order** for the UI list.

## 9. Part splitter (prompt C, `prompts/plan_parts.md`)

Run for kept clips where `is_story` is true OR duration > 75 s, AND `final >= 70`, AND `max_parts` (default 4) allows.

```
You split one strong story into Parts for a short-form series.
Each part must be 30-60 seconds, start on a sentence boundary, and have its OWN hook so a viewer who only sees that part is still pulled in.
Part 1 ends on a cliffhanger or open question (the last sentence should create curiosity). The final part ends on the payoff.
Parts must be contiguous, in order, and together cover only sentences from the story (you may drop weak sentences between parts).
For parts 2+, write recap_line: max 8 words, plain, to show on screen at the start ("Previously: ...").
Use only the provided sentence ids. Between 2 and {{max_parts}} parts. If the story cannot be split cleanly, return one part.
STORY (sentences with ids and times):
{{story_block}}
Return JSON: {parts:[{part_index, start_sid, end_sid, cliffhanger_text, recap_line|null, hook_text}]}
```
Code validation: ids valid and ordered, each part 25-65 s (else merge/split by code to fit), no overlap. Create child clips `cNNp1..pK` with `parent_id`, `part_index`, `part_total`, each with its own `final` = parent final - 3 for parts 2+. The parent (full story) is **not** also kept as a standalone clip unless duration <= 90 s and the user option `keep_full_story` is true.

## 10. Risk (`risk.py`)

Compute `risk` and `risk_flags` per clip (see 10 for policy):
- `no_commentary` if `speech_ratio < 0.35` -> high.
- `low_commentary` if `0.35 <= speech_ratio < 0.5` -> medium.
- `non_cc_source` (license not Creative Commons) -> adds +1 level base "medium" unless channel allow-listed.
- `long_clip` if duration > 75 s -> medium.
- `allowlisted` -> reduces one level (not below low).
- `monetization_flag` if `content_flags` contains `profanity` or `violence` -> informational only.
Level = max over flags (high > medium > low). High-risk clips cannot be tier A (cap `final` at 79 and re-tier).

## 11. Fast lane (`fast_mode` option, for release-week speed)

When true: skip the second judge run, skip the second-look, batch judge 6 per call, build only tier A and B, use `WHISPER_MODEL=medium` if the video > 3 h. Target: a 60-minute video fully processed in under 12 minutes on the target laptop.

## 12. `config/scoring.yaml` (defaults)

```yaml
weights: {llm: 0.65, heat: 0.20, audio: 0.15}
rubric_weights: {hook: 0.25, payoff: 0.20, clarity: 0.15, emotion: 0.15, novelty: 0.10, shareability: 0.10, pace: 0.05}
thresholds: {min_final: 60, tier_a: 80, tier_b: 70}
limits: {min_clip_s: 15, max_clip_s: 60, story_max_s: 150, max_parts: 4, max_clips_soft: 40}
dedupe: {time_overlap: 0.30, text_similarity: 85}
chunk: {minutes: 20, overlap_s: 90}
penalties: {no_context: 15, fixable_context: 4, low_speech: 20, long_clip: 5, weak_hook_cap: 69}
```
The calibration script (09) may rewrite this file; keep a `.bak` of the previous version.

## 13. GTA 6 domain config

`config/glossary_gta6.yaml` (seed; extend after the first videos are processed):
```yaml
domain_description: "GTA 6 (Grand Theft Auto VI) news, trailers, gameplay, livestream reactions, leaks, map and feature discussion, and community reactions"
terms: [GTA 6, GTA VI, Grand Theft Auto VI, Vice City, Leonida, Leonida Keys, Lucia, Jason, Rockstar Games, Take-Two, Vice Beach, Ambrosia, Grassrivers, Port Gellhorn, Mount Kalaga, trailer, gameplay, physics, graphics, map, release date, pre-order, price, PS5, Xbox Series X, GTA Online]
moment_types_that_work: [first reactions, glitches and physics gags, hidden details and easter eggs, map and size reveals, feature comparisons with GTA 5, NPC behaviour, vehicle and stunt moments, price/release/edition announcements, hot takes and debates, streamer rage or hype]
```
Rubric additions for the domain (already in prompts through `domain_description`): "novelty" rewards first-seen footage and concrete reveals; "hook" rewards statements that name something specific in the game.
Release-week note: speed matters. Fast lane + building tier A first means the user can start posting before the full job ends (the UI shows finished clips as soon as each is packaged).

## 14. Honesty rules for the UI text

- Call scores "estimated viral potential", never "viral probability".
- Show per-clip `reasons.overall` and the three signal values so the user can judge.
- If heatmap is missing say "No replay data for this video".
