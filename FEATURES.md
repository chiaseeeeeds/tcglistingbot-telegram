# FEATURES.md — TCG Listing Bot

## Detailed Feature Scope

This file translates the PRD into buildable feature slices.

## 1. Must-Ship First GA Features

### F-01 Photo quality checks
- validate photo inputs before OCR
- warn about blurry, dark, or poor-quality photos
- allow seller override

### F-02 OCR and card identification
- run OCR on front and back images
- attempt canonical match for Pokémon and One Piece
- support EN and JP naming paths
- provide manual correction when confidence is low

### F-03 Price lookup
- gather price references from available sources
- convert to SGD for display
- tolerate missing or partial pricing data

### F-04 Listing templating
- build formatted Telegram HTML listing text from seller settings
- support seller footer, postage, and payment details
- support fixed and auction templates

### F-05 Posting and cross-posting
- post to primary channel
- optionally post to approved secondary channels
- persist message identifiers for all channel copies

### F-06 Claim queue handling
- detect valid claim comments
- lock first winner atomically
- queue later valid claimers
- DM buyer and notify seller

### F-07 Payment deadline enforcement
- expire unpaid claims after configured deadline
- advance queue or reactivate listing

### F-08 SOLD lifecycle
- allow seller to mark payment received
- create transaction record
- edit all related listing messages to SOLD

### F-09 Auctions
- accept valid bids from comments
- update current high bid atomically
- support anti-snipe behavior
- close and award auction automatically

### F-10 Seller controls
- blacklist
- vacation mode
- inventory view
- sold history
- evidence export

### F-11 Scheduled listings
- allow seller to prepare now and post later
- worker posts scheduled listings safely after restart

## 2. Should-Ship Soon After GA

### F-12 Auto-bump
- optionally relist unsold items after seller-defined period

### F-13 Duplicate listing warning
- warn before seller posts likely duplicate active inventory

### F-14 Price movement alerts
- compare active listing against refreshed price references

### F-15 Analytics digest
- periodic seller summary of sales and listing performance

## 3. Deferred Features

### Deferred for later phases
- WTB matching
- buyer digests
- marketplace payments
- commissions
- KYC
- public dashboards

## 3A. Explicit Roadmap TODOs

- implement completed-sale price history capture
- implement seller verified-sales updates on transaction completion
- implement buyer strikes and blacklist enforcement during claims
- add seller-facing sold history and reputation views

## 4. Implementation Notes

### Error handling expectations
- failed OCR should fall back to manual correction
- failed price lookups should still allow posting
- buyer DM failures must notify the seller clearly

### Data safety expectations
- important lifecycle transitions must be atomic
- optional background tasks must be idempotent

### Product expectations
- seller confirmation remains mandatory before posting
- bot-only operation remains the default Phase 1 experience
