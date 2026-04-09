# DATABASE.md — TCG Listing Bot

## Database Design and Schema Notes

This document defines the normalized data model for Phase 1.

Use Supabase Postgres as the source of truth.

## 1. Core Design Principles

- seller data is tenant-scoped
- Telegram IDs are key operational identifiers
- important lifecycle transitions must be atomic
- bot-posted message identifiers must be stored for later edits
- game support must not be hardcoded to Pokémon only

## 2. Core Entities

### `sellers`
- one row per Telegram seller account
- stores Telegram identity, status, reputation, and high-level metrics

### `seller_configs`
- one row per seller
- stores setup and default behavior

### `cards`
- canonical card catalog
- supports multiple games and languages
- must include enough data to power identification and pricing lookup

### `listings`
- one logical listing
- stores denormalized display values, price references, status, and primary Telegram message refs

### `listing_channels`
- one row per listing-channel post
- required for cross-posting and consistent SOLD edits

### `claims`
- one row per claim or winning auction-state claim
- stores queue order, claim status, payment lifecycle, and timing

### `transactions`
- final commercial record for completed sales

### `strikes`
- platform-level accountability events against Telegram IDs

### `seller_buyer_blacklist`
- seller-specific blocklist

### `scheduled_listings`
- listings prepared for future posting

## 3. Recommended Tables

The attached draft schema is a strong starting point. Keep these tables with revisions where
needed:
- `sellers`
- `seller_configs`
- `cards`
- `listings`
- `listing_channels`
- `claims`
- `transactions`
- `strikes`
- `seller_buyer_blacklist`
- `scheduled_listings`
- optional later: `price_history`

## 4. Required Schema Revisions from the Draft

### Keep
- seller and seller config separation
- separate `listing_channels` for cross-posting
- separate `claims` and `transactions`
- unique confirmed-claim protection per listing

### Change
- do not treat Pokémon-only seeding as sufficient; the catalog must support `pokemon` and
  `onepiece`
- make room for EN and JP naming data
- prefer storing storage object key/path instead of only `image_url`
- avoid relying on client-side transaction semantics through the Supabase Python client for the
  most race-sensitive flows

## 5. Listing Status Model

Recommended statuses:
- `draft`
- `active`
- `claim_pending`
- `sold`
- `expired`
- `cancelled`

Auction listings may also use:
- `auction_active`
- `auction_closed`

If you prefer one unified model, document it clearly and keep transitions consistent.

## 6. Claim Status Model

Recommended statuses:
- `queued`
- `confirmed`
- `payment_pending`
- `paid`
- `failed`
- `cancelled`
- `rejected`

## 7. Required Atomic Operations

Implement these as Postgres functions callable through Supabase RPC:
- `claim_listing_atomic`
- `advance_claim_queue`
- `record_bid_atomic`
- `complete_transaction_atomic`
- `reactivate_listing_after_failure`

These operations must handle race conditions that occur when multiple claimers or bidders act at
nearly the same time.

## 8. Catalog Model Notes

For `cards`, keep fields like:
- `game`
- `set_code`
- `set_name`
- `card_number`
- `card_name_en`
- `card_name_jp`
- `variant`
- `rarity`
- `tcgplayer_product_id`
- `pricecharting_id`
- source-specific metadata as needed

Add indices appropriate for:
- `(game, set_code, card_number)`
- English name search
- Japanese name search

## 9. Images and Storage

In `listings`, prefer fields like:
- `primary_image_path`
- `secondary_image_path`
- optional signed URL cache fields if needed

Do not use database rows to store raw image blobs.

## 10. Suggested Migration Order

1. base schema
2. indexes and constraints
3. RPC / SQL functions for atomic transitions
4. row-level security policies if needed for future frontends
5. initial seed/import scripts for card catalogs

## 11. Seed Strategy

- Pokémon can use TCGdex-backed or similar import scripts where appropriate
- One Piece should use a separate curated import path instead of forcing a Pokémon-specific source
- seed scripts should be repeatable and idempotent where practical

## 12. Out of Scope for Initial Schema

- escrow/payment rail tables
- KYC identity documents
- marketplace order books
- public buyer network entities beyond what is needed for claims on existing listings
