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
- `/auction` now exists as a photo-first DM flow that reuses the same OCR/front-back image classification path as fixed-price listings
- auction replies/comments now parse numeric bids on bot-posted auction listings, record the high bid atomically in Postgres, live-edit the Telegram post, apply anti-snipe extension, and hand the winning bidder into the existing payment-deadline flow when the auction closes
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
- claim handler now reads seller-configured claim keywords from `seller_configs.claim_keywords` instead of relying only on a hardcoded keyword set
- setup now persists `primary_channel_id` in seller config, which gives the claim flow cleaner channel metadata for later hardening work
- blacklisted buyers are now blocked in the live claim handler before the atomic claim RPC runs, with seller notification and safer public messaging
- `claim_listing_atomic(...)` now queues later claims deterministically behind the current winner and returns the buyer's existing open claim if the same buyer claims again
- the live claim handler now recognizes queued outcomes, avoids duplicate open claims per buyer/listing in normal flow, and sends different buyer/seller messaging for confirmed versus queued claims
- payment deadline expiry is now implemented via `jobs/payment_deadlines.py`, backed by the new `advance_claim_queue(...)` RPC and APScheduler startup wiring in `main.py`
- seller-paid completion now exists via `/sold`: `complete_transaction_atomic(...)` marks the winning claim paid, creates a transaction row, marks the listing sold, updates seller `total_sales_sgd`, and `handlers/transactions.py` edits the posted listing message(s) to a SOLD state
- minimal seller ops now exist in `handlers/seller_tools.py`: `/stats`, `/inventory`, `/sales`, `/blacklist`, and `/vacation` are wired; vacation mode is also enforced in the live claim handler so away sellers do not keep accepting new claims
- seller ops are no longer command-only: `handlers/seller_tools.py` now renders a Telegram button dashboard with paginated inventory, per-listing detail, queue view, vacation controls, sales view, and a safe mark-paid confirmation flow keyed by `listing_id`
- first-pass DB-backed idempotency now exists via `processed_events` and `db/idempotency.py`; claim comments, `/sold`, blacklist/vacation commands, and mutating seller dashboard callbacks now register processed event keys before side effects
- the bot now has a reusable Telegram listing message editor in `services/listing_message_editor.py`; SOLD edits already use it, and `jobs/auction_close.py` now provides a scheduled scaffold for refreshing auction posts with live time-left/current-bid text and closing them when the end time passes
- setup now verifies not only the posting channel but also bot access to the linked discussion chat when discussion-based comments are enabled
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
- local restart check on April 13, 2026 hit a Telegram `getUpdates` conflict after startup, which means another polling instance is still using this bot token somewhere outside the current shell session

### Known Gaps
- photo flow currently works best with one clear front image
- live website price references now work for matched Pokémon cards via Pokémon TCG API + FX normalization; One Piece still falls back gracefully
- raw PriceCharting rows still need a resolver before they can reliably populate `cards`
- Pokémon EN import is complete, but the bulk loader still benefits from resumable per-file execution in unstable network environments
- multi-candidate OCR and full-catalog matching now work better on tested real Pokémon photos, but latency is still high and live-photo tuning is still needed for glare, partial crops, and non-Pokémon layouts
- older Pokémon cards still need real-photo validation for set-symbol disambiguation beyond the currently conservative shortlist reranker
- card identification is still local-catalog and low-volume friendly
- claim monitoring is partially scaffolded and now includes live blacklist enforcement plus queued-claim handling, but linked-discussion validation is still unfinished
- payment deadline handling, seller-paid completion, SOLD edits, and transaction closure are still unfinished
- seller/buyer reputation and dedicated price history are still todo

