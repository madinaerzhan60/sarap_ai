from __future__ import annotations

import asyncio
import json
import logging
import os

from dotenv import load_dotenv

from app.scrapers.maps_playwright import GoogleMapsScraper, TwoGisScraper, YandexMapsScraper
from app.scrapers.news_crawler import NewsForumCrawler
from app.scrapers.orchestrator import ScrapeJob, ScrapeOrchestrator
from app.scrapers.proxy_pool import ProxyPool
from app.scrapers.registry import ScraperRegistry
from app.scrapers.social_playwright import InstagramScraper, ThreadsScraper, TikTokScraper
from app.scrapers.storage import SupabaseRawReviewStore
from app.scrapers.telegram_api import TelegramScraper
from app.scrapers.youtube_api import YouTubeApiScraper


def build_registry() -> ScraperRegistry:
    store = SupabaseRawReviewStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"], os.environ["SCRAPER_BUSINESS_ID"])
    proxies = ProxyPool([value for value in os.getenv("WEBSHARE_PROXY_URLS", "").split(",") if value.strip()])
    registry = ScraperRegistry()
    registry.register("2gis", lambda: TwoGisScraper(store, proxies))
    registry.register("google_maps", lambda: GoogleMapsScraper(store, proxies))
    registry.register("yandex_maps", lambda: YandexMapsScraper(store, proxies))
    registry.register("instagram", lambda: InstagramScraper(store, proxies, os.getenv("INSTAGRAM_STORAGE_STATE")))
    registry.register("threads", lambda: ThreadsScraper(store, proxies, os.getenv("THREADS_STORAGE_STATE")))
    registry.register("tiktok", lambda: TikTokScraper(store, proxies, os.getenv("TIKTOK_STORAGE_STATE")))
    registry.register("telegram", lambda: TelegramScraper(store, int(os.environ["TELEGRAM_API_ID"]), os.environ["TELEGRAM_API_HASH"], os.getenv("TELEGRAM_SESSION", "sarap-telegram")))
    registry.register("youtube", lambda: YouTubeApiScraper(store, os.environ["YOUTUBE_API_KEY"]))
    registry.register("news", lambda: NewsForumCrawler("News", store, proxies))
    registry.register("forum_blog", lambda: NewsForumCrawler("Forum_Blog", store, proxies))
    return registry


async def main() -> None:
    load_dotenv()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    raw_jobs = json.loads(os.getenv("SCRAPER_JOBS_JSON", "[]"))
    if not raw_jobs:
        raise RuntimeError('SCRAPER_JOBS_JSON must contain jobs, for example [{"source":"2gis","query":"https://...","limit":20}]')
    registry = build_registry()
    jobs = [ScrapeJob(registry.create(row["source"]), row["query"], int(row.get("limit", 50))) for row in raw_jobs]
    results = await ScrapeOrchestrator(max_parallel_sources=int(os.getenv("SCRAPER_MAX_PARALLEL", "3"))).run(jobs)
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
