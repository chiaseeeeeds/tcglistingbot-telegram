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
- medium-confidence modern Pokémon hits like `Team Rocket's Crobat ex` and `Team Rocket's Nidoking ex` now resolve from printed number + weak or merged name fragments instead of failing or hallucinating the wrong base-set card
- old low-number cards now use a shortlist-style name + printed number fallback, so ambiguous cards like Base/Base Set 2 era reprints can be chosen from top candidates instead of being auto-matched incorrectly
- Pokémon set metadata now includes Bulbapedia symbol/logo image URLs, and old-card shortlist reranking can use those symbols as a conservative tie-breaker
- symbol matching now looks in the classic right-side set-symbol area and only reorders shortlist candidates when the symbol evidence is decisively stronger than the alternatives
- local polling bot startup is now detached again and was relaunched successfully on 2026-04-11 15:08 local time
- OCR latency is materially lower after removing duplicate crop-ranking OCR, short-circuiting decisive candidates, and trimming redundant Tesseract passes; the tested Crobat image now runs in about 10s cold and about 4-5s warm locally
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
- older Pokémon cards still need real-photo validation for set-symbol disambiguation beyond the currently conservative shortlist reranker
- card identification is still local-catalog and low-volume friendly
- claim monitoring, queue advancement, and SOLD lifecycle are still todo
- seller/buyer reputation and dedicated price history are still todo

### Near-Term Priorities
1. live-test the updated OCR heuristics on more real Pokémon photos, especially glare and older cards
2. verify the conservative set-symbol reranker on real Base/Jungle/Fossil/Base Set 2 photos before trusting it to reorder often
3. verify linked discussion-thread `Claim` handling against real Telegram reply/update shapes
4. add a real One Piece external pricing path or provider-backed fallback
5. support front + back photo intake

### Working Rules For Future Tasks
- after any meaningful task, update this file with new current state and next risks
- keep this file concise and factual
- use `TASK_EVALUATIONS.md` for task-by-task review entries
- `TODO.md` now tracks PRD gap status
- `ROADMAP.md` now tracks phased delivery order
- `STATUS.md` now provides a plain-language product readiness checklist