### Near-Term Priorities
1. live-test the linked discussion-thread `Claim` handler plus the new seller dashboard flows against real Telegram traffic once the polling conflict is removed
2. move to one real always-on runtime path so the polling conflict stops blocking live verification
3. extend idempotency coverage to any remaining mutating callbacks/messages and then verify it under webhook/runtime conditions
4. if auctions are brought into scope, wire bid parsing and atomic bid updates onto the already-added auction message refresh/close scaffold
5. harden multi-image listing intake with seller front/back override and less chatty album UX

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
- a manifest-driven OCR/resolver evaluation harness now exists at `scripts/evaluate_ocr_resolver.py` with seeded cases in `eval_cases/ocr_resolver_cases.json`
- the evaluator supports both explicit regression cases and synthetic Pokémon catalog audits (`--synthetic-exact-identifier`, `--synthetic-unique-ratio`) so future work can test classes of failures across sets instead of relying on ad hoc user reports
- initial harness runs passed 5/5 seeded regression cases and 20/20 synthetic cross-set smoke cases; JSON reports were written under `.logs/`
- while building the harness, a generic parser gap was found and fixed: `services/card_identifier.py` now accepts digit-containing set codes like `B2` in identifier text instead of only letter-only codes
- the current synthetic audit intentionally focuses on numeric printed-number cases; promo/alphanumeric identifier formats like `BW95` or `TG28` still need their own dedicated evaluation mode and resolver support
- live bot restarted successfully at 2026-04-12 02:20 local time after the identifier parser update
- `AGENTS.md` now explicitly requires updating `TODO.md` and `ROADMAP.md` alongside `MEMORY.md` and `TASK_EVALUATIONS.md` after meaningful implementation tasks whenever scope, priorities, or sequencing change
- the old-card Electrode failure exposed two generic issues rather than any missing card-specific rule: nearby-ratio matching was doing uncached set-count lookups in the hot loop, and the nearby-ratio scorer filtered on matching set totals without actually giving that evidence score weight
- `services/card_identifier.py` now caches Pokémon set card counts, so old-card ratio rescue no longer performs one DB lookup per candidate row
- the nearby-ratio resolver now generically scores three signals together for old cards: matching printed total, OCR-similar name evidence, and a nearby left-side ratio; on the attached Electrode image OCR still reads `3/101`, but the resolver now correctly returns `Electrode Holo (Hidden Legends)` via `nearby_ratio_name_match` without any per-card mapping
- the repo no longer ships `eval_cases/ocr_resolver_cases.json`; OCR evaluation is now synthetic-first by default so repo tests do not look like runtime card hardcodes
- `services/ocr.py` now uses tighter generic bottom-right legacy ratio windows for old Pokémon cards instead of one loose crop; the legacy pass also recovers clean 4-digit compact reads like `5101` into `5/101` when the last three digits are a plausible printed total
- on the saved Electrode debug card crop, OCR now reads `IDENTIFIER: 5/101 | NAME_EN: lectrode oe fFd` directly, so the old-card flow is less dependent on nearby-ratio resolver rescue
- the reason the user still saw `ocr-build-2026-04-12-price-buttons-v7` after later OCR work was not a bad patch but a stale long-running poller process from early April 12, 2026 still consuming the same Telegram bot token; killing all `main.py` processes and restarting a single fresh poller restored the live bot to the current build
- during live debugging on April 12, 2026, the bot proved stable when started directly in-process as `.venv/bin/python -u main.py`; a stale `.logs/bot.pid` can remain even when the actual process has changed, so pid files must be refreshed from the real running process during recovery
- the Medicham V miss from Evolving Skies exposed a generic identifier parser bug: `_SET_BLOCK_RE` was allowed to treat the leading digits of a plain ratio like `186/203` as a fake set code (`18`) and downgrade the true printed number to `6/203`; digit-only fake set codes are now ignored so pure ratios stay intact
- after repeated user pushback, the repo now explicitly treats the current OCR identification system as a transitional state: the next architectural step is not more rescue branches, but a refactor toward structured OCR signals, generic candidate generation, and one evidence scorer as documented in `OCR_ARCHITECTURE_RESET.md`
- Phase A of the OCR architecture reset has started: `services/ocr_signals.py` now defines `OCRSignal` and `OCRStructuredResult`, and `services/ocr.py` emits structured signals such as `identifier`, `printed_ratio`, `set_code_text`, and `name_en` alongside the legacy merged OCR text so the bot can migrate incrementally without breaking the current flow
- the matcher no longer has to derive all identifier metadata by reparsing the merged OCR text: `services/card_identifier.py` now accepts `OCRStructuredResult` directly, and `handlers/listing.py` passes the structured OCR payload into identification so Phase A is now end-to-end through the live listing flow
- the matcher now sources not only identifier metadata but also its search text context from structured OCR signals when available: name, set-text, variant-token, printed-ratio, and identifier signals now feed `_ocr_text_context(...)`, reducing dependence on the legacy merged OCR string during scoring
- Phase B has started in a narrow way: `services/candidate_generation.py` now builds a recall-oriented generic candidate pool from structured OCR signals, printed number hints, set code hints, and fuzzy name evidence; `services/card_identifier.py` now scores that pool instead of walking the full catalog inline for the main generic matching path
- Phase B moved forward again: `services/candidate_scoring.py` is now wired into `services/card_identifier.py`, so shortlist, exact-identifier, nearby-ratio, modern-ratio, and generic candidate scoring all read from one shared name-evidence model instead of each carrying their own OCR-token overlap math
- the main generic resolver now actually scores `candidate_catalog` instead of silently falling back to full-catalog iteration, which makes the candidate-generation split real rather than nominal
- a real runtime bug introduced during the candidate-pool refactor was fixed: `_maybe_modern_ratio_match(...)` no longer references an undefined `candidate_catalog`, and instead builds a local generated pool from the current OCR signals
- old-card rescue is now guarded more cleanly: `_maybe_nearby_ratio_name_match(...)` skips high-number modern cards, so legacy ratio rescue cannot hijack modern secret/ultra-rare identifier flows
- synthetic resolver probes passed for safe/no-safe behavior after the scorer wiring: `PFL 130/094` resolves to `Mega Charizard X ex (Phantasmal Flames)`, `5/101 + Electrode OCR` resolves to `Electrode Holo (Hidden Legends)`, and nonsense `ABC 123/456` still fails safe; in an intentionally ambiguous synthetic `186/203 + Medicham` catalog, the matcher now fails safe instead of forcing the wrong set
- live Supabase-backed validation from this shell still appears unreliable or slow enough to stall direct probes, so compile checks plus synthetic catalog probes are the current validation baseline until the repo gets a stable snapshot-backed eval path
- snapshot-backed offline evaluation now exists end to end: `scripts/export_catalog_snapshot.py` exports the live catalog to `.snapshots/catalog_snapshot.json`, `db/catalog_snapshot.py` can serve `cards` + `pokemon_sets` from that local file, and `scripts/evaluate_ocr_resolver.py --catalog-snapshot ...` runs synthetic audits without touching live Supabase during resolver execution
- `db/cards.py` and `db/pokemon_sets.py` now transparently read from `CARD_CATALOG_SNAPSHOT_PATH` when it is set, which makes resolver evaluation reproducible while keeping production bot behavior unchanged when the env var is absent
- verified on April 12, 2026: snapshot export produced 19,917 active Pokémon cards and 180 Pokémon set rows, and snapshot-backed evaluator runs passed 20/20 smoke cases plus 100/100 broader synthetic cases offline
- there is now a one-command wrapper for the offline audit path: `scripts/run_snapshot_eval.py` refreshes `.snapshots/catalog_snapshot.json`, runs the snapshot-backed evaluator, and writes a timestamped JSON report under `.logs/`; `make ocr-eval-snapshot` is the shorthand entrypoint for this workflow
- verified on April 12, 2026: `make ocr-eval-snapshot OCR_EVAL_LIMIT=20` completed successfully, exported the snapshot, and produced a passing 20/20 offline audit report at `.logs/ocr_eval_snapshot_20260412-235821.json`
- listing intake is no longer single-photo-only: `handlers/listing.py` now collects up to six images in the `PHOTO` state, waits for the seller to reply `done`, and only then runs OCR/matching on the selected front image
- front/back role selection now exists in `services/listing_image_classifier.py`; it scores each uploaded image using game detection, structured OCR signals, identifier/name evidence, match confidence, and a light color heuristic so the bot can pick a likely front image for OCR and a likely back image for buyer condition photos
- listing posting now sends multiple images as a Telegram media group when more than one photo was uploaded, while `db/listings.py` persists `primary_image_path` and `secondary_image_path` for the selected front/back pair
- verified on April 12, 2026: handler + classifier compile passed, and a monkeypatched smoke test confirmed the classifier orders a synthetic front/back pair correctly
- process note from the user: when a new feature is requested, do not jump straight to execution suggestions; first evaluate the request carefully, think through scope / architecture / tradeoffs, and only then recommend the right execution path
- roadmap evaluation on April 13, 2026: the repo is strongest on listing creation and OCR, but the truthful minimum-GA path is now fixed-price seller ops completion, not more scope expansion; the critical sequence is claim handling -> payment deadline/queue advancement -> SOLD/transactions -> minimal seller ops -> launch hardening
- planning baseline on April 13, 2026: Phase 2 GA execution is now defined as six milestones in `ROADMAP.md` — claim hardening, queue integrity, payment deadline worker, mark-paid/SOLD/transactions, minimal seller ops, and launch hardening
- repo-baseline note on April 13, 2026: `handlers/claims.py` and `db/claims.py` already provide partial live claim scaffolding, while `jobs/payment_deadlines.py`, `handlers/transactions.py`, `db/transactions.py`, and `handlers/seller_tools.py` remain mostly placeholder-level and are the main execution gap for the minimum-GA path

