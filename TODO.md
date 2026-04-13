# TODO.md — PRD Gap Checklist

## Minimal Phase 1 GA Priority
- For minimum GA, treat fixed-price listing -> claim -> payment -> SOLD -> seller ops as the shipping path.
- Auctions, Japanese Pokémon, and One Piece are important, but they are post-GA fast-follow unless the user explicitly reprioritizes them.

## Status Legend
- DONE = implemented and working at a meaningful level
- PARTIAL = started, but not yet aligned with PRD/GA intent
- TODO = not yet implemented
- BLOCKED = depends on another unfinished system

## 1. Foundation
- DONE: config loading and environment validation
- DONE: Supabase connectivity and migrations
- PARTIAL: single-bot-process guard for polling stability
  - in-repo lock exists, but stale external/manual pollers can still survive across sessions unless all `main.py` processes are cleaned up before restart
- PARTIAL: always-on runtime / deployment
  - still running in local/live session for testing
  - webhook production deployment still TODO

## 2. Seller Onboarding and Setup
- DONE: `/start` seller creation/loading
- DONE: `/setup` basic seller profile capture
- DONE: channel permission verification
- PARTIAL: richer seller settings capture
  - payment methods beyond PayNow
  - template settings
  - claim keywords and default postage are now captured in `/setup`
- TODO: additional approved channels / cross-post configuration

## 3. Listing Creation
- DONE: `/list` starts from Telegram DM
- DONE: photo-first listing flow exists
- DONE: listing intake now accepts multiple photos per listing batch, including front + back capture before OCR begins
- DONE: seller confirmation before posting
- PARTIAL: OCR and identification
  - Pokémon EN catalog pipeline exists
  - current listing flow now classifies likely front/back roles from a photo batch and runs OCR from the selected front image
  - current OCR identification works but still leans too much on branchy resolver heuristics
  - architecture reset is now planned in `OCR_ARCHITECTURE_RESET.md` to move toward structured OCR signals, generic candidate generation, and one evidence scorer
  - Phase A has started: OCR now emits a first structured signal object alongside the legacy merged OCR text
  - the matcher now consumes structured OCR signals for identifier metadata and search text context instead of relying only on reparsing merged text
  - live-photo coverage is still incomplete for foil, glare, and promo/alphanumeric identifiers
- PARTIAL: card match confidence flow
  - best-effort suggestion exists
  - shortlist / fallback UX still needs more refinement for ambiguous cases
- DONE: front + back photo support
- TODO: unsupported media rejection UX
- DONE: image quality checks before OCR
- TODO: One Piece listing creation path
- TODO: Japanese Pokémon catalog support

## 4. Catalog and Recognition
- DONE: Bulbapedia Pokémon EN set importer
- DONE: Pokemon-Card-CSV importer
- DONE: set alias coverage reaches 172/172 file resolution
- DONE: full clean bulk import completion and validation
- DONE: initial OCR/resolver evaluation harness
- PARTIAL: final OCR identifier resolver against imported `cards`
  - numeric printed-number flows are now audited via synthetic catalog coverage without shipping named per-card OCR manifests in-repo
  - current resolver is now partially split into candidate generation + scoring, but the split is still incomplete and broader scoring logic remains inside `services/card_identifier.py`
  - shared name-evidence scoring now lives in `services/candidate_scoring.py`, and the main generic path consumes the generated candidate pool instead of iterating the full catalog
  - legacy nearby-ratio rescue now intentionally skips modern high-number cards so old-card heuristics do not override modern identifier flows
  - live shell validation against the Supabase catalog is still flaky, so synthetic catalog probes remain part of the required regression workflow until a stable local snapshot eval path exists
  - keep guarding against digit-only false set-code parses on plain ratios like `186/203`
  - promo/alphanumeric identifiers like `BW95` and `TG28` still need dedicated support and evaluation coverage
- PARTIAL: fallback prompt for manual `series code + serial code`
- TODO: Japanese catalog source and importer
- TODO: Japanese OCR/resolver evaluation coverage
- TODO: One Piece catalog source and importer
- TODO: broader real-photo evaluation corpus stored in-repo or in a managed eval bucket
- PARTIAL: snapshot-backed offline resolver evaluation now exists via `scripts/export_catalog_snapshot.py` + `scripts/evaluate_ocr_resolver.py --catalog-snapshot ...`, but the repo still needs a routine refresh policy for the snapshot baseline
- DONE: one-command offline snapshot audit exists via `make ocr-eval-snapshot` / `scripts/run_snapshot_eval.py` for routine regression checks

## 5. Price Lookup
- PARTIAL: bot-history fallback price references exist
- PARTIAL: Pokémon live market references via Pokémon TCG API exist
- PARTIAL: PriceCharting lookup path exists in code
  - official token mode is supported
  - scrape fallback is best-effort only
  - current runtime has no `PRICECHARTING_API_TOKEN`, so PriceCharting is not reliably live in the seller flow yet
