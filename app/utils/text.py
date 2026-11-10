"""Text normalization, slugification, profanity masking, and word utilities."""

from __future__ import annotations

import re

FILLER_WORDS = {
    "um",
    "uh",
    "er",
    "ah",
    "hmm",
    "like",
}


def slugify(text: str, max_len: int = 60) -> str:
    """Generate clean URL/folder-safe slug: lowercase ASCII with hyphens."""
    clean = re.sub(r"[^\w\s-]", "", text.strip()).strip().lower()
    slug = re.sub(r"[-\s]+", "-", clean)
    return slug[:max_len].strip("-") or "video"


def strip_punct(word: str) -> str:
    """Remove leading and trailing punctuation from a token."""
    return word.strip(".,!?:;\"'()[]{}*~`-_/")


def is_filler(word: str) -> bool:
    """Check if token is a standard speech filler word."""
    clean = strip_punct(word).lower()
    return clean in FILLER_WORDS


def mask_profanity(text: str, profanity_list: list[str], mask_char: str = "*") -> str:
    """Mask profanity words while preserving word boundaries and case style."""
    if not profanity_list or not text:
        return text

    result = text
    for bad in sorted(profanity_list, key=len, reverse=True):
        bad_clean = bad.strip().lower()
        if not bad_clean:
            continue

        def replacer(match: re.Match) -> str:
            val = match.group(0)
            if len(val) <= 2:
                return mask_char * len(val)
            return val[0] + (mask_char * (len(val) - 2)) + val[-1]

        pattern = rf"\b{re.escape(bad_clean)}\b"
        result = re.sub(pattern, replacer, result, flags=re.IGNORECASE)

    return result


def truncate_words(text: str, max_chars: int) -> str:
    """Truncate text at word boundaries to not exceed max_chars (no trailing ellipsis)."""
    clean = text.strip()
    if len(clean) <= max_chars:
        return clean

    words = clean.split()
    out: list[str] = []
    curr_len = 0
    for w in words:
        addition = len(w) if not out else len(w) + 1
        if curr_len + addition > max_chars:
            break
        out.append(w)
        curr_len += addition

    return " ".join(out)