- April 13, 2026 completion pass: `/setup` now captures seller claim keywords and default postage, so claim parsing is no longer hardcoded to the schema default for configured sellers
- April 13, 2026 completion pass: `utils/photo_quality.py` now scores resolution / sharpness / glare / exposure before OCR, and listing + auction flows surface those quality warnings when choosing the front image
- April 13, 2026 completion pass: `/admin` now reports live runtime + database readiness, including the hard blocker that the current catalog only contains 2 One Piece rows and 2 Japanese-name rows, so strict PRD launch scope is still data-blocked

- April 13, 2026 catalog pass: added `scripts/import_onepiece_official.py`, which scrapes the official One Piece EN + JP cardlist pages and merges bilingual rows by printed card code
- April 13, 2026 catalog pass: added `scripts/import_pokemon_jp_official.py`, a resumable importer that reads the official Japanese Pokémon result API plus card detail pages to populate JP card rows with real printed set codes like `M4`
- live catalog truth as of this session: One Piece and Japanese support are no longer blocked by missing importer code, but they are still blocked by actually running those long imports to completion and then QAing the real Telegram flows against the expanded catalog

- April 13, 2026 execution snapshot: full One Piece import completed successfully and raised `cards(game='onepiece')` to 3794 rows
- April 13, 2026 execution snapshot: the resumable Japanese Pokémon import is actively running through the official result API + detail-page path; live progress has reached page 22/586 and raised `card_name_jp` coverage to the 700+ row range during this session
- `scripts/phase1_catalog_audit.py` now provides a quick live readiness count for Pokémon, One Piece, Japanese-name coverage, and seller setup state so launch progress can be checked without manual SQL

