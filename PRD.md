# PRD.md — TCG Listing Bot

## Product Requirements Document v1.0

## 1. Product Overview

- Product name: `TCG Listing Bot`
- Product type: Telegram bot
- Primary users: trading card sellers running on Telegram channels
- Product model: multi-seller SaaS
- Launch region: Singapore first
- Launch catalog scope: Pokémon and One Piece, English and Japanese cards

### Core Value Proposition

Collapse a fragmented seller workflow into a single Telegram-native system:
- photo in
- card identified
- price references shown
- preview generated
- listing posted
- comments monitored for claims or bids
- transactions tracked automatically

The product should help a seller go from photo to posted listing in under 90 seconds in normal
cases.

## 2. Problem Statement

Telegram-based TCG sellers currently move between several tools just to publish one listing:
- card photos in Telegram
- manual search in pricing sites
- manual copywriting or AI-assisted formatting
- manual posting to channels
- manual monitoring of claim comments
- manual follow-up for payment
- manual SOLD edits and transaction tracking

This costs time, creates missed claims, and produces poor operational visibility.

## 3. Product Goals

### Phase 1 goals
- reduce listing creation time materially for active sellers
- automate claim detection and queue handling for bot-posted listings
- create a reliable seller transaction record
- support auctions in the same Telegram-native workflow
- support multi-seller isolation and per-seller configuration

### Success metrics
- 20+ active sellers within 90 days of launch
- average photo-to-posted-listing time under 90 seconds
- claim confirmation path completes within 5 seconds in normal conditions
- no critical seller flow depends on a web dashboard
- no unhandled production crashes on the happy path flows

## 4. Non-Goals for Phase 1

- no public marketplace
- no escrow or payment processing
- no commissions on completed sales
- no KYC or identity verification workflow
- no required web dashboard
- no Discord or WhatsApp support
- no buyer-side WTB marketplace network in first GA

## 5. Primary Users

### Casual seller
- lists occasional pulls
- values speed and formatting help

### Hobby seller
- runs a small channel
- values claims automation, sold edits, and history

### Dealer / high-volume seller
- runs multiple channels or higher weekly volume
- values cross-posting, auctions, queueing, and operational visibility

## 6. Key User Stories

### Seller stories
- As a seller, I want to upload photos and get a likely card match so I do not search manually.
- As a seller, I want to see price references before posting so I can set an informed price.
- As a seller, I want a preview and final confirmation so the bot does not post mistakes.
- As a seller, I want claim comments detected automatically so I do not miss buyers.
- As a seller, I want payment deadlines and queue advancement automated so I do not babysit.
- As a seller, I want SOLD edits and transaction records created automatically.
- As a seller, I want auctions handled in the same comment-driven workflow.
- As a seller, I want blacklist and vacation tools for operational control.

### Platform stories
- As the platform owner, I want seller data isolated per tenant.
- As the platform owner, I want claim and bid handling to be race-safe.
- As the platform owner, I want integrations to fail gracefully without breaking Telegram UX.

## 7. Functional Requirements

### FR-01 Onboarding and seller setup
- `/start` creates or loads the seller account.
- `/setup` captures seller profile, linked channels, payment methods, postage defaults, claim
  settings, and template settings.
- The bot verifies required posting permissions before a channel is enabled.
- All important setup state persists across restarts.

### FR-02 Listing creation
- Seller can start listing creation with `/list` or by sending photos.
- Bot accepts front and back card photos.
- Bot rejects unsupported media types clearly.
- Bot checks image quality before OCR.
- OCR and card identification support Pokémon and One Piece, EN and JP.
- Bot presents best-effort card match plus confidence.
- If confidence is low, seller can correct details before posting.

### FR-03 Price lookup
- Bot fetches price references from multiple sources when available.
- Prices are normalized to SGD for display.
- Partial failures do not block listing creation.
- Seller can always override the suggested price.

### FR-04 Listing preview and posting
- Seller chooses listing type: fixed price or auction.
- Seller can edit condition notes and optional description.
- Seller always sees a preview before post.
- Seller must confirm before the bot posts.
- Bot stores the Telegram message IDs needed for later edits.

### FR-05 Comment-based claim handling
- Bot monitors comments or replies attached to bot-posted listing messages.
- A valid claim is detected from seller-configured keywords, defaulting to `Claim`.
- The first valid claim wins only if the atomic lock succeeds.
- Later claims enter a queue in chronological order.
- Bot DMs the winning buyer with payment instructions if possible.
- Bot notifies the seller of claim state changes.
- If payment is missed, the next queued buyer is advanced automatically.

### FR-06 Auctions
- Auction bids are parsed from comments or replies on auction listings.
- Valid bids must satisfy minimum increment rules.
- The highest bid is updated atomically.
- The listing message is edited in place to show the current bid.
- Anti-snipe rules extend end time when valid late bids arrive.
- Winner flow reuses the payment workflow.

### FR-07 Transactions and lifecycle
- Seller can mark payment received from Telegram.
- Transaction record is persisted.
- Reputation / verified sale count is updated.
- Listing is edited to SOLD.
- Cross-posted copies are updated consistently.

### FR-08 Seller operations
- Seller can view active listings and sold listings.
- Seller can view transaction history.
- Seller can manage blacklist entries.
- Seller can enable vacation mode.
- Seller can schedule listings for future posting.
- Seller can cross-post to approved channels.

### FR-09 Trust and evidence
- Bot maintains verified sale counts.
- Bot logs strikes for non-payment or similar operational failures.
- Bot can export transaction evidence as a PDF.

## 8. Deferred Features

These remain explicitly deferred unless the user changes scope:
- WTB matching and buyer demand network
- wishlist digests
- marketplace payments or escrow
- web dashboard
- commission model
- formal white-label admin tooling

## 9. Non-Functional Requirements

### Performance
- simple Telegram responses should return quickly
- listing creation should complete within a reasonable seller-facing window
- slow optional tasks must not block the main bot response

### Reliability
- all important state must survive process restarts
- duplicate Telegram updates must be idempotent
- race-sensitive transitions must use database-backed atomic logic

### Security
- all secrets come from environment variables
- seller data is tenant-scoped
- user-provided text is escaped before insertion into Telegram HTML

### Maintainability
- message strings and templates are centralized
- game-specific parsing is isolated behind adapters or services
- adding more games later should not require rewriting core handler logic

## 10. Acceptance Criteria for First GA

The first production-ready release is complete when all of the following are true:
- a seller can complete setup and post a listing entirely inside Telegram
- a seller can create a Pokémon or One Piece listing in EN or JP with confirmation before post
- a valid claim comment on a bot-posted listing is handled correctly end-to-end
- missed payment advances the queue correctly
- a seller can complete a transaction and trigger SOLD edits and history updates
- auction close flow works correctly for at least the supported auction path
- the bot survives restart without losing important setup or listing draft state

## 11. Release Shape

### First GA
- onboarding
- listing creation
- price reference support
- comment-based claims
- payment deadlines and queueing
- sold edits and transaction log
- blacklist
- vacation mode
- auctions
- scheduled listings
- cross-channel posting

### Shortly after GA
- auto-bump
- price movement alerts
- duplicate listing warning
- richer analytics digest
