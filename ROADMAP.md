# ROADMAP.md — TCG Listing Bot

## Goal
Ship a usable Telegram-native seller bot that can create listings reliably, post them to the seller's channel, and manage claim/payment lifecycle inside Telegram.

## Roadmap Principles
- finish the Pokémon EN path end-to-end first
- do not expand scope before the core claim/payment loop works
- always prefer reliable manual fallback over fragile automation
- complete bot-first operations before adding admin/dashboard surfaces

## Phase 0 — Stability Baseline
### Objective
Keep the bot responsive and operable during active development.

### Includes
- command responsiveness
- single-instance polling safety
- stable setup flow
- stable manual posting flow

### Exit Criteria
- `/start`, `/setup`, `/list`, `/help`, `/ping` are consistently responsive
- seller can still complete the current manual fallback path

## Phase 1 — Pokémon EN Listing Core
### Objective
Complete one clean listing path for Pokémon EN from photo to confirmed post.

### Includes
- complete Pokémon EN catalog import
- final language-detect → identifier-zone OCR → resolver flow
- manual fallback for `series code + serial code`
- best-effort price references before seller final price
- preview and post with stored message refs

### Exit Criteria
- seller uploads a Pokémon EN front photo
- bot detects likely language and reads identifier zone
- bot resolves the card or falls back cleanly
- seller confirms and the bot posts successfully

## Phase 2 — Claim and Payment Core
### Objective
Make posted listings operationally useful in the real channel.

### Includes
- linked-discussion comment monitoring
- claim keyword parsing
- atomic first-claim winner
- claim queue for later buyers
- buyer payment DM when possible
- missed-payment deadline and queue advancement

### Exit Criteria
- a valid claim comment on a bot-posted listing is handled end-to-end
- missed payment advances the queue correctly

## Phase 3 — Transaction and Seller Ops
### Objective
Close the post-sale loop and give sellers practical operational tools.

### Includes
- seller marks payment received
- transaction persistence
- SOLD edits
- active / sold listing views
- blacklist management
- vacation mode
- transaction history

### Exit Criteria
- a seller can complete a sale and see history updates inside Telegram
- bad buyers can be blocked operationally

## Phase 4 — Pricing and Trust Hardening
### Objective
Improve pricing usefulness and trust signals without blocking core flows.

### Includes
- live external pricing sources
- SGD normalization and caching
- verified sale counters
- strikes / reputation scaffolding
- evidence export

### Exit Criteria
- listings show meaningful price references
- trust data is stored and seller-visible where appropriate

## Phase 5 — Auctions
### Objective
Add auction flows after fixed-price claim handling is proven stable.

### Includes
- auction listing type
- bid parsing
- increment rules
- anti-snipe logic
- auction close / winner flow

### Exit Criteria
- at least one supported auction path works reliably end-to-end

## Phase 6 — Expansion Scope
### Objective
Add the remaining catalog and game scope once the EN Pokémon path is production-sound.

### Includes
- Japanese Pokémon catalog + resolver
- One Piece set-zone mapping and catalog
- One Piece listing path

### Exit Criteria
- EN + JP Pokémon and One Piece all work through the same bot-first pipeline

## Immediate Next Sequence
1. finish the clean Pokémon EN catalog load
2. validate imported `cards`
3. wire final OCR identifier resolver to `cards`
4. add fallback input for `series code + serial code`
5. implement linked-discussion claim handling
6. implement payment deadlines + queue advancement
7. implement SOLD + transaction log
8. deploy to Railway/webhook

## What Not To Do Yet
- do not build the web dashboard yet
- do not expand One Piece before Pokémon EN end-to-end works
- do not over-invest in JP OCR before EN identifier resolution is stable
- do not chase marketplace/escrow features in Phase 1
