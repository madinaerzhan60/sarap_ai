from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import ipaddress
import json
import os
import asyncio
import re
import socket
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.connectors.base import BaseConnector
from app.models import ConnectionType, MentionType, RawItem


class ConnectorUnavailable(RuntimeError):
    """The selected collection method cannot currently be used."""


def _safe_public_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConnectorUnavailable("A public http(s) source URL is required")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        raise ConnectorUnavailable("Local addresses cannot be monitored")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and not address.is_global:
        raise ConnectorUnavailable("Private network addresses cannot be monitored")
    allowed = [x.strip().lower() for x in os.getenv("CRAWLER_ALLOWED_HOSTS", "").split(",") if x.strip()]
    if allowed and not any(host == item or host.endswith(f".{item}") for item in allowed):
        raise ConnectorUnavailable(f"Host {host} is not in CRAWLER_ALLOWED_HOSTS")
    return value


async def _assert_public_dns(value: str) -> None:
    parsed = urlparse(_safe_public_url(value))
    try:
        records = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ConnectorUnavailable(f"Could not resolve source host: {parsed.hostname}") from exc
    addresses = {record[4][0] for record in records}
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ConnectorUnavailable("The source host resolves to a private or reserved network")


async def _public_get(client: httpx.AsyncClient, value: str, *, max_redirects: int = 5) -> httpx.Response:
    current = _safe_public_url(value)
    for _ in range(max_redirects + 1):
        await _assert_public_dns(current)
        response = await client.get(current)
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response
        location = response.headers.get("location")
        if not location:
            return response
        current = _safe_public_url(urljoin(current, location))
    raise ConnectorUnavailable("The source exceeded the redirect limit")


