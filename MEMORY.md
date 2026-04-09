# MEMORY.md — TCG Listing Bot

## Current Product Memory

### Identity
- product: `TCG Listing Bot`
- interface: Telegram bot only in Phase 1
- model: multi-seller SaaS
- launch scope: Pokémon + One Piece, EN + JP
- primary channel: `@TCGMarketplaceSingapore`
- claims model: linked discussion comments monitored by bot

### Current Working State
- `/start`, `/help`, `/setup`, `/ping`, and `/list` respond again
- seller setup persists in Supabase
- `/list` now starts as a photo-first flow in DM
- OCR provider is local Tesseract
- identifier-focused OCR now uses an EN-only bottom-left identifier lane first, with JP OCR isolated to broader name text
- local catalog matching works against seeded cards first
- listing posting still requires seller confirmation before posting
- PriceCharting staging import path exists for bulk external catalog ingestion
- Pokémon EN set metadata importer exists from Bulbapedia
- Pokémon EN card catalog importer exists from Pokemon-Card-CSV
- All 172 Pokemon-Card-CSV files now resolve to a set mapping after alias tuning

### Important Constraints
- do not auto-post without explicit seller confirmation
- do not depend on marketplace, escrow, or KYC in Phase 1
- external pricing should degrade gracefully when unavailable
- comment-based claim automation is still pending
- Railway/webhook deployment is still pending for always-on hosting

### Known Gaps
- photo flow currently works best with one clear front image
- live website price references are not fully integrated yet
- raw PriceCharting rows still need a resolver before they can reliably populate `cards`
- Pokémon EN import currently has full set-name resolution, but the bulk importer still needs performance tuning/commit visibility
- OCR for Japanese names is improved but still likely weaker than dedicated hosted vision models
- card identification is still local-catalog and low-volume friendly
- claim monitoring, queue advancement, and SOLD lifecycle are still todo
- seller/buyer reputation and dedicated price history are still todo

### Near-Term Priorities
1. connect live price reference providers
2. support front + back photo intake
3. implement discussion-comment claim handling
4. deploy to Railway with webhook mode
5. add reputation and price-history tables/logic

### Working Rules For Future Tasks
- after any meaningful task, update this file with new current state and next risks
- keep this file concise and factual
- use `TASK_EVALUATIONS.md` for task-by-task review entries
- `TODO.md` now tracks PRD gap status
- `ROADMAP.md` now tracks phased delivery order
