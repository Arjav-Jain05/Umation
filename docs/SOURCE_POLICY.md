# Source Creator Rights & Fair-Use Policy

This policy document governs how `shorts-engine` extracts, attributes, assesses risk, and packages video clips from third-party content creators.

---

## 1. Credit Alone Does NOT Equate to Fair Use

A common misconception in content clipping is that adding "No copyright infringement intended" or naming the original creator legally shields a publisher from copyright infringement.

> **CRITICAL LEGAL NOTICE**:
> Attribution and credit blocks do **NOT** automatically grant fair-use protection under United States copyright law (17 U.S.C. § 107) or international equivalents.

Fair use is an affirmative defense evaluated on four statutory factors:
1. **The Purpose and Character of the Use**: Transformative value (e.g. insightful commentary, critique, education, humorous reaction) weighs heavily in favor of fair use. Verbatim gameplay extraction without commentary or original perspective weighs against fair use.
2. **The Nature of the Copyrighted Work**: Creative and artistic works receive stronger protection than purely factual recordings.
3. **The Amount and Substantiality of the Portion Used**: Clipping short, focused excerpts (15–60 seconds) rather than whole broadcasts strongly favors fair use.
4. **The Effect of the Use Upon the Potential Market**: If your short substitutes for the original video or diverts viewership, it harms fair use. If it acts as promotional discovery directing fans to the source channel, the risk is reduced.

---

## 2. Mandatory Creator Credit Block

Every video packaged by `shorts-engine` automatically embeds a structured, prominent credit block into the video description and metadata:

```markdown
═══════════════════════════════════════════════
ORIGINAL CREATOR ATTRIBUTION:
Source Video: {source_title}
Creator Channel: {channel_name} ({channel_url})
Original Broadcast: {webpage_url}

All rights remain with the original content creator.
═══════════════════════════════════════════════
```

The application strictly forbids removing this block from automated export packages.

---

## 3. Per-Clip Source Risk Assessment (`source_risk_notes`)

`shorts-engine` computes automated risk scores during the `assess_risk` stage:

| Risk Level | Characteristics | Restrictions Enforced |
|---|---|---|
| **Low** | High commentary ratio (>45%), strong transformative hook, clear original reaction | Eligible for Tier S and A ratings |
| **Medium** | Moderate speech ratio (25–45%), contextual gameplay commentary | Eligible for Tier B and C ratings |
| **High** | Pure gameplay without speech or commentary (<25% speech ratio) | Final score capped at 79.0; ineligible for Tier A/S; flagged for manual review |

### Recording Creator Policy
Each clip record contains an auditable `source_risk_notes` field. Users must document:
- Whether the creator has a public clipping policy (e.g., "Clips allowed with credit", "No clipping allowed", "Members-only stream").
- Any specific embargoes, spoilers, or monetization restrictions requested by the creator.

---

## 4. Prohibited Content Sources

`shorts-engine` strictly refuses:
1. Private, unlisted, or members-only broadcasts.
2. Non-public livestreams or content protected behind authentication barriers.
3. Channels on the local blocklist (`config/source_policy.yaml`).
4. Re-uploading of existing vertical shorts (content already formatted as 9:16 Shorts/Reels/TikToks).
