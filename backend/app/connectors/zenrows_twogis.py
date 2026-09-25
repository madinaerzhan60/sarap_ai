"""ZenRows connector for 2GIS reviews."""

from __future__ import annotations

import json
import logging
import os
import time
from html.parser import HTMLParser

import httpx

from app.connectors.base import BaseConnector
from app.connectors.reviews import extract_reviews_from_html, normalize_twogis_business_url
from app.models import ConnectionType, MentionType, RawItem
from app.scrapers.maps_playwright import PROFILES, extract_map_items
from app.scrapers.fallback import ProviderError, ProviderNotConfigured

logger = logging.getLogger(__name__)

TWOGIS_REVIEW_CARD_SELECTOR = "div._1rowqpjv"


class ZenRowsTwoGisConnector(BaseConnector):
    """Fetch a 2GIS reviews page through ZenRows and reuse the existing parser."""

    source = "2gis"
    connection_type = ConnectionType.monitored
    collection_method = "zenrows"

    def __init__(self, page_url: str, business_id: str = "global") -> None:
        self.page_url = normalize_twogis_business_url(page_url)
        self.business_id = business_id

    async def fetch_latest(self, last_seen_item_id: str | None = None) -> list[RawItem]:
        api_key = os.getenv("ZENROWS_API_KEY", "").strip()
        if not api_key:
            raise ProviderNotConfigured("ZENROWS_API_KEY is empty")

        timeout = _timeout_seconds()
        params = {
            "url": self.page_url,
            "apikey": api_key,
            "js_render": "true",
            "premium_proxy": "true",
            "js_instructions": json.dumps(_zenrows_js_instructions()),
        }
        started_at = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                response = await client.get("https://api.zenrows.com/v1/", params=params)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            elapsed = time.monotonic() - started_at
            raise ProviderError(f"zenrows: {_safe_exception_detail(exc, elapsed)}") from exc

        html = response.text.strip()
        if not html:
            raise ProviderError("zenrows: empty response")
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type and not _looks_like_html(html):
            raise ProviderError(f"zenrows: unexpected content type {content_type}")
        final_url = str(getattr(response, "url", "")) or response.headers.get("zr-final-url", "")
        blocked = _looks_blocked(html, final_url)
        diagnostics = diagnose_zenrows_twogis_response(
            html,
            status_code=response.status_code,
            content_type=content_type,
            final_url=final_url,
            scroll_count=_scroll_count(),
            blocked=blocked,
        )
        logger.info(
            "zenrows_twogis status=%s final_url=%s content_type=%s body_size=%s scrolls=%s review_elements=%s blocked=%s title=%s",
            diagnostics["status_code"],
            diagnostics["final_url"],
            diagnostics["content_type"],
            diagnostics["body_size"],
            diagnostics["scroll_count"],
            diagnostics["review_selector_count"],
            diagnostics["blocked"],
            diagnostics["title"],
        )
        if blocked:
            raise ProviderError("zenrows: blocked or captcha response")

        items = _extract_twogis_items(html, self.page_url)
        if not items:
            raise ProviderError("zenrows: no usable 2GIS reviews found in response")
        if last_seen_item_id:
            items = items[
                : next(
                    (i for i, item in enumerate(items) if item.external_id == last_seen_item_id),
                    len(items),
                )
            ]
        return items


def _timeout_seconds() -> float:
    raw = os.getenv("ZENROWS_TIMEOUT_SECONDS") or os.getenv("CRAWLER_TIMEOUT_SECONDS", "20")
    try:
        return max(10.0, float(raw))
    except ValueError:
        return 60.0


def _scroll_count() -> int:
    raw = os.getenv("TWOGIS_ZENROWS_SCROLLS", "5").strip()
    try:
        return max(0, min(int(raw), 25))
    except ValueError:
        return 5


