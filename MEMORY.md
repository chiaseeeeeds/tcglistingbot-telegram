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
- `/list` OCR now detects and rectifies the card first, then reads Pokémon identifier ROIs relative to the normalized card instead of the raw photo
- OCR debug artifacts are now saved locally for failed tuning sessions
- OCR now aggregates signals across multiple fallback card crops, combining top-name OCR and identifier OCR instead of relying on one crop only
- Catalog reads now page through the full `cards` table, so fuzzy resolution can use all imported Pokémon rows
- `/list` now auto-detects the game instead of asking the seller first, with a current Pokémon-first bias while One Piece support is still maturing
- matcher now fails safe on weak number-only OCR instead of forcing random catalog hits
- Google Vision OCR is now supported as an optional provider when credentials are configured
- Pokémon live price references are now pulled from Pokémon TCG API market data and normalized to SGD with live FX rates
- in-process card catalog reads are now cached, which reduces repeated matcher latency during `/list`
- OCR identifier recovery now votes across noisy compact number blobs like `2344182` and uses stronger lower-left identifier probes
- medium-confidence modern Pokémon hits like `Team Rocket's Crobat ex` and `Team Rocket's Nidoking ex` now resolve from printed number + weak name fragments instead of failing or hallucinating the wrong base-set card
- old low-number cards now use a shortlist-style name + printed number fallback, so ambiguous cards like Base/Base Set 2 era reprints can be chosen from top candidates instead of being auto-matched incorrectly
- basic discussion-thread claim handling is now wired for bot-posted listings, backed by the atomic claim RPC
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
- discussion-thread claim handling now resolves more reply/message shapes, but still needs live discussion-group verification
- Railway/webhook deployment is still pending for always-on hosting
- local Orchids startup now uses `nohup` + `.logs/bot.pid`, which is more stable than the old foreground startup but still not equivalent to proper hosting/supervision

### Known Gaps
- photo flow currently works best with one clear front image
- live website price references now work for matched Pokémon cards via Pokémon TCG API + FX normalization; One Piece still falls back gracefully
- raw PriceCharting rows still need a resolver before they can reliably populate `cards`
- Pokémon EN import is complete, but the bulk loader still benefits from resumable per-file execution in unstable network environments
- multi-candidate OCR and full-catalog matching now work better on tested real Pokémon photos, but latency is still high and live-photo tuning is still needed for glare, partial crops, and non-Pokémon layouts
- card identification is still local-catalog and low-volume friendly
- claim monitoring, queue advancement, and SOLD lifecycle are still todo
- seller/buyer reputation and dedicated price history are still todo

### Near-Term Priorities
1. live-test the updated OCR heuristics on more real Pokémon photos, especially glare and older cards
2. verify linked discussion-thread `Claim` handling against real Telegram reply/update shapes
3. add a real One Piece external pricing path or provider-backed fallback
4. support front + back photo intake
5. improve old-card disambiguation further with set-symbol or layout cues after shortlist fallback

### Working Rules For Future Tasks
- after any meaningful task, update this file with new current state and next risks
- keep this file concise and factual
- use `TASK_EVALUATIONS.md` for task-by-task review entries
- `TODO.md` now tracks PRD gap status
- `ROADMAP.md` now tracks phased delivery order
- `STATUS.md` now provides a plain-language product readiness checklist