- PARTIAL: SGD normalization from external sources
- TODO: explicit provider-status reporting in seller/admin pricing output
- TODO: external pricing resilience / partial failure policy
- TODO: pricing display tied to resolved card identity across all supported games

## 6. Posting and Lifecycle
- DONE: listing preview exists
- DONE: seller confirmation before posting exists
- DONE: bot posts listing to configured channel
- DONE: posted Telegram message IDs are stored
- PARTIAL: listing image storage to Supabase exists, but still needs production hardening
- TODO: cross-posted listing message tracking
- TODO: scheduled listing support

## 7. Claims
- PARTIAL: linked-discussion comment monitoring
  - `handlers/claims.py` already watches group/supergroup text replies and tries multiple reply-origin shapes
  - real linked-discussion verification against production Telegram update shapes is still required
- DONE: seller-configured claim keywords
  - claim handler now respects `seller_configs.claim_keywords` with sane defaults
  - seller-facing config UI for editing keywords is still missing
- DONE: atomic first-claim lock end-to-end
- DONE: queued later claims
- PARTIAL: buyer DM with payment instructions
  - DM attempts already exist, but they are best-effort and not yet tied to broader claim/payment state transitions
- PARTIAL: seller notifications on claim state changes
  - first-claim seller DM exists, but later queue, expiry, paid, and SOLD transitions are not yet covered
- DONE: seller blacklist enforcement during claims
- DONE: missed-payment queue advancement

## 8. Auctions
- TODO: auction listing type selection
- TODO: comment-based bid parsing
- TODO: minimum increment enforcement
- TODO: atomic highest-bid updates
- PARTIAL: auction lifecycle now works end-to-end
  - `/auction` now creates bot-posted auction listings from the same photo/OCR intake shape as `/list`
  - numeric bids from linked discussion replies/comments now update the high bid atomically and live-edit the Telegram post
  - anti-snipe extension now exists in the atomic bid RPC
  - auction closeout now promotes the winner into the existing payment-deadline flow
- TODO: live QA on linked-discussion bid parsing and award notifications
- TODO: seller-side auction controls (cancel / end-early / relist)
- TODO: cross-post synchronization for auction edits and closure states

## 9. Transactions and SOLD Lifecycle
- PARTIAL: transaction domain scaffolding exists
  - `db/transactions.py` and `handlers/transactions.py` are present but not implemented beyond scaffolding
- DONE: seller marks payment received
- DONE: transaction persistence flow
- DONE: SOLD edits on channel messages
- TODO: cross-post SOLD synchronization
- TODO: verified sale count updates
- TODO: dispute support / notes

## 10. Seller Operations
- DONE: seller-tools dashboard exists
  - `handlers/seller_tools.py` now provides a Telegram button dashboard for inventory, listing detail, queue view, sales, blacklist, and vacation mode
- DONE: active listings view
- DONE: sold listings view
- DONE: transaction history view
- DONE: blacklist management
- DONE: vacation mode
- TODO: scheduled listings
- TODO: cross-post tools

## 11. Trust and Evidence
- TODO: verified sale counts surfaced to sellers
- TODO: buyer strikes for non-payment
- TODO: seller-specific blacklist enforcement during claims
- TODO: PDF evidence export
- TODO: reputation system buildout

## 12. Non-Functional / Launch Hardening
- PARTIAL: important setup state persists in DB
- TODO: important listing draft state persists across restarts
- PARTIAL: idempotent duplicate Telegram update handling
  - claim comments, `/sold`, blacklist/vacation mutations, and dashboard mark-paid/vacation callbacks now use DB-backed processed-event keys
  - broader coverage for all callback/message mutations and full webhook/runtime rollout is still needed
- TODO: structured template/message centralization
- TODO: production webhook deployment
- PARTIAL: observability and evaluation
  - OCR/resolver synthetic audit harness now exists
  - wider automated coverage, progress reporting, and recurring runs are still needed
- TODO: import/data validation reports

## Minimal GA Execution Milestones
- M1: claim flow validation and hardening
  - verify linked-discussion resolution
  - add seller-configurable keywords
  - enforce blacklist checks
- M2: queue semantics and claim state integrity
  - later claims queue chronologically
  - winner state stays atomic
- M3: payment deadline worker
  - expire unpaid claims
  - advance queue or reactivate listing
- M4: mark paid, SOLD edits, and transaction closure
  - seller marks paid
  - transaction row created
  - listing post marked SOLD
- M5: minimal seller operations
  - active listings
  - sold/transaction history
  - blacklist + vacation mode
- M6: launch hardening
  - webhook deployment
  - duplicate-update protection
  - recurring eval and monitoring

## 13. Deferred / Later
- TODO LATER: One Piece full support
- TODO LATER: Japanese Pokémon catalog support
- TODO LATER: price history buildout
- TODO LATER: buyer reputation
- TODO LATER: wishlist / WTB matching
- TODO LATER: marketplace payments / escrow
- TODO LATER: web dashboard