def _extract_twogis_items(html: str, page_url: str) -> list[RawItem]:
    scraped = extract_map_items(
        html,
        PROFILES["2gis"],
        page_url,
        max(1, int(os.getenv("INITIAL_REVIEW_LIMIT", "500"))),
        "zenrows",
    )
    items = [
        RawItem(
            source="2gis",
            source_type=MentionType.review,
            external_id=item.stable_id(),
            external_url=item.url,
            author_name=None if item.author == "Unknown" else item.author,
            text=item.text_content,
            rating=item.rating,
            published_at=item.published_at,
            metadata={**item.metadata, "language": item.language, "collected_by": "zenrows"},
        )
        for item in scraped
    ]
    return items or extract_reviews_from_html(html, page_url, "2gis")


def _safe_exception_detail(exc: BaseException, elapsed_seconds: float | None = None) -> str:
    class_name = type(exc).__name__
    elapsed = f" after {elapsed_seconds:.1f}s" if elapsed_seconds is not None else ""
    message = str(exc).strip()
    representation = repr(exc)
    if message:
        return f"{class_name}{elapsed}: {message}"
    return f"{class_name}{elapsed}: {representation}"


def _zenrows_js_instructions() -> list[dict[str, str | int]]:
    wait_ms = int(os.getenv("PLAYWRIGHT_SCROLL_WAIT_MS", "900"))
    instructions: list[dict[str, str | int]] = [{"wait": 3000}]
    scroll_script = """
const cards = document.querySelectorAll('div._1rowqpjv');
if (cards.length) {
  cards[cards.length - 1].scrollIntoView({block: 'end'});
} else {
  const candidates = Array.from(document.querySelectorAll('main, [data-scroll="true"], div'))
    .filter((el) => el.scrollHeight > el.clientHeight + 200)
    .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));
  if (candidates[0]) {
    candidates[0].scrollTop += 1400;
  }
  window.scrollBy(0, 1400);
}
""".strip()
    for _ in range(_scroll_count()):
        instructions.append({"evaluate": scroll_script})
        instructions.append({"wait": wait_ms})
    return instructions


def _looks_like_html(html: str) -> bool:
    normalized = html.lstrip().lower()
    return (
        normalized.startswith("<html")
        or normalized.startswith("<!doctype")
        or "<body" in normalized
    )


class _DiagnosticHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.title_parts: list[str] = []
        self.review_selector_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self.in_title = True
        if tag.lower() == "div":
            values = {key.lower(): value or "" for key, value in attrs}
            classes = values.get("class", "").split()
            if "_1rowqpjv" in classes:
                self.review_selector_count += 1

    def handle_data(self, data: str) -> None:
        if self.in_title and data.strip():
            self.title_parts.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    @property
    def title(self) -> str:
        return " ".join(" ".join(self.title_parts).split())


def diagnose_zenrows_twogis_response(
    html: str,
    *,
    status_code: int | None = None,
    content_type: str = "",
    final_url: str = "",
    scroll_count: int | None = None,
    blocked: bool | None = None,
) -> dict[str, object]:
    parser = _DiagnosticHtmlParser()
    parser.feed(html)
    return {
        "status_code": status_code,
        "final_url": final_url,
        "content_type": content_type,
        "body_size": len(html.encode("utf-8")),
        "scroll_count": _scroll_count() if scroll_count is None else scroll_count,
        "title": parser.title,
        "captcha_2gis_present": "captcha.2gis." in html.lower() or "captcha.2gis." in final_url.lower(),
        "block_evidence": blocked if blocked is not None else _looks_blocked(html, final_url),
        "blocked": blocked if blocked is not None else _looks_blocked(html, final_url),
        "review_selector_count": parser.review_selector_count,
    }


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._hidden_depth += 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth and data.strip():
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._hidden_depth:
            self._hidden_depth -= 1

    @property
    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())


def _visible_text(html: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(html)
    return parser.text


def _looks_blocked(html: str, final_url: str = "") -> bool:
    if "captcha.2gis." in final_url.lower():
        return True

    normalized = _visible_text(html).casefold()
    return any(
        marker in normalized
        for marker in (
            "captcha",
            "access denied",
            "are you a human",
            "verify you are human",
            "unusual traffic",
            "капча",
            "подтвердите, что вы не робот",
            "подозрительную активность",
        )
    )
