# SARAP collectors

The collector worker is separate from the FastAPI web process so a slow or blocked source cannot stop the product API.

## Architecture

```text
backend/
├── collector_main.py                 # worker entry point and 10-source registry
└── app/scrapers/
    ├── base.py                       # BaseScraper interface and shared cleaning
    ├── models.py                     # normalized ScrapedItem and language detection
    ├── storage.py                    # batched Supabase upsert
    ├── proxy_pool.py                 # authenticated HTTP/SOCKS5 rotation
    ├── retry.py                      # exponential retry with jitter
    ├── fallback.py                   # 2GIS/Instagram provider cascade
    ├── orchestrator.py               # isolated concurrent jobs
    ├── maps_playwright.py            # 2GIS, Google Maps, Yandex Maps
    ├── social_playwright.py          # Instagram, Threads, TikTok sessions
    ├── telegram_api.py               # official Telegram API via Telethon
    ├── youtube_api.py                # official YouTube Data API v3
    └── news_crawler.py               # news and forum/blog crawling
```

Registered sources: `2gis`, `google_maps`, `yandex_maps`, `instagram`, `threads`, `tiktok`, `telegram`, `youtube`, `news`, `forum_blog`.

## Fallback pipeline

The two high-volume sources use ordered provider chains:

```text
2GIS:      Playwright -> Scrapfly -> configured Apify Actor
Instagram: Playwright -> SociaVault -> SocialCrawl -> configured Apify Actor
YouTube:   YouTube Data API -> SociaVault comments
```

The next provider runs when the current one is blocked, returns no records, has no credits, or fails. Network and server failures use exponential retry. Authentication, credit, and empty-result errors move directly to the next provider so the worker does not spend credits repeating a request that cannot succeed.

The product source button collects YouTube comments from a video URL or from the most recent videos found on a channel page. Video titles and descriptions are not stored as customer mentions. When `YOUTUBE_API_KEY` is empty, the connector uses the configured SociaVault comments endpoint.

Outscraper is not in the 2GIS chain because its published API catalogue does not provide a 2GIS reviews endpoint. Its map review product is for Google Maps. `ScrapflyProvider` is the real second path for 2GIS HTML.

Every normalized row records the successful provider in `raw_reviews.collected_by`. Existing logical names map to the requested storage fields as follows:

| Requested name | SARAP column |
| --- | --- |
| platform | `source` |
| source_id | `external_id` |
| author_name | `author` |
| review_text | `text_content` |
| rating | `rating` |
| created_at | `created_at` |
| collected_by | `collected_by` |

The existing names are kept because the dashboard and analysis pipeline already read them.

## Setup

1. Apply `supabase/migrations/20260918_raw_reviews_collectors.sql` in the Supabase SQL editor.
2. Install Python requirements and the Chromium runtime:

   ```bash
   pip install -r backend/requirements.txt
   playwright install chromium
   ```

3. Copy the collector variables from `backend/.env.example` into `backend/.env`.
4. Put Webshare endpoints in `WEBSHARE_PROXY_URLS` as comma-separated URLs, for example `http://user:password@host:port`.
5. Add only the provider keys you want to enable. Missing keys are skipped without stopping the chain. Apify also needs an Actor ID because Store actors can change and different actors accept different inputs.
6. Define jobs as JSON:

   ```dotenv
   SCRAPER_JOBS_JSON=[{"source":"2gis","query":"https://2gis.kz/.../tab/reviews","limit":10000},{"source":"instagram","query":"https://www.instagram.com/p/POST_ID/","limit":10000}]
   ```

7. Start the worker from `backend`:

   ```bash
   python collector_main.py
   ```

Each source returns its own `ok` or `error` result plus the provider that succeeded and failed fallback attempts. CAPTCHA and verification pages are reported as blocked; the worker does not attempt to bypass them. A retry receives the next proxy from the pool. Official APIs remain the preferred path for Telegram and YouTube.

`limit=10000` is a collection ceiling, not a promise that one public URL contains 10,000 visible records. SociaVault and SocialCrawl walk pagination cursors until the limit or the last page. Apify is capped separately by `APIFY_MAX_ITEMS_PER_RUN` to prevent an accidental expensive run. Increase that value deliberately when the Actor and account budget are ready.

For Telegram, create and authorize the Telethon session locally once, then mount that session file in the worker. For Instagram, Threads, and TikTok, provide authenticated Playwright storage-state files through their corresponding environment variables.
