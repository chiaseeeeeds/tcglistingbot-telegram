# STATUS.md — TCG Listing Bot

## Working Now
- Bot process runs locally in Telegram polling mode
- `/start`, `/help`, `/setup`, `/ping`, `/list`, `/auction`, `/sold`, `/stats`, and `/admin` respond
- Seller account and setup data persist in Supabase
- Seller can link a primary Telegram channel
- `/list` starts from a DM photo upload
- OCR runs locally with Tesseract
- Photo quality is checked before OCR on listing and auction intake
- Pokémon EN card matching uses the imported `cards` catalog
- Bottom-left identifier matching works when OCR reads set code + card number
- Manual identifier fallback works with input like `PAF 234/091`
- Seller gets a listing preview before posting
- Bot can post the listing to the configured Telegram channel
- Posted message IDs are stored in the database
- Pokémon EN catalog import is complete

## Partially Working
- OCR is functional but still needs live tuning on real seller photos
- `/setup` now stores claim keywords and default postage, but richer payment/template settings are still incomplete
- Price references prefer exact `card_id` history, but bot history is still sparse
- Title/manual fallback works, but the seller UX can still be tightened
- Image storage works, but production hardening is still pending
- Local runtime is stable for development, but always-on hosting is not done yet

## Not Working Yet
- Linked discussion comment monitoring live QA
- Payment deadline automation
- Queue advancement after missed payment
- SOLD message edits and transaction completion flow
- Active listings / sold listings / transaction history views
- Buyer strikes and reputation system
- External live price providers
- One Piece card flow
- Japanese Pokémon catalog flow
- Front + back image intake
- Webhook production deployment

## Best End-To-End Flow Available Today
1. Seller runs `/setup`
2. Seller links a channel
3. Seller runs `/list` in DM
4. Seller sends a front photo
5. Bot runs OCR
6. Bot tries exact Pokémon EN identifier match
7. Seller can type manual identifier if OCR is weak
8. Bot suggests card title and shows price refs if available
9. Seller enters final price and optional notes
10. Seller confirms with `post`
11. Bot posts to the Telegram channel

## Immediate Next Milestones
1. Live-test `/list` with real Pokémon EN cards and tune OCR matching
2. Add live external price references
3. Support front + back photo intake
4. Implement linked-discussion claim handling
5. Implement payment deadline + queue advancement
6. Implement SOLD lifecycle and transaction records
7. Deploy to Railway/webhook mode

## Success Threshold For The Current Phase
- Seller can reliably create a Pokémon EN listing from a real card photo
- Bot can resolve the card from OCR or manual identifier fallback
- Seller can confirm and post without manual admin intervention
- Price references are useful enough to help pricing decisions
