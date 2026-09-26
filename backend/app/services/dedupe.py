"""Deduplication service for SARAP mentions.

Two levels:
1. STRICT: same source item ingested twice → no new logical row.
   Uses dedupe_key (source + author + normalized text).
2. NEAR: long copied/reposted content across sources → group under canonical.
   Conservative: only for sufficiently long content with high similarity.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any


# ---------------------------------------------------------------------------
# Text normalization helpers
# ---------------------------------------------------------------------------

def _normalize_for_comparison(text: str) -> str:
    """Aggressively normalize text for near-duplicate comparison."""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s+", " ", text).strip().casefold()
    # Remove common punctuation variations
    text = re.sub(r"[""\"''«»]", '"', text)
    text = re.sub(r"[—–-]", "-", text)
    text = re.sub(r"[…]", "...", text)
    return text


# ---------------------------------------------------------------------------
# Near-duplicate detection
# ---------------------------------------------------------------------------

MIN_LENGTH_FOR_NEAR_DEDUPE = 120  # characters — don't near-match short texts


def _token_set(text: str) -> set[str]:
    """Split normalized text into word tokens."""
    return set(re.findall(r"\w+", text))


def jaccard_similarity(a: str, b: str) -> float:
    """Token-level Jaccard similarity."""
    set_a = _token_set(a)
    set_b = _token_set(b)
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def containment_ratio(shorter: str, longer: str) -> float:
    """What fraction of shorter's tokens appear in longer."""
    set_short = _token_set(shorter)
    set_long = _token_set(longer)
    if not set_short:
        return 0.0
    return len(set_short & set_long) / len(set_short)


def is_near_duplicate(text_a: str, text_b: str, threshold: float = 0.75) -> bool:
    """Conservative near-duplicate check for long content only.

    Short texts (< MIN_LENGTH_FOR_NEAR_DEDUPE chars) are never considered
    near-duplicates to avoid merging independent short comments like
    "❤️", "Топ", "Amazing".
    """
    norm_a = _normalize_for_comparison(text_a)
    norm_b = _normalize_for_comparison(text_b)

    # Short texts: never near-match
    if len(norm_a) < MIN_LENGTH_FOR_NEAR_DEDUPE or len(norm_b) < MIN_LENGTH_FOR_NEAR_DEDUPE:
        return False

    # Exact normalized match
    if norm_a == norm_b:
        return True

    # Jaccard similarity
    if jaccard_similarity(norm_a, norm_b) >= threshold:
        return True

    # Containment: one is a subset of the other
    shorter, longer = (norm_a, norm_b) if len(norm_a) <= len(norm_b) else (norm_b, norm_a)
    if containment_ratio(shorter, longer) >= 0.85:
        return True

    return False


def find_near_duplicate_group(
    new_text: str,
    candidates: list[dict[str, Any]],
    threshold: float = 0.75,
) -> dict[str, Any] | None:
    """Find the best canonical match among existing mentions.

    Args:
        new_text: text of the new mention
        candidates: list of dicts with at least 'id' and 'text' keys
        threshold: Jaccard threshold for near-duplicate

    Returns:
        The best matching candidate dict, or None
    """
    best_match: dict[str, Any] | None = None
    best_score = 0.0

    for candidate in candidates:
        candidate_text = candidate.get("text", "")
        if not candidate_text:
            continue
        if not is_near_duplicate(new_text, candidate_text, threshold):
            continue

        norm_new = _normalize_for_comparison(new_text)
        norm_cand = _normalize_for_comparison(candidate_text)
        score = jaccard_similarity(norm_new, norm_cand)
        if score > best_score:
            best_score = score
            best_match = candidate

    return best_match
