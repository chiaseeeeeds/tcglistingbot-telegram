# TODO.md — PRD Gap Checklist

## Status Legend
- DONE = implemented and working at a meaningful level
- PARTIAL = started, but not yet aligned with PRD/GA intent
- TODO = not yet implemented
- BLOCKED = depends on another unfinished system

## 1. Foundation
- DONE: config loading and environment validation
- DONE: Supabase connectivity and migrations
- DONE: single-bot-process guard for polling stability
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
  - final language-detect → bottom-left-zone → identifier resolver flow not complete
- PARTIAL: card match confidence flow
  - best-effort suggestion exists
  - final structured fallback UX still incomplete
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
- PARTIAL: final OCR identifier resolver against imported `cards`
- PARTIAL: fallback prompt for manual `series code + serial code`
- TODO: Japanese catalog source and importer
- TODO: One Piece catalog source and importer

## 5. Price Lookup
- PARTIAL: bot-history fallback price references exist
- TODO: multi-source price lookup
- TODO: SGD normalization from external sources
- TODO: external pricing resilience / partial failure policy
- TODO: pricing display tied to resolved card identity

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
- TODO: observability and failure dashboards
- TODO: import/data validation reports

## 13. Deferred / Later
- TODO LATER: One Piece full support
- TODO LATER: Japanese Pokémon catalog support
- TODO LATER: price history buildout
- TODO LATER: buyer reputation
- TODO LATER: wishlist / WTB matching
- TODO LATER: marketplace payments / escrow
- TODO LATER: web dashboard