- modern high-number Pokémon resolution is now explicitly tagged with resolver metadata like `pokemon_modern_identifier_first` and exact-id matches use `exact_identifier`, which makes live Telegram debugging much clearer
- `/list` admin replies now include an actual debug block with resolver path, detected identifier, confidence, and top candidate instead of silently computing it and dropping it
- exact local regression checks currently pass for `233/182 + ortNidoKine`, `234/182 + BleamiRocket`, and `PAF 234/091 + Charizard ex`
- local detached bot startup remains unreliable inside the Orchids harness; the bot is currently running in a persistent PTY session instead of a true daemonized background process
- root cause for the live Nidoking miss was unstable Supabase pagination in `db/cards.py`: catalog pages were fetched with `.range(...)` but without a deterministic `.order(...)`, so some processes missed rows like `DRI 233` and produced false `generic_catalog_no_match` results
- `db/cards.py` now paginates active cards with `.order('id')`, which makes full-catalog scans deterministic across processes
- admin debug now exposes resolver build, catalog size, and left-number candidate counts, which helped distinguish OCR issues from catalog/data issues
- OCR failure on the Lucario sample was caused by two generic pipeline issues: the Pokémon name ROI was too high (cropping the frame edge instead of the title strip), and identifier OCR over-trusted a thresholded ROI that turned `179/132` into noisy slash ratios like `797/732`
- `services/ocr.py` now uses lower/wider Pokémon name windows, softer identifier preprocessing, more Tesseract identifier variants (`psm 6/7/11`, raw/autocontrast/contrast/threshold/invert), stricter explicit set-code extraction, and ratio plausibility scoring so plausible collector numbers like `179/132` beat obviously bad ones like `797/732`
- local validation on the attached Mega Lucario photo now returns `IDENTIFIER: 179/132 | NAME_EN: ... Mega Lucario` and resolves to `Mega Lucario ex Illustration Rare (Mega Evolution)` without any image-specific hardcoding
- runtime audit found no literal per-card title hardcodes in OCR or identification paths; the remaining fixed values are generic OCR windows, thresholds, and catalog-scoring heuristics
- user-facing manual identifier examples were normalized from a real card code to the generic placeholder `ABC 123/456` so prompts no longer imply any specific card or set
- generic fallback matching is now stricter when OCR claims a set code that does not match the best catalog hit; weak fuzzy evidence no longer auto-resolves to a random card in that situation
- current live pricing sources are Pokémon TCG API market data plus bot listing history; `services/pricecharting.py` is still just a scaffold and the `cards` table currently has 0 non-null `pricecharting_id` rows, so PriceCharting is not actually wired yet
- `/list` price selection now supports inline Telegram buttons for each returned price reference plus a custom-price button, instead of forcing manual typing every time
- posted listings now persist `pricecharting_price_sgd` and `yuyutei_price_sgd` too when those sources are eventually added back to the lookup pipeline
- Pokémon set-name detection is now alias-aware in a generic way: `services/card_identifier.py` splits canonical set names on separators like em dashes and matches aliases such as `Phantasmal Flames` from catalog metadata instead of relying only on the full `pokemon_sets.set_name`
- local resolver regression checks now also pass for `130/94 + Phantasmal Flames`, which resolves to `Mega Charizard X ex (Phantasmal Flames)` via `exact_identifier` instead of drifting to unrelated `130` cards
- the price reference buttons were present in code but were not attached to the Telegram message; `/list` now sends the inline keyboard so sellers can actually tap a returned source price
- `services/pricecharting.py` now prefers real live lookups: official API token mode when `PRICECHARTING_API_TOKEN` is configured, plus a stronger Scrapling fallback that reads browser HTML from `response.body`/`html_content` instead of the misleading `response.text`
- live PriceCharting scraping still degrades gracefully to no result in this environment because PriceCharting remains Cloudflare-protected without an API token, but the failure path is now real and explicit rather than a scaffold pretending to scrape
- the local polling bot was not actually down because of OCR changes; it was blocked by a stale `.logs/bot.lock`. Clearing the stale lock and restarting brought the bot back up successfully at 2026-04-12 01:52 local time
- Pokémon EN set-name import mapping is now validated against all 172 source CSV files: generic alias-based set mapping resolves every current file with 0 unmapped sets
- alias mapping now keeps the full canonical set name plus the suffix segment after separators like em dashes, which preserves correct umbrella/base mappings such as `Black & White -> BLW` while still resolving child aliases like `Phantasmal Flames -> PFL` and `Ascended Heroes -> ASC`
- generic card resolution now gives stronger weight to exact `name + printed number` evidence, so matches are driven more by card identity and less by broad series context when OCR sees both
- live polling bot was restarted successfully at 2026-04-12 02:01 local time on build `card-identify-2026-04-12-name-number-priority-v3`
- repo-local skill `skills/tcg-catalog-integrity/SKILL.md` now exists to codify the no-hardcoding OCR/catalog rules, generic set-alias policy, pricing-source priority, and approved external references for future work sessions
- the attached gold `Mega Charizard X ex` photo exposed a generic resolver gap: OCR was already reading `130/094`, and the ROI logs even contained `PFLEN`, but the set-code parser was too strict and the resolver still drifted to a loose shortlist instead of trusting the unique ratio evidence
- `services/ocr.py` now recovers known set codes from noisy alphanumeric identifier chunks near the detected ratio, which converts OCR strings like `0 PFLEN F130/094` into `PFL 130/094` without any card-specific rules
- `services/card_identifier.py` now has a generic `unique_print_ratio_match` path: when printed left-number + total uniquely identify a single catalog row, it resolves that card directly instead of wandering to unrelated same-number candidates
- live bot restarted successfully at 2026-04-12 02:07 local time on visible build `ocr-build-2026-04-12-identifier-code-recovery-v9`
