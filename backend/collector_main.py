from __future__ import annotations

import asyncio
import json
import logging
import os

from dotenv import load_dotenv

from app.scrapers.maps_playwright import GoogleMapsScraper, TwoGisScraper, YandexMapsScraper
from app.scrapers.fallback import (
    ApifyProvider,
    FallbackPipeline,
    PlaywrightProvider,
    ScrapflyProvider,
    SociaVaultProvider,
    SocialCrawlProvider,
)
from app.scrapers.news_crawler import NewsForumCrawler
from app.scrapers.orchestrator import ScrapeJob, ScrapeOrchestrator
from app.scrapers.proxy_pool import ProxyPool
from app.scrapers.registry import ScraperRegistry
from app.scrapers.social_playwright import InstagramScraper, ThreadsScraper, TikTokScraper
from app.scrapers.storage import SupabaseRawReviewStore
from app.scrapers.telegram_api import TelegramScraper
from app.scrapers.youtube_api import YouTubeApiScraper


def build_registry(
    store: SupabaseRawReviewStore | None = None,
    proxies: ProxyPool | None = None,
) -> ScraperRegistry:
    store = store or SupabaseRawReviewStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"], os.environ["SCRAPER_BUSINESS_ID"])
    proxies = proxies or ProxyPool([value for value in os.getenv("WEBSHARE_PROXY_URLS", "").split(",") if value.strip()])
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


def build_fallback_pipelines(store: SupabaseRawReviewStore, proxies: ProxyPool) -> dict[str, FallbackPipeline]:
    return {
        "2gis": FallbackPipeline(
            "2gis",
            [
                PlaywrightProvider("2gis", lambda: TwoGisScraper(store, proxies)),
                ScrapflyProvider("2gis", os.getenv("SCRAPFLY_API_KEY")),
                ApifyProvider(
                    "2gis",
                    os.getenv("APIFY_API_TOKEN"),
                    os.getenv("APIFY_2GIS_ACTOR_ID"),
                    os.getenv("APIFY_2GIS_INPUT_JSON"),
                ),
            ],
            store,
        ),
        "instagram": FallbackPipeline(
            "instagram",
            [
                PlaywrightProvider(
                    "instagram",
                    lambda: InstagramScraper(store, proxies, os.getenv("INSTAGRAM_STORAGE_STATE")),
                ),
                SociaVaultProvider(os.getenv("SOCIAVAULT_API_KEY")),
                SocialCrawlProvider(os.getenv("SOCIALCRAWL_API_KEY")),
                ApifyProvider(
                    "instagram",
                    os.getenv("APIFY_API_TOKEN"),
                    os.getenv("APIFY_INSTAGRAM_ACTOR_ID"),
                    os.getenv("APIFY_INSTAGRAM_INPUT_JSON"),
                ),
            ],
            store,
        ),
    }


async def main() -> None:
    load_dotenv()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    raw_jobs = json.loads(os.getenv("SCRAPER_JOBS_JSON", "[]"))
    if not raw_jobs:
        raise RuntimeError('SCRAPER_JOBS_JSON must contain jobs, for example [{"source":"2gis","query":"https://...","limit":20}]')
    store = SupabaseRawReviewStore(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"], os.environ["SCRAPER_BUSINESS_ID"])
    proxies = ProxyPool([value for value in os.getenv("WEBSHARE_PROXY_URLS", "").split(",") if value.strip()])
    pipelines = build_fallback_pipelines(store, proxies)
    registry = build_registry(store, proxies)
    fallback_jobs = [row for row in raw_jobs if row["source"].casefold() in pipelines]
    regular_jobs = [row for row in raw_jobs if row["source"].casefold() not in pipelines]
    semaphore = asyncio.Semaphore(int(os.getenv("SCRAPER_MAX_PARALLEL", "3")))

    async def run_fallback(row: dict[str, object]) -> dict[str, object]:
        source = str(row["source"]).casefold()
        async with semaphore:
            try:
                return await pipelines[source].collect_data(str(row["query"]), int(row.get("limit", 10_000)))
            except Exception as exc:
                logging.getLogger("sarap.fallback").exception("Fallback job %s failed", source)
                return {"platform": source, "status": "error", "error": str(exc), "collected": 0, "saved": 0}

    fallback_results = await asyncio.gather(*(run_fallback(row) for row in fallback_jobs))
    jobs = [ScrapeJob(registry.create(row["source"]), row["query"], int(row.get("limit", 50))) for row in regular_jobs]
    regular_results = await ScrapeOrchestrator(max_parallel_sources=int(os.getenv("SCRAPER_MAX_PARALLEL", "3"))).run(jobs)
    results = [*fallback_results, *regular_results]
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
