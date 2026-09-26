import hashlib
import re
import unicodedata
from uuid import UUID

from app.models import NormalizedMention, RawItem
from app.services.classification import classify_author, classify_content


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalized_casefold(text: str) -> str:
    """Normalize whitespace, unicode, then casefold for stable comparison."""
    return normalize_text(text).casefold()


def content_hash(item: RawItem) -> str:
    """Stable content hash for strict duplicate detection.

    Uses source + normalized text only.  Does NOT include external_id because
    external_id may contain volatile relative-date text for fallback scraped
    items (e.g. "3 дня назад" changes to "4 дня назад" the next day).
    """
    payload = f"{item.source.lower()}|{_normalized_casefold(item.text)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def dedupe_key(item: RawItem) -> str:
    """Stable fingerprint for strict deduplication within a source.

    Combines source + author (if available) + normalized text.
    Independent of external_id and date labels.
    """
    author = _normalized_casefold(item.author_name or "")
    text = _normalized_casefold(item.text)
    payload = f"{item.source.lower()}|{author}|{text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize(item: RawItem, business_id: UUID) -> NormalizedMention:
    data = item.model_dump()
    data["text"] = normalize_text(item.text)
    stable_author_id = str(item.metadata.get("author_id") or item.metadata.get("author_external_id") or "").strip()
    normalized_name = normalize_text(item.author_name or "").casefold()
    data["metadata"] = {**item.metadata, "author_key": stable_author_id or normalized_name}
    author_type, include_in_analysis = classify_author(item)
    return NormalizedMention(
        **data,
        business_id=business_id,
        content_hash=content_hash(item),
        dedupe_key=dedupe_key(item),
        content_type=classify_content(item),
        author_type=author_type,
        include_in_analysis=include_in_analysis,
    )
