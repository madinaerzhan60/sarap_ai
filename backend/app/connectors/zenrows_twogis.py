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

    async def fetch_latest(self, last_seen_item_id: str | None = None, *, backfill: bool = False) -> list[RawItem]:
        api_key = os.getenv("ZENROWS_API_KEY", "").strip()
        if not api_key:
            raise ProviderNotConfigured("ZENROWS_API_KEY is empty")

        timeout = _timeout_seconds(backfill=backfill)
        params = {
            "url": self.page_url,
            "apikey": api_key,
            "js_render": "true",
            "premium_proxy": "true",
            "js_instructions": json.dumps(_zenrows_js_instructions(backfill=backfill)),
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
            scroll_count=_scroll_count(backfill=backfill),
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
        self.last_collection_metadata = {
            "scroll_count": _scroll_count(backfill=backfill),
            "accumulated_review_card_count": diagnostics["review_selector_count"],
            "history_complete": diagnostics["history_complete"],
            "no_growth_iterations": diagnostics["no_growth_iterations"],
            "parsed_count": len(items),
        }
        if not items:
            raise ProviderError("zenrows: no usable 2GIS reviews found in response")
        if last_seen_item_id and not backfill:
            items = items[
                : next(
                    (i for i, item in enumerate(items) if item.external_id == last_seen_item_id),
                    len(items),
                )
            ]
        return items


def _timeout_seconds(*, backfill: bool = False) -> float:
    raw = os.getenv("ZENROWS_TIMEOUT_SECONDS") or os.getenv("CRAWLER_TIMEOUT_SECONDS", "20")
    try:
        timeout = max(10.0, float(raw))
    except ValueError:
        timeout = 60.0
    if backfill:
        minimum_backfill_timeout = (_scroll_count(backfill=True) * _scroll_wait_ms() / 1000) + 30
        timeout = max(timeout, minimum_backfill_timeout)
    return timeout


def _scroll_wait_ms() -> int:
    raw = os.getenv("PLAYWRIGHT_SCROLL_WAIT_MS", "900")
    try:
        return max(0, int(raw))
    except ValueError:
        return 900


def _scroll_count(*, backfill: bool = False) -> int:
    variable = "TWOGIS_ZENROWS_BACKFILL_SCROLLS" if backfill else "TWOGIS_ZENROWS_SCROLLS"
    default = "40" if backfill else "5"
    cap = 150 if backfill else 25
    raw = os.getenv(variable, default).strip()
    try:
        return max(0, min(int(raw), cap))
    except ValueError:
        return int(default)


def _no_growth_limit() -> int:
    raw = os.getenv("TWOGIS_ZENROWS_NO_GROWTH_LIMIT", "8")
    try:
        return max(1, int(raw))
    except ValueError:
        return 8


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
    deduped = list({item.external_id: item for item in items}.values())
    return deduped or extract_reviews_from_html(html, page_url, "2gis")


def _safe_exception_detail(exc: BaseException, elapsed_seconds: float | None = None) -> str:
    class_name = type(exc).__name__
    elapsed = f" after {elapsed_seconds:.1f}s" if elapsed_seconds is not None else ""
    message = str(exc).strip()
    representation = repr(exc)
    if message:
        return f"{class_name}{elapsed}: {message}"
    return f"{class_name}{elapsed}: {representation}"


def _zenrows_js_instructions(*, backfill: bool = False) -> list[dict[str, str | int]]:
    wait_ms = _scroll_wait_ms()
    instructions: list[dict[str, str | int]] = [{"wait": 3000}]
    collect_script = """
window.__sarap2gisReviewKeys = window.__sarap2gisReviewKeys || {};
let container = document.querySelector('[data-sarap-accumulated-reviews="true"]');
if (!container) {
  container = document.createElement('div');
  container.setAttribute('data-sarap-accumulated-reviews', 'true');
  container.style.display = 'none';
  document.body.appendChild(container);
}
const liveCards = Array.from(document.querySelectorAll('div._1rowqpjv'))
  .filter((card) => !card.closest('[data-sarap-accumulated-reviews="true"]'));
    for (const card of liveCards) {
  const author = (card.querySelector('span[title]')?.getAttribute('title') || card.querySelector('span[title]')?.textContent || '').trim();
  const text = (card.querySelector('div._83kmcy a')?.textContent || '').replace(/\\s+/g, ' ').trim();
  const date = (card.querySelector('span._10c0hgu')?.textContent || '').trim();
  const rating = String(card.querySelectorAll('svg[color="#ffb81c"]').length || '');
  const key = card.getAttribute('data-review-id') || [author, text, date, rating].join('|');
  if (key && !window.__sarap2gisReviewKeys[key]) {
    window.__sarap2gisReviewKeys[key] = true;
    const clone = card.cloneNode(true);
    clone.setAttribute('data-sarap-review-key', key);
    container.appendChild(clone);
  }
}
""".strip()
    if backfill:
        scroll_count = _scroll_count(backfill=True)
        no_growth_limit = _no_growth_limit()
        indented_collect_script = collect_script.replace("\n", "\n    ")
        backfill_script = f"""
(async () => {{
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const collectCurrentReviewCards = () => {{
    {indented_collect_script}
  }};
  const scrollCount = {scroll_count};
  const waitMs = {wait_ms};
  const noGrowthLimit = {no_growth_limit};
  let previousCount = 0;
  let noGrowthIterations = 0;
  let completed = false;
  for (let i = 0; i < scrollCount; i += 1) {{
    collectCurrentReviewCards();
    const accumulator = document.querySelector('[data-sarap-accumulated-reviews="true"]');
    const accumulatedCount = accumulator ? accumulator.querySelectorAll('div._1rowqpjv').length : 0;
    if (accumulatedCount > previousCount) {{
      previousCount = accumulatedCount;
      noGrowthIterations = 0;
    }} else {{
      noGrowthIterations += 1;
    }}
    if (noGrowthIterations >= noGrowthLimit) {{
      completed = true;
      break;
    }}
    const cards = Array.from(document.querySelectorAll('div._1rowqpjv'))
      .filter((card) => !card.closest('[data-sarap-accumulated-reviews="true"]'));
    if (cards.length) {{
      cards[cards.length - 1].scrollIntoView({{block: 'end'}});
    }} else {{
      const candidates = Array.from(document.querySelectorAll('main, [data-scroll="true"], div'))
        .filter((el) => el.scrollHeight > el.clientHeight + 200)
        .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));
      if (candidates[0]) {{
        candidates[0].scrollTop += 1400;
      }}
      window.scrollBy(0, 1400);
    }}
    if (waitMs > 0) await sleep(waitMs);
  }}
  collectCurrentReviewCards();
  const accumulator = document.querySelector('[data-sarap-accumulated-reviews="true"]');
  if (accumulator) {{
    const finalCount = accumulator.querySelectorAll('div._1rowqpjv').length;
    accumulator.setAttribute('data-sarap-history-complete', String(completed || noGrowthIterations >= noGrowthLimit));
    accumulator.setAttribute('data-sarap-accumulated-count', String(finalCount));
    accumulator.setAttribute('data-sarap-no-growth-iterations', String(noGrowthIterations));
  }}
}})();
""".strip()
        instructions.append({"evaluate": backfill_script})
        return instructions

    scroll_script = collect_script + """
const cards = Array.from(document.querySelectorAll('div._1rowqpjv'))
  .filter((card) => !card.closest('[data-sarap-accumulated-reviews="true"]'));
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
    for _ in range(_scroll_count(backfill=backfill)):
        instructions.append({"evaluate": scroll_script})
        instructions.append({"wait": wait_ms})
    instructions.append({"evaluate": collect_script})
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
        self.history_complete = False
        self.no_growth_iterations = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self.in_title = True
        if tag.lower() == "div":
            values = {key.lower(): value or "" for key, value in attrs}
            classes = values.get("class", "").split()
            if "_1rowqpjv" in classes:
                self.review_selector_count += 1
            if values.get("data-sarap-accumulated-reviews") == "true":
                self.history_complete = values.get("data-sarap-history-complete") == "true"
                try:
                    self.no_growth_iterations = int(values.get("data-sarap-no-growth-iterations") or "0")
                except ValueError:
                    self.no_growth_iterations = 0

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
        "history_complete": parser.history_complete,
        "no_growth_iterations": parser.no_growth_iterations,
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
