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
- Pokémon EN card catalog import is complete: 172/172 source files, 20,202 staging rows, 19,917 distinct live card identities
- OCR-backed identifier resolution now queries the imported `cards` catalog first by set code + printed number, with manual `PAF 234/091` fallback support in `/list`
- Price references now prefer exact `card_id` listing history before falling back to title-based matching
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
- Pokémon EN import is complete, but the bulk loader still benefits from resumable per-file execution in unstable network environments
- OCR for Japanese names is improved but still likely weaker than dedicated hosted vision models
- card identification is still local-catalog and low-volume friendly
- claim monitoring, queue advancement, and SOLD lifecycle are still todo
- seller/buyer reputation and dedicated price history are still todo

### Near-Term Priorities
1. live-test and tune OCR-to-catalog matching in `/list`
2. add first real exact-card listing history by using the updated `/list` flow
3. connect live external price reference providers
4. support front + back photo intake
5. implement discussion-comment claim handling

### Working Rules For Future Tasks
- after any meaningful task, update this file with new current state and next risks
- keep this file concise and factual
- use `TASK_EVALUATIONS.md` for task-by-task review entries
- `TODO.md` now tracks PRD gap status
- `ROADMAP.md` now tracks phased delivery order
- `STATUS.md` now provides a plain-language product readiness checklist
