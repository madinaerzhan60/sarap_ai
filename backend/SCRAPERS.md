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
    ├── orchestrator.py               # isolated concurrent jobs
    ├── maps_playwright.py            # 2GIS, Google Maps, Yandex Maps
    ├── social_playwright.py          # Instagram, Threads, TikTok sessions
    ├── telegram_api.py               # official Telegram API via Telethon
    ├── youtube_api.py                # official YouTube Data API v3
    └── news_crawler.py               # news and forum/blog crawling
```

Registered sources: `2gis`, `google_maps`, `yandex_maps`, `instagram`, `threads`, `tiktok`, `telegram`, `youtube`, `news`, `forum_blog`.

## Setup

1. Apply `supabase/migrations/20260918_raw_reviews_collectors.sql` in the Supabase SQL editor.
2. Install Python requirements and the Chromium runtime:

   ```bash
   pip install -r backend/requirements.txt
   playwright install chromium
   ```

3. Copy the collector variables from `backend/.env.example` into `backend/.env`.
4. Put Webshare endpoints in `WEBSHARE_PROXY_URLS` as comma-separated URLs, for example `http://user:password@host:port`.
5. Define jobs as JSON:

   ```dotenv
   SCRAPER_JOBS_JSON=[{"source":"2gis","query":"https://2gis.kz/...","limit":20},{"source":"youtube","query":"VIDEO_ID","limit":50}]
   ```

6. Start the worker from `backend`:

   ```bash
   python collector_main.py
   ```

Each source returns its own `ok` or `error` result. CAPTCHA and verification pages are reported as blocked; the worker does not attempt to bypass them. A later job receives the next proxy from the pool. Official APIs remain the preferred path for Telegram and YouTube.

For Telegram, create and authorize the Telethon session locally once, then mount that session file in the worker. For Instagram, Threads, and TikTok, provide authenticated Playwright storage-state files through their corresponding environment variables.
