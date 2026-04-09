# TODO.md — TCG Listing Bot

## Next Product Buildout

### Priority 1 — Claims and transaction completion
- Implement linked-discussion claim detection for bot-posted listings.
- Persist claim queue ordering and first-valid-claim resolution.
- Add seller payment confirmation flow.
- Create transaction records on completed sales.
- Edit posted messages to SOLD on transaction completion.

### Priority 2 — Reputation system
- Increment `sellers.reputation_score` when a transaction completes.
- Surface seller verified sale count in listing output.
- Add buyer strike logging for non-payment and abandoned claims.
- Add buyer blacklist enforcement during claim handling.
- Add seller-facing views for strikes and blacklist state.

### Priority 3 — Price history buildout
- Add live `price_history` table migration to production schema.
- Record completed sale prices into `price_history` on every transaction.
- Store market references captured at listing time alongside completed sale data.
- Add queries for per-card and per-game sale history retrieval.
- Expose basic seller analytics from price history and transactions.

### Priority 4 — Listing operations hardening
- Verify linked discussion group behavior during setup more deeply.
- Add channel/comment permission diagnostics.
- Add duplicate listing warnings.
- Add scheduled listing posting and auto-bump jobs.

### Priority 5 — OCR and catalog quality
- Implement real Tesseract OCR pipeline in `services/ocr.py`.
- Add Pokémon and One Piece parsing heuristics.
- Add manual correction path for low-confidence OCR.
- Add catalog import scripts for broader card coverage.
