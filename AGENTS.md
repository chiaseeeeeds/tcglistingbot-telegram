# AGENTS.md — TCG Listing Bot

## Master Instructions for Coding AI

## Who You Are Building For

You are building `TCG Listing Bot`, a Telegram-native seller operations bot for trading card sellers in
Singapore and nearby Telegram-first communities.

The product goal for Phase 1 is simple:
- seller sends card photos to the bot
- bot identifies the card and suggests price references
- seller confirms a preview
- bot posts the listing to the seller's Telegram channel
- bot monitors Telegram comments/replies for claims or bids
- bot manages payment deadlines, queue advancement, SOLD edits, and transaction logs

Phase 1 is a bot-first product. There is no required public web frontend.

Before implementing product code, read these files in this order:
1. `AGENTS.md`
2. `PRD.md`
3. `TECHNICAL.md`
4. `DATABASE.md`
5. `BOT_FLOWS.md`
6. `FEATURES.md`
7. `API.md`

## Product Scope Guardrails

Build for these locked decisions unless the user changes them explicitly:
- product model: multi-seller SaaS
- interface: Telegram bot only in Phase 1
- claim model: Telegram comments/replies monitored by the bot
- launch games: `pokemon` and `onepiece`
- launch language/card scope: English and Japanese
- automation mode: mostly automatic, but seller must confirm before posting
- success goal: ship a usable production bot, not just a prototype

## Non-Negotiable Rules

### Code quality
- Never leave silent placeholders in production paths.
- If something is intentionally not implemented, raise a descriptive exception.
- Add type hints on public functions and methods.
- Use structured logging with meaningful context.
- Every network and database boundary must handle failures gracefully.

### Telegram rules
- Use `async`/`await` throughout Telegram handlers and services.
- Always call `query.answer()` in callback handlers before longer work.
- Default parse mode is `HTML`, not Markdown.
- Never DM a Telegram user who has not started the bot.
- Never attempt to edit messages not posted by the bot.
- Only bot-posted listings can participate in automated claims or auctions.

### Data and state rules
- Persist important flow state in the database, not only in memory.
- Do not rely on sequential client-side DB writes for race-sensitive transitions.
- Use database-backed atomic operations for claim locks, queue advancement, bids, and transaction
  completion.
- Store storage object paths or signed-access references, not long-lived public URLs as the source
  of truth.
- Keep seller data isolated. One seller must never see another seller's private data.

### Product rules
- Never auto-post a listing without an explicit seller confirmation step.
- Never confirm a claim unless the listing is still eligible and the lock succeeds atomically.
- Never block the main bot flow on optional features like analytics or WTB matching.
- Treat WTB and marketplace behavior as deferred unless the user asks to bring them into scope.

## Technical Defaults

- Language: Python 3.11+
- Bot framework: `python-telegram-bot`
- Backend: Supabase/Postgres
- Hosting: Railway or equivalent webhook-friendly host
- Background processing: APScheduler-backed worker jobs

## File and Project Structure

Use this structure unless the user requests a different layout:
- `main.py` for app entrypoint
- `config.py` for validated environment loading
- `handlers/` for Telegram handlers
- `db/` for data access and RPC wrappers
- `services/` for OCR, pricing, storage, and external integrations
- `jobs/` for scheduled and retryable background work
- `utils/` for pure helpers
- `migrations/` for SQL files
- `scripts/` for seed/import tools

## How to Approach Features

For each feature:
1. Check user scope against `PRD.md`.
2. Read the relevant flow in `BOT_FLOWS.md`.
3. Confirm the related schema in `DATABASE.md`.
4. Implement data access and atomic operations first.
5. Then implement service logic.
6. Then wire the Telegram handler.
7. Validate the unhappy path before the happy path.

## What the Bot Must Never Do

- Expose one seller's private settings or transaction history to another seller.
- Assume comments are available without channel + discussion-group permissions being verified.
- Assume OCR or price data is correct enough to skip seller confirmation.
- Depend on marketplace payments, escrow, or KYC in Phase 1.
- Hardcode secrets or ship credentials in the repo.

## Coding Style

- `snake_case` for functions and variables
- `PascalCase` for classes
- `UPPER_SNAKE_CASE` for constants
- Use the standard `logging` module, never `print()` in app code
- Keep modules focused and reasonably small

## Delivery Priorities

Build in this order:
1. foundation and config
2. seller onboarding and channel linking
3. listing creation core
4. comment-based claims and payment handling
5. transactions, sold edits, and seller tools
6. auctions
7. launch hardening
8. optional QoL features

## Documentation Priority

If documentation in this repo conflicts with older attached drafts, prefer the repo versions.
These files are the normalized source of truth for implementation.
