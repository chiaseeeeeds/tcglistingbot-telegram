# BOT_FLOWS.md — TCG Listing Bot

## Telegram Conversation and Lifecycle Flows

This file defines the intended Phase 1 bot UX at a product level.

Exact button labels can evolve during implementation, but these flows are the source of truth.

## 1. `/start`

### New user
- create seller record if missing
- create seller config record if missing
- welcome the user
- direct them to `/setup`

### Existing user
- show a compact home menu with actions like:
  - list a card
  - view active listings
  - view sold history
  - settings

## 2. `/setup`

The setup flow should collect:
- primary posting channel
- optional additional posting channels
- seller display name
- payment methods
- payment details
- postage defaults
- footer / disclaimer text
- default claim keyword(s)
- default payment deadline hours

### Setup validation
- the bot must verify required channel permissions before setup completes
- failed permission checks should explain what the seller must change
- for `@TCGMarketplaceSingapore`, claims are expected to arrive through the linked discussion flow
- setup should explicitly validate the posting channel and its linked discussion-group path before enabling automated claim handling

## 3. Listing Creation Flow

### Step 1: intake
- seller starts with `/list` or by sending a photo
- bot requests front and back photos if both are not yet provided

### Step 2: quality checks
- bot warns about blurry, dark, bright, or tiny images
- seller can retake or continue

### Step 3: OCR and identification
- bot extracts text from both images
- bot attempts card match using the relevant game adapter
- low-confidence or unknown results fall back to manual correction

### Step 4: pricing
- bot gathers available price references
- bot displays suggested price and source references
- seller can override manually

### Step 5: listing details
- seller chooses fixed-price or auction
- seller enters optional condition notes
- seller may choose schedule time or immediate post
- seller may choose additional channels if enabled

### Step 6: preview
- bot shows final preview
- seller can confirm, edit, or cancel

### Step 7: posting
- bot posts listing to the selected channel(s)
- bot stores all created message IDs for future updates

## 4. Claim Handling Flow

### Trigger
- a valid comment or reply is received on a bot-posted fixed-price listing

### Processing
- validate the listing is still claimable
- validate the claim keyword pattern
- attempt atomic claim lock

### Outcomes
- if first valid claim succeeds:
  - set listing to claim-pending state
  - DM buyer with payment instructions if possible
  - notify seller
- if listing is already claimed:
  - queue the buyer behind the current claimer if queueing is enabled
- if buyer is blacklisted or requires manual review:
  - follow seller policy and notify seller appropriately

## 5. Payment Completion Flow

### Seller action
- seller taps a button or issues a command to mark payment received

### System action
- complete transaction atomically
- edit all relevant listing messages to SOLD
- update seller reputation / verified sales count
- record transaction history

## 6. Missed Payment Flow

### Trigger
- payment deadline worker finds an unpaid confirmed claim

### System action
- mark current claim as failed
- log strike if policy applies
- advance next queued claim atomically if one exists
- otherwise reactivate the listing
- notify seller of the result

## 7. Auction Flow

### Create auction
- seller chooses auction mode
- seller sets starting bid, increment, end time, and anti-snipe configuration

### Bid handling
- parse numeric bids from comments or replies
- validate increment and auction status
- update highest bid atomically
- edit listing in place with latest bid
- notify previously highest bidder if they can be DM'd

### Auction close
- worker closes auction when time expires
- highest valid bidder becomes the winner
- winner enters payment flow

## 8. Seller Tools

### `/inventory`
- show active listings and quick actions

### `/sold`
- show completed transactions and sold archive references

### `/stats`
- show seller-level operational summary

### `/vacation`
- toggle vacation mode until a chosen date

### `/blacklist`
- add, remove, and list blocked buyers

### `/evidence`
- export evidence for a completed transaction

## 9. Deferred Flows

These remain documented as future work, not first-GA requirements:
- `/wtb`
- buyer wishlist and digest flows
- marketplace or escrow flows
