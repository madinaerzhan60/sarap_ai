from __future__ import annotations

import asyncio
from datetime import datetime

from googleapiclient.discovery import build

from app.scrapers.base import BaseScraper
from app.scrapers.models import ScrapedItem
from app.scrapers.storage import SupabaseRawReviewStore


class YouTubeApiScraper(BaseScraper):
    source = "YouTube"

    def __init__(self, storage: SupabaseRawReviewStore, api_key: str) -> None:
        super().__init__(storage)
        if not api_key:
            raise ValueError("YOUTUBE_API_KEY is required")
        self.api_key = api_key
        self.client = None

    async def connect(self) -> None:
        self.client = await asyncio.to_thread(lambda: build("youtube", "v3", developerKey=self.api_key, cache_discovery=False))

    async def scrape(self, query: str, limit: int = 50) -> list[ScrapedItem]:
        if not self.client:
            raise RuntimeError("connect() must run before scrape()")
        video_id = query.split("v=")[-1].split("&")[0] if "v=" in query else query.strip()
        video = await asyncio.to_thread(lambda: self.client.videos().list(part="snippet", id=video_id).execute())
        items: list[ScrapedItem] = []
        if video.get("items"):
            snippet = video["items"][0]["snippet"]
            items.append(ScrapedItem(source=self.source, author=snippet.get("channelTitle", "Unknown"), text_content="\n".join(filter(None, [snippet.get("title"), snippet.get("description")])), published_at=datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00")), language="unknown", external_id=f"video-{video_id}", url=f"https://youtube.com/watch?v={video_id}", metadata={"kind": "video"}))
        token = None
        while len(items) < limit:
            response = await asyncio.to_thread(lambda page_token=token: self.client.commentThreads().list(part="snippet", videoId=video_id, maxResults=min(100, limit - len(items)), pageToken=page_token, textFormat="plainText", order="time").execute())
            for row in response.get("items", []):
                comment = row["snippet"]["topLevelComment"]
                snippet = comment["snippet"]
                items.append(ScrapedItem(source=self.source, author=snippet.get("authorDisplayName", "Unknown"), text_content=snippet["textDisplay"], published_at=datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00")), language="unknown", external_id=comment["id"], url=f"https://youtube.com/watch?v={video_id}&lc={comment['id']}", metadata={"kind": "comment", "likes": snippet.get("likeCount", 0)}))
            token = response.get("nextPageToken")
            if not token:
                break
        return items[:limit]
