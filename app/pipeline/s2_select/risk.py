"""Fair-use risk evaluation and policy flags per clip."""

from __future__ import annotations

from app.core.schemas import SourceInfo

LEVEL_ORDER = {"low": 1, "medium": 2, "high": 3}
ORDER_TO_LEVEL = {1: "low", 2: "medium", 3: "high"}


def assess(
    duration_s: float,
    speech_ratio: float,
    source_info: SourceInfo,
    content_flags: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Determine fair-use risk level (low, medium, high) and descriptive flags."""
    flags: list[str] = []
    level_rank = 1  # default low

    # 1. Commentary ratio
    if speech_ratio < 0.35:
        flags.append("no_commentary")
        level_rank = max(level_rank, 3)
    elif speech_ratio < 0.50:
        flags.append("low_commentary")
        level_rank = max(level_rank, 2)

    # 2. License check
    is_cc = bool(source_info.license and "creative commons" in source_info.license.lower())
    is_allowlisted = source_info.source_policy.status == "allow"

    if not is_cc and not is_allowlisted:
        flags.append("non_cc_source")
        level_rank = max(level_rank, 2)

    # 3. Long clip
    if duration_s > 75.0:
        flags.append("long_clip")
        level_rank = max(level_rank, 2)

    # 4. Content flags (monetization warnings)
    flags_set = set(content_flags or [])
    if "profanity" in flags_set or "violence" in flags_set:
        flags.append("monetization_flag")

    # 5. Allowlisted adjustment
    if is_allowlisted:
        flags.append("allowlisted")
        level_rank = max(1, level_rank - 1)

    return ORDER_TO_LEVEL[level_rank], flags
