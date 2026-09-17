import hashlib
import re
import unicodedata
from uuid import UUID

from app.models import NormalizedMention, RawItem


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def content_hash(item: RawItem) -> str:
    payload = f"{item.source.lower()}|{item.external_id}|{normalize_text(item.text).casefold()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize(item: RawItem, business_id: UUID) -> NormalizedMention:
    data = item.model_dump()
    data["text"] = normalize_text(item.text)
    return NormalizedMention(**data, business_id=business_id, content_hash=content_hash(item))
