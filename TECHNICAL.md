# TECHNICAL.md — TCG Listing Bot

## Tech Stack, Architecture, and Environment

## 1. Stack Decisions

### Why Python
- strong OCR and scraping ecosystem
- mature Telegram bot tooling
- good fit for async services and background jobs

### Why `python-telegram-bot`
- async-first architecture
- mature handler model
- supports webhook-based production deployment

### Why Supabase
- managed Postgres
- storage support
- practical backend for a small SaaS team
- supports SQL functions / RPC for atomic workflows

### Why Railway
- simple deploy model
- easy environment management
- suitable for webhook + worker split in early stages

## 2. Recommended Architecture

### Services
- `bot-web`: receives Telegram webhooks and handles user interactions
- `bot-worker`: runs APScheduler jobs for deadlines, auctions, scheduled posts, and retries

### Data backend
- Supabase Postgres is the source of truth
- Supabase Storage stores uploaded card images
- Postgres functions / RPC calls handle atomic state transitions

### Integration boundaries
- `services/ocr.py`
- support pluggable OCR providers, defaulting to local Tesseract before Google Vision
- `services/card_identifier.py`
- `services/price_lookup.py`
- `services/image_storage.py`
- `services/exchange_rates.py`

## 3. Claim Detection Architecture

Important correction from the draft docs:
- Telegram claim detection must come from Telegram updates for comments/replies on bot-posted
  listing messages.
- Supabase Realtime may be used for internal app events later, but it is not the source of truth
  for Telegram comments.

Required assumptions:
- the bot must have the right permissions in the posting channel
- if channel comments are discussion-group based, the bot must also receive the relevant reply
  updates there
- claim locking must be atomic in the database

## 4. Game Support Model

Phase 1 ships with:
- `pokemon`
- `onepiece`

Each game should be encapsulated behind a small adapter boundary:
- parsing OCR hints
- resolving canonical card identity
- normalizing title, set, number, and variant output
- choosing preferred price sources

## 5. Suggested Project Structure

```text
.
├── AGENTS.md
├── PRD.md
├── TECHNICAL.md
├── DATABASE.md
├── BOT_FLOWS.md
├── FEATURES.md
├── API.md
├── main.py
├── config.py
├── requirements.txt
├── .env.example
├── handlers/
├── db/
├── services/
├── jobs/
├── utils/
├── migrations/
└── scripts/
```

## 6. Runtime Modules

### `handlers/`
- `start.py`
- `setup.py`
- `listing.py`
- `claims.py`
- `auctions.py`
- `transactions.py`
- `seller_tools.py`
- `admin.py`

### `db/`
- `client.py`
- `sellers.py`
- `seller_configs.py`
- `listings.py`
- `listing_channels.py`
- `claims.py`
- `transactions.py`
- `blacklist.py`
- `strikes.py`
- `scheduled_listings.py`
- `rpc.py`

### `services/`
- `ocr.py`
- `card_identifier.py`
- `game_adapters.py`
- `price_lookup.py`
- `tcgplayer.py`
- `pricecharting.py`
- `yuyutei.py`
- `image_storage.py`
- `translator.py`
- `exchange_rates.py`
- `pdf_generator.py`

### `jobs/`
- `scheduler.py`
- `payment_deadlines.py`
- `auction_close.py`
- `scheduled_posts.py`
- `auto_bump.py`
- `price_alerts.py`

## 7. Environment Variables

```bash
TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_URL=

SUPABASE_URL=
SUPABASE_SERVICE_KEY=
SUPABASE_STORAGE_BUCKET=tcg-listing-bot-images

GOOGLE_APPLICATION_CREDENTIALS=./service-account.json

TCGPLAYER_PUBLIC_KEY=
TCGPLAYER_PRIVATE_KEY=

ENVIRONMENT=development
LOG_LEVEL=INFO

DEFAULT_PAYMENT_DEADLINE_HOURS=24
DEFAULT_AUTO_BUMP_DAYS=3
DEFAULT_PRICE_ALERT_THRESHOLD=0.15
MIN_LISTING_PRICE_SGD=0.50
MAX_LISTING_PRICE_SGD=10000

BOT_ADMIN_TELEGRAM_IDS=
DEFAULT_TIMEZONE=Asia/Singapore
```

## 8. Storage Rules

- store original uploaded image objects in Supabase Storage
- persist object path or signed-access metadata in Postgres
- avoid using long-lived public URLs as the sole stored reference

## 9. Reliability Rules

- all webhook handlers must be idempotent for duplicate Telegram deliveries
- all important multi-step states should persist in DB
- background jobs must tolerate restart and rerun safely
- failures in OCR or pricing should degrade to manual correction, not hard failure

## 10. Local Development Notes

- local development may use polling for convenience
- production should use webhooks
- no dev server is required yet because the project currently contains documentation only
