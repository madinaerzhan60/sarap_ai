from __future__ import annotations

import hashlib
import os
import re
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import httpx

from app.connectors.base import BaseConnector
from app.models import ConnectionType, MentionType, RawItem


def _text(element: ElementTree.Element | None) -> str:
    return "" if element is None or element.text is None else element.text.strip()


class RssConnector(BaseConnector):
    """Keyless connector for RSS and Atom feeds supplied by the business."""

    source = "rss"
    connection_type = ConnectionType.monitored

    def __init__(self, feed_url: str, source_name: str = "rss") -> None:
        self.feed_url = feed_url
        self.source = source_name

    async def fetch_latest(self, last_seen_item_id: str | None = None) -> list[RawItem]:
        headers = {"User-Agent": os.getenv("CRAWLER_USER_AGENT", "SARAPBot/0.1")}
        timeout = float(os.getenv("CRAWLER_TIMEOUT_SECONDS", "20"))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = await client.get(self.feed_url)
            response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        entries = root.findall(".//item") or root.findall("{*}entry")
        items: list[RawItem] = []
        for entry in entries:
            title = _text(entry.find("title")) or _text(entry.find("{*}title"))
            description = _text(entry.find("description")) or _text(entry.find("{*}summary"))
            link = _text(entry.find("link"))
            if not link:
                atom_link = entry.find("{*}link")
                link = "" if atom_link is None else atom_link.attrib.get("href", "")
            guid = _text(entry.find("guid")) or _text(entry.find("{*}id")) or link
            if not guid:
                guid = hashlib.sha256(f"{title}|{description}".encode()).hexdigest()
            if guid == last_seen_item_id:
                break
            date_text = _text(entry.find("pubDate")) or _text(entry.find("{*}published")) or _text(entry.find("{*}updated"))
            try:
                published = parsedate_to_datetime(date_text) if date_text else None
            except (TypeError, ValueError):
                published = None
            text = re.sub(r"<[^>]+>", " ", f"{title}. {description}")
            items.append(RawItem(source=self.source, source_type=MentionType.news_article, external_id=guid, external_url=link or None, text=text, published_at=published))
        return items


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


class MonitoredPageConnector(BaseConnector):
    """Checks a known public URL; it is not a general-purpose search engine."""

    source = "web_page"
    connection_type = ConnectionType.monitored

    def __init__(self, page_url: str, source_name: str = "web_page") -> None:
        self.page_url = page_url
        self.source = source_name

    async def fetch_latest(self, last_seen_item_id: str | None = None) -> list[RawItem]:
        user_agent = os.getenv("CRAWLER_USER_AGENT", "SARAPBot/0.1")
        timeout = float(os.getenv("CRAWLER_TIMEOUT_SECONDS", "20"))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": user_agent}) as client:
            if os.getenv("CRAWLER_RESPECT_ROBOTS_TXT", "true").lower() == "true":
                robots_url = urljoin(self.page_url, "/robots.txt")
                try:
                    robots = await client.get(robots_url)
                    if robots.status_code == 200:
                        parser = RobotFileParser(robots_url)
                        parser.parse(robots.text.splitlines())
                        if not parser.can_fetch(user_agent, self.page_url):
                            return []
                except httpx.HTTPError:
                    return []
            response = await client.get(self.page_url)
            response.raise_for_status()
        if "text/html" not in response.headers.get("content-type", ""):
            return []
        parser = _VisibleTextParser()
        parser.feed(response.text)
        text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()[:30_000]
        external_id = hashlib.sha256(text.encode()).hexdigest()
        if not text or external_id == last_seen_item_id:
            return []
        return [RawItem(source=self.source, source_type=MentionType.web_page, external_id=external_id, external_url=self.page_url, text=text, metadata={"host": urlparse(self.page_url).hostname})]