def _walk_json(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _type_is_review(value: Any) -> bool:
    types = value if isinstance(value, list) else [value]
    return any(str(item).lower().endswith("review") for item in types)


def _author_name(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        return str(value.get("name") or "").strip() or None
    return None


def _rating(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("ratingValue")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= 5 else None


def _make_item(source: str, page_url: str, text: str, *, author: str | None = None, rating: float | None = None, published: str | None = None, external_id: str | None = None) -> RawItem:
    stable = external_id or hashlib.sha256(f"{source}|{author}|{rating}|{text}".encode()).hexdigest()
    return RawItem(
        source=source,
        source_type=MentionType.review,
        external_id=stable,
        external_url=page_url,
        author_name=author,
        text=text,
        rating=rating,
        published_at=published,
        metadata={"collection_method": "scraper", "structured_data": True},
    )


class _ReviewHtmlParser(HTMLParser):
    """Extract JSON-LD and basic schema.org review microdata without site-specific bypasses."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.json_scripts: list[str] = []
        self._in_json = False
        self._json_parts: list[str] = []
        self._review_depth = 0
        self._field: str | None = None
        self._current: dict[str, Any] | None = None
        self.microdata: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        if tag == "script" and values.get("type", "").lower() == "application/ld+json":
            self._in_json = True
            self._json_parts = []
            return
        itemtype = values.get("itemtype", "").lower()
        if self._review_depth == 0 and "schema.org/review" in itemtype:
            self._review_depth = 1
            self._current = {}
        elif self._review_depth:
            self._review_depth += 1
        if self._review_depth:
            prop = values.get("itemprop")
            if prop in {"reviewBody", "author", "ratingValue", "datePublished"}:
                self._field = prop
                content = values.get("content")
                if content and self._current is not None:
                    self._current[prop] = content

    def handle_data(self, data: str) -> None:
        if self._in_json:
            self._json_parts.append(data)
        elif self._review_depth and self._field and self._current is not None and data.strip():
            self._current[self._field] = f"{self._current.get(self._field, '')} {data.strip()}".strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_json:
            self.json_scripts.append("".join(self._json_parts))
            self._in_json = False
            self._json_parts = []
            return
        if self._review_depth:
            self._review_depth -= 1
            self._field = None
            if self._review_depth == 0 and self._current:
                self.microdata.append(self._current)
                self._current = None


def extract_reviews_from_html(html: str, page_url: str, source: str) -> list[RawItem]:
    parser = _ReviewHtmlParser()
    parser.feed(html)
    items: list[RawItem] = []
    for script in parser.json_scripts:
        try:
            document = json.loads(script)
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _walk_json(document):
            if not _type_is_review(node.get("@type")):
                continue
            text = str(node.get("reviewBody") or node.get("description") or "").strip()
            if not text:
                continue
            items.append(_make_item(source, str(node.get("url") or page_url), text, author=_author_name(node.get("author")), rating=_rating(node.get("reviewRating")), published=node.get("datePublished"), external_id=str(node.get("@id") or "") or None))
    for node in parser.microdata:
        text = str(node.get("reviewBody") or "").strip()
        if text:
            items.append(_make_item(source, page_url, text, author=_author_name(node.get("author")), rating=_rating(node.get("ratingValue")), published=node.get("datePublished")))
    return list({item.external_id: item for item in items}.values())


class ReviewPageScraperConnector(BaseConnector):
    """Focused scraper for one customer-supplied public URL."""

    connection_type = ConnectionType.monitored
    collection_method = "scraper"

    def __init__(self, page_url: str, source_name: str) -> None:
        self.page_url = _safe_public_url(page_url)
        self.source = source_name.lower().strip()

    async def fetch_latest(self, last_seen_item_id: str | None = None) -> list[RawItem]:
        user_agent = os.getenv("CRAWLER_USER_AGENT", "SARAPBot/0.1 (+https://sarap.ai/bot)")
        timeout = float(os.getenv("CRAWLER_TIMEOUT_SECONDS", "20"))
        max_bytes = int(os.getenv("CRAWLER_MAX_RESPONSE_BYTES", "2000000"))
        headers = {"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"}
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, headers=headers) as client:
            if os.getenv("CRAWLER_RESPECT_ROBOTS_TXT", "true").lower() == "true":
                robots_url = urljoin(self.page_url, "/robots.txt")
                try:
                    robots_response = await _public_get(client, robots_url)
                except httpx.HTTPError as exc:
                    raise ConnectorUnavailable(f"Could not verify robots.txt: {exc}") from exc
                if robots_response.status_code == 200:
                    robots = RobotFileParser(robots_url)
                    robots.parse(robots_response.text.splitlines())
                    if not robots.can_fetch(user_agent, self.page_url):
                        raise ConnectorUnavailable("This website blocks automatic collection. Use its official API or import reviews with Paste text / HTML.")
            try:
                response = await _public_get(client, self.page_url)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ConnectorUnavailable(f"The source website returned HTTP {exc.response.status_code}") from exc
            except httpx.HTTPError as exc:
                raise ConnectorUnavailable("The source website is currently unavailable") from exc
        if "text/html" not in response.headers.get("content-type", ""):
            raise ConnectorUnavailable("The source did not return an HTML page")
        if len(response.content) > max_bytes:
            raise ConnectorUnavailable("The source page is larger than the configured response limit")
        items = extract_reviews_from_html(response.text, str(response.url), self.source)
        if last_seen_item_id:
            items = items[: next((i for i, item in enumerate(items) if item.external_id == last_seen_item_id), len(items))]
        return items


def normalize_twogis_business_url(page_url: str) -> str:
    """Return the exact reviews URL and reject search pages without a firm ID."""
    safe_url = _safe_public_url(page_url)
    parsed = urlparse(safe_url)
    hostname = (parsed.hostname or "").lower()
    if not (hostname.startswith("2gis.") or ".2gis." in hostname):
        raise ConnectorUnavailable("2GIS source must use a 2gis business page URL")
    firm_match = re.search(r"/firm/(\d+)(?:/|$)", parsed.path)
    parts = [part for part in parsed.path.split("/") if part]
    if not firm_match or not parts:
        raise ConnectorUnavailable(
            "This 2GIS URL is incomplete. Open the exact company card and copy a link containing /firm/<numeric company ID>."
        )
    city = parts[0]
    return parsed._replace(path=f"/{city}/firm/{firm_match.group(1)}/tab/reviews", query="", fragment="").geturl()


class TwoGisPlaywrightConnector(BaseConnector):
    """Collect 2GIS reviews rendered in a real browser without bypassing verification pages."""

    source = "2gis"
    connection_type = ConnectionType.monitored
    collection_method = "playwright"

    def __init__(self, page_url: str) -> None:
        self.page_url = normalize_twogis_business_url(page_url)

    async def fetch_latest(self, last_seen_item_id: str | None = None) -> list[RawItem]:
        from typing import cast

        from app.scrapers.fallback import ApifyProvider, FallbackPipeline, PlaywrightProvider, ScrapflyProvider
        from app.scrapers.maps_playwright import TwoGisScraper
        from app.scrapers.proxy_pool import ProxyPool
        from app.scrapers.storage import SupabaseRawReviewStore

        proxies = [value for value in os.getenv("WEBSHARE_PROXY_URLS", "").split(",") if value.strip()]
        proxy_pool = ProxyPool(proxies)
        pipeline = FallbackPipeline(
            "2gis",
            [
                PlaywrightProvider("2gis", lambda: TwoGisScraper(cast(SupabaseRawReviewStore, None), proxy_pool)),
                ScrapflyProvider("2gis", os.getenv("SCRAPFLY_API_KEY")),
                ApifyProvider(
                    "2gis",
                    os.getenv("APIFY_API_TOKEN"),
                    os.getenv("APIFY_2GIS_ACTOR_ID"),
                    os.getenv("APIFY_2GIS_INPUT_JSON"),
                ),
            ],
        )
        scraped, provider, failures = await pipeline.collect_items(self.page_url, limit=100)
        if not scraped or not provider:
            detail = "; ".join(f"{row['provider']}: {row['error']}" for row in failures)
            raise ConnectorUnavailable(f"2GIS collection failed through every configured method. {detail}")
        self.collection_method = provider
        items = [RawItem(
            source=self.source,
            source_type=MentionType.review,
            external_id=item.stable_id(),
            external_url=item.url,
            author_name=None if item.author == "Unknown" else item.author,
            text=item.text_content,
            rating=item.rating,
            published_at=item.published_at,
            metadata={**item.metadata, "language": item.language, "collected_by": provider, "fallbacks": failures},
        ) for item in scraped]
        if last_seen_item_id:
            items = items[:next((index for index, item in enumerate(items) if item.external_id == last_seen_item_id), len(items))]
        return items


class InstagramFallbackConnector(BaseConnector):
    """Collect public Instagram comments through the configured provider cascade."""

    source = "instagram"
    connection_type = ConnectionType.monitored
    collection_method = "playwright"

    def __init__(self, page_url: str) -> None:
        from app.scrapers.fallback import instagram_profile_handle

        self.page_url = _safe_public_url(page_url)
        host = (urlparse(self.page_url).hostname or "").lower()
        if host not in {"instagram.com", "www.instagram.com"}:
            raise ConnectorUnavailable("Instagram collection requires an instagram.com profile, post or reel URL")
        self.is_profile = bool(instagram_profile_handle(self.page_url))
        if not self.is_profile and not re.match(r"^/(?:p|reel)/[^/]+/?", urlparse(self.page_url).path):
            raise ConnectorUnavailable("Use an Instagram profile, post or reel URL")

    async def fetch_latest(self, last_seen_item_id: str | None = None) -> list[RawItem]:
        from typing import cast

        from app.scrapers.fallback import ApifyProvider, FallbackPipeline, PlaywrightProvider, SociaVaultInstagramProfileProvider, SociaVaultProvider, SocialCrawlProvider
        from app.scrapers.proxy_pool import ProxyPool
        from app.scrapers.social_playwright import InstagramScraper
        from app.scrapers.storage import SupabaseRawReviewStore

        proxies = [value for value in os.getenv("WEBSHARE_PROXY_URLS", "").split(",") if value.strip()]
        proxy_pool = ProxyPool(proxies)
        apify = ApifyProvider(
            "instagram",
            os.getenv("APIFY_API_TOKEN"),
            os.getenv("APIFY_INSTAGRAM_ACTOR_ID"),
            os.getenv("APIFY_INSTAGRAM_INPUT_JSON"),
        )
        playwright = PlaywrightProvider(
                    "instagram",
                    lambda: InstagramScraper(
                        cast(SupabaseRawReviewStore, None),
                        proxy_pool,
                        None,
                    ),
                )
        providers = (
            [SociaVaultInstagramProfileProvider(os.getenv("SOCIAVAULT_API_KEY")), apify, playwright]
            if self.is_profile else [
                SociaVaultProvider(os.getenv("SOCIAVAULT_API_KEY")),
                SocialCrawlProvider(os.getenv("SOCIALCRAWL_API_KEY")),
                apify,
                playwright,
            ]
        )
        pipeline = FallbackPipeline("instagram", providers)
        scraped, provider, failures = await pipeline.collect_items(self.page_url, limit=500)
        if not scraped or not provider:
            detail = "; ".join(f"{row['provider']}: {row['error']}" for row in failures)
            raise ConnectorUnavailable(f"Instagram collection failed through every configured method. {detail}")
        self.collection_method = provider
        items = [RawItem(
            source=self.source,
            source_type=MentionType.social_comment,
            external_id=item.stable_id(),
            external_url=item.url,
            author_name=None if item.author == "Unknown" else item.author,
            text=item.text_content,
            rating=item.rating,
            published_at=item.published_at,
            metadata={**item.metadata, "language": item.language, "collected_by": provider, "fallbacks": failures},
        ) for item in scraped]
        if last_seen_item_id:
            items = items[:next((index for index, item in enumerate(items) if item.external_id == last_seen_item_id), len(items))]
        return items


class ModularScraperConnector(BaseConnector):
    """Expose the modular scraper implementations through the product source API."""

    connection_type = ConnectionType.monitored
    collection_method = "playwright"

    def __init__(self, source: str, page_url: str, scraper_factory: Any, source_type: MentionType) -> None:
        self.source = source
        self.page_url = _safe_public_url(page_url)
        self.scraper_factory = scraper_factory
        self.source_type = source_type

    async def fetch_latest(self, last_seen_item_id: str | None = None) -> list[RawItem]:
        if os.getenv("VERCEL"):
            raise ConnectorUnavailable("Playwright browser is unavailable in the Vercel runtime")
        scraper = self.scraper_factory()
        try:
            await scraper.connect()
            scraped = scraper.clean_data(await scraper.scrape(self.page_url, 100))
        except Exception as exc:
            raise ConnectorUnavailable(str(exc)) from exc
        finally:
            await scraper.close()
        items = [RawItem(
            source=self.source,
            source_type=self.source_type,
            external_id=item.stable_id(),
            external_url=item.url,
            author_name=None if item.author == "Unknown" else item.author,
            text=item.text_content,
            rating=item.rating,
            published_at=item.published_at,
            metadata={**item.metadata, "language": item.language, "collected_by": item.collected_by or self.collection_method},
        ) for item in scraped]
        if last_seen_item_id:
            items = items[:next((index for index, item in enumerate(items) if item.external_id == last_seen_item_id), len(items))]
        return items


class MapFallbackConnector(BaseConnector):
    """Shared Google/Yandex browser collector with optional provider fallbacks."""

    connection_type = ConnectionType.monitored
    collection_method = "playwright"

    def __init__(self, platform: str, page_url: str) -> None:
        if platform not in {"google_maps", "yandex_maps"}:
            raise ValueError(f"Unsupported map platform: {platform}")
        self.platform = platform
        self.source = platform
        self.page_url = _safe_public_url(page_url)

    async def fetch_latest(self, last_seen_item_id: str | None = None) -> list[RawItem]:
        from typing import cast

        from app.scrapers.fallback import ApifyProvider, FallbackPipeline, PlaywrightProvider, ScrapflyProvider
        from app.scrapers.maps_playwright import GoogleMapsScraper, YandexMapsScraper
        from app.scrapers.proxy_pool import ProxyPool
        from app.scrapers.storage import SupabaseRawReviewStore

        proxies = ProxyPool([value for value in os.getenv("WEBSHARE_PROXY_URLS", "").split(",") if value.strip()])
        scraper_cls = GoogleMapsScraper if self.platform == "google_maps" else YandexMapsScraper
        env_prefix = "GOOGLE_MAPS" if self.platform == "google_maps" else "YANDEX_MAPS"
        pipeline = FallbackPipeline(self.platform, [
            PlaywrightProvider(self.platform, lambda: scraper_cls(cast(SupabaseRawReviewStore, None), proxies)),
            ScrapflyProvider(self.platform, os.getenv("SCRAPFLY_API_KEY")),
            ApifyProvider(
                self.platform,
                os.getenv("APIFY_API_TOKEN"),
                os.getenv(f"APIFY_{env_prefix}_ACTOR_ID"),
                os.getenv(f"APIFY_{env_prefix}_INPUT_JSON"),
            ),
        ])
        scraped, provider, failures = await pipeline.collect_items(self.page_url, limit=100)
        if not scraped or not provider:
            detail = "; ".join(f"{row['provider']}: {row['error']}" for row in failures)
            raise ConnectorUnavailable(f"{self.platform} collection failed through every configured method. {detail}")
        self.collection_method = provider
        items = [RawItem(
            source=self.source,
            source_type=MentionType.review,
            external_id=item.stable_id(),
            external_url=item.url,
            author_name=None if item.author == "Unknown" else item.author,
            text=item.text_content,
            rating=item.rating,
            published_at=item.published_at,
            metadata={**item.metadata, "language": item.language, "collected_by": provider, "fallbacks": failures},
        ) for item in scraped]
        if last_seen_item_id:
            items = items[:next((index for index, item in enumerate(items) if item.external_id == last_seen_item_id), len(items))]
        return items


def extract_youtube_video_ids(html: str) -> list[str]:
    """Return unique public video IDs in the order shown on a channel page."""
    seen: set[str] = set()
    result: list[str] = []
    for video_id in re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html):
        if video_id not in seen:
            seen.add(video_id)
            result.append(video_id)
    return result


def youtube_video_id(value: str) -> str | None:
    parsed = urlparse(value)
    if parsed.hostname in {"youtu.be", "www.youtu.be"}:
        candidate = parsed.path.strip("/").split("/")[0]
    elif parsed.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            from urllib.parse import parse_qs

            candidate = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/shorts/", "/live/")):
            candidate = parsed.path.strip("/").split("/")[1]
        else:
            return None
    else:
        return None
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate or "") else None


class YouTubePublicConnector(BaseConnector):
    """Collect comments from recent public videos, never video titles as mentions."""

    source = "youtube"
    connection_type = ConnectionType.monitored
    collection_method = "public_page"

    def __init__(self, page_url: str) -> None:
        self.page_url = _safe_public_url(page_url)

    async def fetch_latest(self, last_seen_item_id: str | None = None) -> list[RawItem]:
        from typing import cast

        from app.scrapers.fallback import SociaVaultYouTubeProvider
        from app.scrapers.storage import SupabaseRawReviewStore
        from app.scrapers.youtube_api import YouTubeApiScraper

        timeout = float(os.getenv("CRAWLER_TIMEOUT_SECONDS", "20"))
        headers = {"User-Agent": "Mozilla/5.0 SARAP/1.0", "Accept-Language": "ru,en;q=0.8"}
        direct_id = youtube_video_id(self.page_url)
        if direct_id:
            ids = [direct_id]
        else:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, headers=headers) as client:
                response = await _public_get(client, self.page_url)
                response.raise_for_status()
                ids = extract_youtube_video_ids(response.text)
        if not ids:
            raise ConnectorUnavailable("No public videos were found on this YouTube page")

        max_videos = max(1, int(os.getenv("YOUTUBE_MAX_VIDEOS_PER_SYNC", "2")))
        total_limit = max(1, int(os.getenv("YOUTUBE_COMMENTS_PER_SYNC", "100")))
        per_video = max(1, total_limit // min(max_videos, len(ids)))
        api_key = os.getenv("YOUTUBE_API_KEY", "").strip()
        social_provider = SociaVaultYouTubeProvider(os.getenv("SOCIAVAULT_API_KEY"))
        scraped = []
        failures: list[str] = []
        provider_used: str | None = None

        for video_id in ids[:max_videos]:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            video_items = []
            if api_key:
                scraper = YouTubeApiScraper(cast(SupabaseRawReviewStore, None), api_key)
                try:
                    await scraper.connect()
                    api_items = await scraper.scrape(video_id, per_video + 1)
                    video_items = [item for item in api_items if item.metadata.get("kind") == "comment"][:per_video]
                    if video_items:
                        provider_used = "youtube_api"
                except Exception as exc:
                    failures.append(f"youtube_api: {type(exc).__name__}")
                finally:
                    await scraper.close()
            if not video_items and social_provider.configured:
                try:
                    video_items = await social_provider.collect(video_url, per_video)
                    if video_items:
                        provider_used = "sociavault"
                except Exception as exc:
                    failures.append(f"sociavault: {exc}")
            scraped.extend(video_items)
            if len(scraped) >= total_limit:
                break

        if not scraped or not provider_used:
            if not api_key and not social_provider.configured:
                failures.append("YOUTUBE_API_KEY and SOCIAVAULT_API_KEY are empty")
            raise ConnectorUnavailable("YouTube comment collection failed. " + "; ".join(failures))
        self.collection_method = provider_used
        items = [RawItem(
            source=self.source,
            source_type=MentionType.video_comment,
            external_id=item.stable_id(),
            external_url=item.url,
            author_name=None if item.author == "Unknown" else item.author,
            text=item.text_content,
            published_at=item.published_at,
            metadata={**item.metadata, "language": item.language, "collected_by": provider_used},
        ) for item in scraped[:total_limit]]
        if last_seen_item_id:
            items = items[:next((index for index, item in enumerate(items) if item.external_id == last_seen_item_id), len(items))]
        return items


class GoogleBusinessReviewsConnector(BaseConnector):
    """Official Google Business Profile review connector for a verified location."""

    source = "google_business"
    connection_type = ConnectionType.official
    collection_method = "api"

    def __init__(self, access_token: str, account_id: str, location_id: str) -> None:
        if not all((access_token, account_id, location_id)):
            raise ConnectorUnavailable("Google Business API credentials are incomplete")
        self.access_token = access_token
        self.account_id = account_id
        self.location_id = location_id

    async def fetch_latest(self, last_seen_item_id: str | None = None) -> list[RawItem]:
        endpoint = f"https://mybusiness.googleapis.com/v4/accounts/{self.account_id}/locations/{self.location_id}/reviews"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with httpx.AsyncClient(timeout=20, headers=headers) as client:
            try:
                response = await client.get(endpoint, params={"pageSize": 50, "orderBy": "updateTime desc"})
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in {401, 403}:
                    raise ConnectorUnavailable("Google Business authorization is invalid or expired; reconnect this source") from exc
                raise ConnectorUnavailable(f"Google Business API returned HTTP {exc.response.status_code}") from exc
            except httpx.HTTPError as exc:
                raise ConnectorUnavailable("Google Business API is currently unavailable") from exc
        items: list[RawItem] = []
        for review in response.json().get("reviews", []):
            review_id = str(review.get("reviewId") or review.get("name") or "")
            if review_id == last_seen_item_id:
                break
            text = str(review.get("comment") or "").strip()
            if not text:
                continue
            star = review.get("starRating")
            rating = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}.get(star, _rating(star))
            items.append(RawItem(source=self.source, source_type=MentionType.review, external_id=review_id, text=text, author_name=_author_name(review.get("reviewer")), rating=rating, published_at=review.get("createTime"), metadata={"collection_method": "official_api"}))
        return items


class InstagramGraphCommentsConnector(BaseConnector):
    """Official Instagram Graph API connector using one workspace's OAuth token."""

    source = "instagram"
    connection_type = ConnectionType.official
    collection_method = "api"

    def __init__(self, access_token: str, instagram_user_id: str | None = None, media_id: str | None = None) -> None:
        if not access_token or not (instagram_user_id or media_id):
            raise ConnectorUnavailable("Instagram OAuth credentials require instagram_user_id or media_id")
        self.access_token = access_token
        self.instagram_user_id = instagram_user_id
        self.media_id = media_id

    async def _get(self, client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> dict[str, Any]:
        version = os.getenv("META_GRAPH_API_VERSION", "v23.0").strip()
        base = os.getenv("META_GRAPH_API_BASE", "https://graph.facebook.com").rstrip("/")
        response = await client.get(f"{base}/{version}/{path.lstrip('/')}", params={**params, "access_token": self.access_token})
        if response.status_code >= 400:
            detail = response.json().get("error", {}).get("message") if response.headers.get("content-type", "").startswith("application/json") else None
            raise ConnectorUnavailable(f"Instagram API rejected the source credential: {detail or response.status_code}")
        return response.json()

    async def fetch_latest(self, last_seen_item_id: str | None = None) -> list[RawItem]:
        async with httpx.AsyncClient(timeout=20) as client:
            media_ids = [self.media_id] if self.media_id else []
            if not media_ids and self.instagram_user_id:
                media = await self._get(client, f"{self.instagram_user_id}/media", {"fields": "id,permalink", "limit": 10})
                media_ids = [str(row["id"]) for row in media.get("data", []) if row.get("id")]
            items: list[RawItem] = []
            for media_id in media_ids:
                comments = await self._get(client, f"{media_id}/comments", {"fields": "id,text,username,timestamp,like_count", "limit": 100})
                for comment in comments.get("data", []):
                    comment_id = str(comment.get("id") or "")
                    if comment_id == last_seen_item_id:
                        return items
                    text = str(comment.get("text") or "").strip()
                    if not comment_id or not text:
                        continue
                    items.append(RawItem(
                        source=self.source,
                        source_type=MentionType.social_comment,
                        external_id=comment_id,
                        author_name=str(comment.get("username") or "").strip() or None,
                        text=text,
                        published_at=comment.get("timestamp"),
                        metadata={"collection_method": "official_api", "media_id": media_id, "likes_count": int(comment.get("like_count") or 0)},
                    ))
        return items


def connector_for(source: dict[str, Any], credentials: dict[str, Any] | None = None) -> BaseConnector:
    """Compatibility entrypoint backed by the unified production registry."""
    from app.collectors.registry import collector_registry

    return collector_registry.resolve(source, credentials)[1]
