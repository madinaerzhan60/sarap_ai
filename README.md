# SARAP

SARAP is an AI reputation early-warning and intelligence system for businesses in Kazakhstan.

The repository contains a polished, responsive frontend and a FastAPI backend implementing the complete product boundary:

`connect → collect → normalize → deduplicate → analyze → score risk → alert → act`

## What works now

- Landing, login, registration and three-step onboarding
- Supabase accounts with email confirmation, persistent sessions, password recovery and password reset
- A profile and isolated business workspace for each confirmed user
- Responsive Overview, Mentions, Analytics, Alerts, Sources, Discover and Settings pages
- Explicit `Official`, `Monitored`, `Provider` and `Imported` connection modes
- Interactive demo: add a mention, run language/aspect analysis, calculate risk, ignore duplicates and create an alert
- Smart Reply suggestions that never send automatically
- FastAPI endpoints for ingestion, sources, polling and discovery
- Durable Supabase persistence for mentions, AI analysis, aspects, risk scores, alerts, discoveries and source state
- Server-protected `/admin` console for workspaces, connector health, AI usage, feature flags, global settings and audit history
- Hybrid source collection: official API when configured, focused scraper fallback for customer-supplied public URLs
- Replaceable connector and web-search interfaces
- Kazakh, Russian, English and mixed KZ/RU analysis with a Groq → Gemini cascade and deterministic local fallback
- Deterministic risk engine with evidence
- Telegram Bot API adapter
- Supabase/PostgreSQL schema, indexes and Row Level Security policies
- Lightweight in-process job queue and adaptive polling policy

The UI uses realistic local demo data when credentials are unavailable. It never labels polling as real-time and never pretends that a stub is connected.

## Run locally

From `sarap.ai/backend`:

```bash
python3 -m uvicorn app.main:app --reload --port 8000
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000). The frontend also works by opening `frontend/index.html` directly.

Run tests:

```bash
PYTHONPATH=. python3 -m pytest
```

## Demo flow

1. Select **View demo** on the landing page.
2. Open the preconfigured sample workspace and optionally add a monitored source.
3. Open **Mentions** and choose **Add mention**.
4. Paste `Кофе күшті, бірақ кассир қыз өте дөрекі екен.` and choose a low rating.
5. SARAP normalizes the item, detects mixed KZ/RU, extracts Product and Staff aspects, calculates risk and creates an alert when the score crosses the threshold.
6. Add the same text again to see deduplication.
7. Open **Discover** and run a web scan to see query fan-out and relevance-filtered demo results.

## Supabase

1. Create a Supabase project.
2. For a new project, run `supabase/schema.sql`, then `supabase/migrations/20260917_product_admin.sql` in the SQL editor. For an existing SARAP database, run `supabase/migrations/20260917_auth_accounts.sql` and then `supabase/migrations/20260917_product_admin.sql` once.
3. In **Authentication → Providers → Email**, enable Email and **Confirm email**.
4. In **Authentication → URL Configuration**, set the local Site URL to `http://127.0.0.1:8000` and add `http://127.0.0.1:8000/` to Redirect URLs. Add the deployed HTTPS address before launch.
5. Put the project URL and anon key in `backend/.env`. The anon key is browser-safe only with Row Level Security enabled. Never put the service-role key in the frontend.
6. For reliable customer email delivery, configure custom SMTP in Supabase before launch. The built-in sender is sufficient only for initial setup and has delivery limits.

Create a confirmed platform admin and a clean confirmed test account after the migrations:

```bash
SARAP_ADMIN_EMAIL=admin@example.com SARAP_TEST_EMAIL=test@example.com python3 scripts/create_accounts.py
```

The script requires `SUPABASE_SERVICE_ROLE_KEY`, generates strong one-time passwords, gives only the admin account the platform role, and deliberately leaves the test account without a workspace so onboarding starts cleanly.

When served through FastAPI, the frontend reads the browser-safe Supabase URL and anon key from `/api/public-config`; secrets remain server-side. Registration creates a Supabase Auth user, waits for email confirmation, and then creates the user's profile, business membership, aliases and source connections. A standalone file can show the explicit demo workspace but does not create fake accounts.

## Integration boundaries

- `backend/app/connectors/base.py`: common connector contract
- `backend/app/connectors/demo.py`: monitored 2GIS demo and official Google stub
- `backend/app/connectors/search.py`: pluggable search provider and query fan-out
- `backend/app/connectors/feeds.py`: free RSS/Atom and robots-aware monitored-page connectors
- `backend/app/connectors/reviews.py`: official Google reviews plus structured-data scraper fallback and connector selection
- `backend/app/services/normalization.py`: canonical text and content hashing
- `backend/app/services/ai.py`: cheap-first structured demo classifier
- `backend/app/services/llm.py`: Groq fast pass and Gemini strong-model escalation
- `backend/app/services/risk.py`: explainable 0–100 risk score
- `backend/app/services/polling.py`: adaptive near-real-time schedule
- `backend/app/services/telegram.py`: Telegram alert formatter and sender
- `backend/app/workers.py`: lightweight in-process job queue
- `backend/app/security.py`: Supabase session verification and workspace membership checks

`collection_mode=auto` prefers a configured official connector and otherwise uses the customer-supplied public URL. `api` requires an official connector; `scraper` forces the focused collector. The scraper reads JSON-LD or schema.org review markup, respects robots.txt by default, applies response limits, and does not bypass authentication, CAPTCHA or blocking. A source that disallows collection returns a clear 409 response instead of silently fabricating data.

Example source request:

```json
{
  "business_id": "00000000-0000-0000-0000-000000000000",
  "source": "2GIS",
  "connection_type": "monitored",
  "collection_mode": "auto",
  "source_url": "https://2gis.kz/almaty/firm/.../tab/reviews"
}
```

## Production checklist

- Add `GROQ_API_KEY` and `GEMINI_API_KEY`; keep the local classifier as a resilient fallback and build a versioned evaluation set.
- Move scheduled collection from the in-process queue to a durable Postgres-backed worker before running multiple backend instances.
- Add real Google/Meta OAuth callbacks and webhook signature validation.
- Select a licensed review source for 2GIS/Yandex. Discover uses free GDELT, RSS/Atom and monitored pages; Common Crawl is available for historical URL lookup.
- Move the in-process queue to a durable lightweight worker such as a Postgres-backed queue.
- Add rate limiting, audit logs, error monitoring and backup/retention jobs.
- Configure the shared bot with `TELEGRAM_BOT_TOKEN`. Store each business or user's `chat_id` in `telegram_connections`, not in `.env`.

## Design decisions

The original SARAP colors, typography, glass treatment and sieve/radar idea are preserved. Glass is concentrated in navigation, summaries and high-value cards so the interface stays calm. Teal means safe/connected/positive; amber means warning/attention. The SVG mark combines a filtered signal path with a detected signal dot and works as both wordmark companion and favicon.
