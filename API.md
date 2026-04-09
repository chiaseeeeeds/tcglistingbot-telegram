# API.md — TCG Listing Bot

## External Integrations and API Notes

This file records the planned external services and important implementation constraints.

## 1. Google Cloud Vision

### Purpose
- OCR for card images

### Use
- extract text from front and back images
- feed text into game-specific parsing and identification

### Requirements
- service account JSON stored outside version control
- credentials loaded by environment variable

### Failure policy
- OCR failure must degrade to manual correction, not hard-stop the seller

## 1A. Local Tesseract OCR

### Purpose
- lower-cost local OCR path for early development and first internal testing

### Use
- default OCR provider when you do not want to pay for hosted OCR yet
- best paired with seller confirmation and manual correction

### Constraints
- requires local/system Tesseract installation
- quality depends heavily on image quality and text layout
- should be treated as a best-effort first-pass recognizer

## 2. TCGPlayer

### Purpose
- primary EN pricing reference where available

### Use
- fetch pricing for cards with known product mapping

### Constraints
- approval may take time
- do not make the product depend solely on TCGPlayer approval

## 3. PriceCharting

### Purpose
- secondary pricing reference

### Constraints
- scrape responsibly
- rate limit requests
- tolerate blocks or missing coverage

## 4. Yuyutei

### Purpose
- strong JP market reference, especially for Japanese cards

### Constraints
- prices need JPY to SGD conversion
- scraping should be rate-limited and resilient

## 5. Exchange Rate Source

### Purpose
- normalize USD and JPY references into SGD

### Requirements
- cache rates
- do not fetch on every single listing operation

## 6. Card Catalog Sources

### Pokémon
- TCGdex or equivalent import sources may be used for seed/import workflows

### One Piece
- use a separate curated import strategy appropriate for One Piece data

The product must not assume one catalog source works equally well for both games.

## 7. Telegram Bot API Constraints

- the bot cannot DM users who have never started it
- the bot can only edit messages it posted
- comment/reply handling depends on the posting channel and discussion configuration
- production deployment should use webhooks

## 8. Supabase Storage

### Purpose
- store listing images

### Rules
- keep the storage bucket private if possible
- store object path references in the database
- generate signed access when needed

## 9. Operational Notes

- every external integration must be wrapped with retries or graceful fallback where sensible
- failures must be logged with enough context to debug seller-facing problems
- none of these integrations should expose raw errors to Telegram users
