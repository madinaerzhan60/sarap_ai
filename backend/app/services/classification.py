from __future__ import annotations

from app.models import AuthorType, ContentType, MentionType, RawItem


def classify_content(item: RawItem) -> ContentType:
    explicit = item.metadata.get("content_type")
    if explicit in {value.value for value in ContentType}:
        return ContentType(explicit)
    if item.source_type == MentionType.review or item.source.casefold() in {"2gis", "google maps", "google_business", "yandex_maps", "manual"}:
        return ContentType.review
    if item.source_type in {MentionType.social_comment, MentionType.video_comment}:
        return ContentType.question if item.text.rstrip().endswith("?") else ContentType.comment
    if item.source_type == MentionType.news_article:
        return ContentType.news
    if item.source_type == MentionType.social_post:
        return ContentType.question if item.text.rstrip().endswith("?") else ContentType.post
    return ContentType.other


def classify_author(item: RawItem) -> tuple[AuthorType, bool]:
    explicit = item.metadata.get("author_type")
    if explicit in {value.value for value in AuthorType}:
        author_type = AuthorType(explicit)
    elif item.metadata.get("is_business_reply") or item.metadata.get("official_account"):
        author_type = AuthorType.company
    elif item.metadata.get("is_employee"):
        author_type = AuthorType.employee
    elif item.source.casefold() in {"2gis", "google maps", "google_business", "yandex_maps", "manual"} or item.rating is not None:
        author_type = AuthorType.customer
    else:
        author_type = AuthorType.unknown
    return author_type, author_type not in {AuthorType.employee, AuthorType.company}
