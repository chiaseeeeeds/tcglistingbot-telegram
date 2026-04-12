# TODO.md — PRD Gap Checklist

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
  - postage defaults
  - claim keyword settings
  - template settings
- TODO: additional approved channels / cross-post configuration

## 3. Listing Creation
- DONE: `/list` starts from Telegram DM
- DONE: photo-first listing flow exists
- DONE: seller confirmation before posting
- PARTIAL: OCR and identification
  - Pokémon EN catalog pipeline exists
  - current OCR identification works but still leans too much on branchy resolver heuristics
  - architecture reset is now planned in `OCR_ARCHITECTURE_RESET.md` to move toward structured OCR signals, generic candidate generation, and one evidence scorer
  - Phase A has started: OCR now emits a first structured signal object alongside the legacy merged OCR text
  - live-photo coverage is still incomplete for foil, glare, and promo/alphanumeric identifiers
- PARTIAL: card match confidence flow
  - best-effort suggestion exists
  - shortlist / fallback UX still needs more refinement for ambiguous cases
- TODO: front + back photo support
- TODO: unsupported media rejection UX
- TODO: image quality checks before OCR
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
  - current resolver should be refactored into a cleaner candidate-generation + scoring architecture instead of accumulating rescue branches
  - keep guarding against digit-only false set-code parses on plain ratios like `186/203`
  - promo/alphanumeric identifiers like `BW95` and `TG28` still need dedicated support and evaluation coverage
- PARTIAL: fallback prompt for manual `series code + serial code`
- TODO: Japanese catalog source and importer
- TODO: Japanese OCR/resolver evaluation coverage
- TODO: One Piece catalog source and importer
- TODO: broader real-photo evaluation corpus stored in-repo or in a managed eval bucket

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
- TODO: linked-discussion comment monitoring
- TODO: seller-configured claim keywords
- TODO: atomic first-claim lock end-to-end
- TODO: queued later claims
- TODO: buyer DM with payment instructions
- TODO: seller notifications on claim state changes
- TODO: missed-payment queue advancement

## 8. Auctions
- TODO: auction listing type selection
- TODO: comment-based bid parsing
- TODO: minimum increment enforcement
- TODO: atomic highest-bid updates
- TODO: message edits with current bid
- TODO: anti-snipe extension logic
- TODO: auction winner flow reusing payment path

## 9. Transactions and SOLD Lifecycle
- TODO: seller marks payment received
- TODO: transaction persistence flow
- TODO: SOLD edits on channel messages
- TODO: cross-post SOLD synchronization
- TODO: verified sale count updates
- TODO: dispute support / notes

## 10. Seller Operations
- TODO: active listings view
- TODO: sold listings view
- TODO: transaction history view
- TODO: blacklist management
- TODO: vacation mode
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
- TODO: idempotent duplicate Telegram update handling
- TODO: structured template/message centralization
- TODO: production webhook deployment
- PARTIAL: observability and evaluation
  - OCR/resolver synthetic audit harness now exists
  - wider automated coverage, progress reporting, and recurring runs are still needed
- TODO: import/data validation reports

## 13. Deferred / Later
- TODO LATER: One Piece full support
- TODO LATER: Japanese Pokémon catalog support
- TODO LATER: price history buildout
- TODO LATER: buyer reputation
- TODO LATER: wishlist / WTB matching
- TODO LATER: marketplace payments / escrow
- TODO LATER: web dashboard