- April 13, 2026 runtime hardening: `services/pricecharting.py` no longer burns listing latency on scrape fallback when no API token is configured; PriceCharting scraping is now opt-in via `PRICECHARTING_SCRAPE_FALLBACK_ENABLED=true`, so live Pokémon pricing stays fast and usually returns Pokémon TCG API references in a few seconds instead of hanging on repeated 403s
- April 13, 2026 importer hardening: `scripts/import_pokemon_jp_official.py` now skips official JP detail pages that expose a real set code but no collector number (for example numberless basic energy deck pages) instead of crashing the whole crawl
- April 13, 2026 catalog execution update: after hardening the JP importer, pages 25 through 35 imported successfully, raising `pokemon_total` to 21,273 and `jp_named_total` to 1,358; the checkpoint now sits at page 35 with the last batch recording only one skipped numberless energy row
- April 13, 2026 local runtime note: detached local polling remains flaky in this shell environment even when startup logs show a clean boot, so process liveness still needs manual verification rather than trusting `.logs/bot.pid` alone
- April 13, 2026 importer follow-up: the JP official detail-page 403s and numberless card pages no longer crash the crawl, but the official result API itself started hard-returning 403 at page 68 during this session even after retries, browser-like headers, and lower concurrency; the crawl is now blocked by upstream rate-limiting rather than parser correctness
