# 10. Fair use, credit and risk policy

Contents: 1 What this tool does and does not do · 2 Why credit is not permission · 3 Source policy file · 4 Risk model · 5 Behaviour rules for the agent · 6 UI texts · 7 Privacy · 8 Safe working practice for the user

This policy is not legal advice and the app must never present itself as giving legal advice.

## 1. What this tool does and does not do

Does: refuses blocklisted sources, records the user's acknowledgement, writes a factual credit block, flags risky clips, keeps clips short, favours clips with spoken commentary, and adds transformative elements (captions, on-screen explanations, arrows).
Does not: decide whether a use is fair use, guarantee that a clip will not receive a claim or takedown, remove watermarks or hide the source, or upload anything.

## 2. Why credit is not permission

Giving credit and writing "no copyright infringement intended" do not give anyone rights. Fair use (where it applies, e.g. in the US) is judged case by case on purpose, amount used, effect on the original's market and how transformative the use is. In practice, platforms also run automated systems (for example content-matching) that act before any human considers fair use, and rights holders may issue claims or takedowns. The app therefore:
- writes only the factual credit and a rights-ownership line (07 section 5);
- never writes "fair use", "no infringement intended", or similar claims;
- shows risk flags instead of reassurance.

For GTA 6 material specifically, the source video usually contains two layers of other people's rights: the streamer's own content and the game publisher's footage. Assume the rights holders may enforce. This is a risk the user knowingly takes; the app must make it visible, not hide it.

## 3. Source policy file (`config/source_policy.yaml`)

```yaml
# Channels are matched by channel_id first, then by lower-cased channel name.
allow:        # channels that have explicitly allowed clipping/reuse (user fills in)
  - {name: "", channel_id: "", note: "e.g. permission email or posted clipping policy"}
block:        # never process these
  - {name: "", channel_id: "", note: ""}
require_cc: false     # if true, only Creative Commons or allowlisted sources are processed
max_clip_seconds: 90  # absolute ceiling regardless of options
```
If `require_cc` is true and the source is neither CC-licensed nor allowlisted, the job fails at `source_check` with `SourceBlocked("This source is not Creative Commons or allowlisted.")`. Default false (the user's choice), but the UI explains the option.

## 4. Risk model (implemented in `risk.py`, 04 section 10)

Flags: `no_commentary` (high), `low_commentary` (medium), `non_cc_source` (medium unless allowlisted), `long_clip` (medium), `allowlisted` (lowers by one level), `missing_channel` (medium), `monetization_flag` (info), `duplicate_of_other_source` (info, when the same moment text appears in a previous job; optional).
Overall risk = the highest flag level after adjustments. High-risk clips cannot be tier A.
Rationale shown in the UI tooltip:
- no/low commentary: the clip is mostly someone else's footage with little added.
- non-CC source: the creator has not granted reuse.
- long clip: using more of the original weighs against reuse.

## 5. Behaviour rules for the agent building and running the app

1. Never remove or obscure the credit block. Never offer an option to turn it off.
2. Never add features to evade detection (pitch/speed/mirror tricks, hiding the source, cropping out watermarks to hide origin).
3. Never process private, members-only, paid, age-gated or otherwise restricted videos, and never use cookies.
4. Keep default clip length <= 60 s; absolute ceiling 90 s (Parts are each <= 65 s).
5. Do not reproduce a whole video as a series of Parts. Cap total Part-clips per source at 25% of the source duration; log a warning when reached and stop adding.
6. Prefer commentary: the speech-ratio penalty and risk flags exist for this reason; do not tune them away.
7. If the user asks the agent whether something is fair use, the agent explains the four factors briefly, says it cannot decide, and recommends the user consult a qualified person for important cases.
8. Do not generate thumbnails with official logos, official key art or real people's likenesses (07).
9. Store the acknowledgement (`ack_fair_use`, `ack_at`) with every job.

## 6. UI texts (use exactly)

- Acknowledgement checkbox: "I understand I am responsible for deciding whether I may reuse this video. The tool adds credits and risk flags but does not give legal advice."
- Non-CC warning (shown at `source_check`): "This video is not Creative Commons. Reusing it may lead to claims or takedowns. Check the creator's reuse policy."
- High risk tooltip: "High risk: this clip is mostly the original creator's footage with little commentary."
- Footer on job page: "Credits are added to every description. Credits do not grant permission."

## 7. Privacy

Sent to Gemini: transcript text for chunks and candidates, and a few still frames of the finished vertical clip (arrow targets only, at most 8 per clip). No full videos, no audio. Everything else stays on the laptop. State this in `README.md`. No analytics, no telemetry. The API key lives only in `.env` (gitignored).

## 8. Safe working practice to recommend to the user (README section)

- Prefer sources that explicitly allow clipping, Creative Commons videos and your own content.
- Add real commentary or explanation on top of clips when you can; clips that are just footage are the riskiest.
- Keep clips short and add context (the app's captions and hook text help).
- Expect that rights holders may claim or remove content, and don't build anything you can't afford to lose on a single channel.
- Check each platform's current reuse and monetization policies before posting.
