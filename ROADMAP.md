# ROADMAP.md — TCG Listing Bot

## Goal
Ship a usable Telegram-native seller bot that can create listings reliably, post them to the seller's channel, and manage the fixed-price claim/payment/SOLD lifecycle inside Telegram.

## Roadmap Principles
- finish the Pokémon EN path end-to-end first
- do not expand scope before the fixed-price claim/payment loop works
- always prefer reliable manual fallback over fragile automation
- complete bot-first operations before adding admin/dashboard surfaces
- add evaluation coverage whenever OCR/catalog behavior changes so users are not doing manual QA for us
- when new feature requests appear, evaluate scope/architecture/tradeoffs first before proposing execution

## Minimal Phase 1 GA Definition
For the purpose of getting to a truthful minimum GA, this repo should treat these as the must-ship scope:
- seller onboarding and setup work reliably
- seller can create a listing from photos, confirm it, and post it
- posted fixed-price listings can be claimed from Telegram comments/replies
- first valid claim is locked atomically and later claims queue correctly
- seller can mark payment received
- missed payment advances the queue or reactivates the listing
- SOLD edits and transaction records work end-to-end
- core seller operations exist for active listings, sold history, and blacklist/vacation controls
- deployment, observability, and idempotency are good enough for live usage

These are explicitly not blockers for minimal GA and should be treated as post-GA fast-follow unless the user reprioritizes them:
- auctions
- Japanese Pokémon
- One Piece
- advanced pricing/trust features beyond usable references
- dashboard/web surfaces

## Current Reality Check
### What is strong now
- seller onboarding/setup exists
- listing creation exists and is the strongest path in the product
- OCR/matching architecture is moving in the right direction
- raw-photo OpenAI OCR is now live; the immediate priority is resolver safety, JP evaluation coverage, and latency tuning rather than adding more OCR branches
- live OCR QA now also needs truthful operator feedback; when hosted OCR changes, seller/admin messages must reflect the real fallback behavior and expose safe warning summaries for debugging
- snapshot-backed offline OCR evaluation exists
- multi-image listing intake with front/back classification now exists

### What still blocks GA
- claim reply monitoring, seller-configured keyword matching, blacklist enforcement, and queued-claim semantics are now wired, but linked-discussion behavior is not yet verified end-to-end
- payment deadline expiry, seller-paid completion, SOLD edits, transaction closure, a minimal Telegram seller dashboard, first-pass DB-backed idempotency, and reusable live message-edit infrastructure are now wired, but full runtime hardening and operational polish are still missing
- seller mark-paid -> SOLD -> transaction loop now exists through the minimal `/sold` command path
- seller operational tools are still placeholder-level
- no production deployment / webhook path yet
- no idempotent Telegram update handling yet

## Phase 0 — Stability Baseline
### Objective
Keep the bot responsive and operable during active development.

### Includes
- command responsiveness
- single-instance polling safety
- stable setup flow
- stable manual posting flow
- truthful debug output and build markers
- one active bot poller per token during local/live debugging

### Exit Criteria
- `/start`, `/setup`, `/list`, `/help`, `/ping` are consistently responsive
- seller can still complete the current manual fallback path
- the live build/debug output reflects the actual running logic

## Phase 1 — Listing Core Hardening
### Objective
Finish one dependable fixed-price listing creation path for Pokémon EN.

### Includes
- multi-image intake with front/back selection and seller override when uncertain
- photo quality checks before OCR
- robust Pokémon EN OCR/resolver path with manual fallback
- price reference presentation with truthful provider visibility
- preview + explicit seller confirmation
- post to Telegram with stored message refs and image paths
- snapshot-backed OCR regression workflow
- idempotent handling for duplicate listing-flow updates where practical

### Exit Criteria
- seller can send front/back photos, confirm title/price, and post successfully
- OCR no-match and low-confidence flows fall back cleanly
- listing post stores the front/back image references needed later
- OCR regressions are checked by routine offline audits, not only ad hoc user examples

## Phase 2 — Claim Core
### Objective
Make fixed-price bot-posted listings operational in the live channel.

### Includes
- linked-discussion validation in setup
- comment/reply monitoring for bot-posted listings
- seller-configurable claim keyword parsing with sensible defaults
- atomic first-claim lock
- queued later claims in chronological order
- seller notifications on claim state changes
- buyer DM when allowed and possible

### Exit Criteria
- a valid claim comment on a bot-posted listing is handled correctly end-to-end
- later valid claims queue correctly without race bugs
- seller can see claim state transitions without manual detective work

## Phase 3 — Payment, SOLD, and Transactions
### Objective
Close the operational sale loop inside Telegram.

### Includes
- seller marks payment received
- payment deadline worker for unpaid claims
- queue advancement or listing reactivation on missed payment
- SOLD edits on channel posts
- transaction persistence and seller-visible sold history
- verified message/listing linkage for auditability

### Exit Criteria
- seller can complete a real sale end-to-end inside Telegram
- unpaid winners are expired and queue advancement behaves correctly
- SOLD status and transaction history update reliably

## Phase 4 — Minimal Seller Ops
### Objective
Give sellers the minimum operational controls needed for daily usage.

### Includes
- active listings view
- sold listings / transaction history view
- blacklist management
- vacation mode
- basic evidence trail / notes sufficient for support and dispute review

### Exit Criteria
- sellers can manage active and completed listings from the bot
- bad buyers can be blocked operationally
- temporary seller unavailability can be controlled without manual admin intervention

## Phase 5 — Launch Hardening
### Objective
Make the minimum GA scope safe to run live.

### Includes
- webhook-friendly deployment path
- idempotent Telegram update handling
- recurring OCR evaluation runs
- import/data validation reports
- structured logging and incident-friendly debugging
- resilience around optional pricing/source failures

### Exit Criteria
- one production deployment path is documented and repeatable
- duplicate updates do not create duplicate side effects on critical flows
- operators can detect and debug failures without guessing

## Post-GA Fast Follow
### After minimal Phase 1 GA
1. auctions
2. advanced pricing/trust hardening
3. Japanese Pokémon
4. One Piece
5. richer seller ops and cross-post tooling

## Immediate Next Sequence
1. harden multi-image listing intake with seller front/back override and less chatty album UX
2. make pricing provider availability explicit in the seller flow
3. finish webhook deployment and duplicate-update/idempotency protection
4. continue OCR architecture cleanup only where it directly improves live listing accuracy or reduces manual correction rate

## Phase 2 Execution Plan For Minimal GA

### Milestone 1 — Claim Flow Validation and Hardening
**Goal**
- validate the existing linked-discussion reply resolution against real Telegram update shapes
- replace hardcoded claim keywords with seller-configurable keywords plus sensible defaults
- enforce seller blacklist checks before claim acceptance
- make claim-state replies and logs explicit about why a claim was accepted, queued, or rejected

**Depends on**
- current posted-message linkage in `db/listings.py`
- current `handlers/claims.py` reply-resolution scaffold
- current `claim_listing_atomic(...)` RPC contract

**Can run in parallel with**
- launch-hardening prep work that does not change claim behavior
- seller-op read-side queries that do not mutate claim state

**Acceptance criteria**
- a valid `Claim` reply in the linked discussion resolves back to the correct bot-posted listing
- blacklisted buyers are rejected safely and truthfully
- seller-configured keywords work without code edits
- logs show enough context to debug failed claim resolution without guessing

### Milestone 2 — Queue Semantics and Claim State Integrity
**Goal**
- extend the claim path so later valid claims queue chronologically after the first confirmed claim
- make claim statuses, queue positions, and listing status transitions explicit and queryable
- verify race behavior so two near-simultaneous claims do not both become the winner

**Depends on**
- Milestone 1 claim-resolution validation
- review and likely expansion of `migrations/004_atomic_rpc.sql` semantics

**Can run in parallel with**
- seller-op read views for active claims
- deployment prep that is orthogonal to claim mutation logic

**Acceptance criteria**
- first valid claim becomes the active payment-pending winner
- later valid claims are stored in deterministic queue order
- duplicate or concurrent winner states cannot occur for one listing
- seller can inspect the current winner plus queue state from the bot or DB-backed admin/debug output

### Milestone 3 — Payment Deadline Worker and Queue Advancement
**Goal**
- implement the unpaid-claim expiry worker in `jobs/payment_deadlines.py`
- advance the queue to the next eligible claimant or reactivate the listing when the queue is exhausted
- issue strike / blacklist side effects only where the PRD flow actually calls for them

**Depends on**
- Milestone 2 claim-state and queue semantics
- clear claim statuses and deadline fields in the `claims` table

**Can run in parallel with**
- seller-paid completion UI wiring, as long as both use the same claim-state contract

**Acceptance criteria**
- an unpaid winner expires automatically after the configured deadline
- the next queued claimant is promoted correctly when present
- the listing returns to an active claimable state when no queue remains
- state transitions are idempotent and safe if the worker retries

### Milestone 4 — Mark Paid, SOLD Edits, and Transaction Closure
**Goal**
- implement the seller-side payment confirmation flow
- persist transactions in `transactions`
- edit the original bot-posted listing message(s) to SOLD / completed state
- preserve an auditable linkage between listing, winning claim, and final transaction

**Depends on**
- Milestone 2 queue state contract
- Milestone 3 worker semantics, so manual paid completion and expiry cannot conflict
- real implementation of `db/transactions.py` and `handlers/transactions.py`

**Can run in parallel with**
- seller sold-history read views

**Acceptance criteria**
- seller can mark the current winning claim as paid from the bot
- one transaction row is created for the completed sale
- the channel listing is visibly marked SOLD
- completed listings no longer accept claims

### Milestone 5 — Minimal Seller Operations
**Goal**
- replace placeholder seller tools with the minimum daily-ops surface
- ship active listings, sold history / transactions, blacklist management, and vacation mode
- expose enough read-side information that sellers do not need manual DB checks for routine work

**Depends on**
- Milestones 1 through 4 for truthful operational data
- real queries behind `handlers/seller_tools.py`

**Can run in parallel with**
- launch hardening and deployment docs once side-effecting flows stabilize

**Acceptance criteria**
- seller can view active listings and current claim state
- seller can view completed sales / transaction history
- seller can add and remove blacklist entries
- seller can toggle vacation mode without breaking existing listings

### Milestone 6 — Launch Hardening
**Goal**
- move from local polling dependence toward a repeatable webhook-friendly deployment path
- add duplicate-update / idempotency protection around critical Telegram side effects
- make monitoring and recurring OCR regression checks operational, not ad hoc

**Depends on**
- core listing, claim, payment, and SOLD flows being stable enough to harden

**Can run in parallel with**
- late-stage seller-op polish
- OCR regression workflow polish that does not alter live claim/payment behavior

**Acceptance criteria**
- one documented deployment path can run continuously without manual babysitting
- duplicate Telegram updates do not duplicate claims, posts, or SOLD transitions
- logs and recurring eval jobs are sufficient to catch regressions before users report them

## Dependency Summary
- Milestone 1 must land before any trustworthy end-to-end claim QA exists
- Milestone 2 is the contract layer for all later claim/payment behavior
- Milestone 3 and Milestone 4 can overlap in implementation, but both depend on the Milestone 2 claim-state model
- Milestone 5 should mostly wait until Milestones 1 through 4 expose stable read/write semantics
- Milestone 6 should start early for observability, but GA sign-off only makes sense after Milestones 1 through 5 are operational

## Definition Of “Ready For Minimal GA”
Minimal Phase 1 GA is reached when Milestones 1 through 6 are complete for the Pokémon EN fixed-price path, even if auctions, Japanese Pokémon, and One Piece are still deferred.

## What Not To Do Yet
- do not treat auctions as a blocker for minimal GA
- do not expand One Piece before the fixed-price Pokémon EN seller ops loop works
- do not over-invest in JP OCR before the live claim/payment lifecycle exists
- do not build the web dashboard yet
- do not chase marketplace/escrow features in Phase 1


## Auction Track Status — 2026-04-13
- implemented: `/auction` creation flow, numeric bid parsing from discussion replies/comments, atomic high-bid updates, live Telegram post edits, anti-snipe extension, and auction closeout into the existing payment flow
- next hardening: live linked-discussion QA, seller auction controls, cross-post sync for edits, and abuse/edge-case handling around duplicate or malformed bids
- sequencing guidance: keep minimal GA sign-off anchored to the fixed-price seller loop, but auction work is no longer a scaffold-only track and can now be hardened in parallel

- 2026-04-13 update: `/setup` now captures claim keywords and default postage, `utils/photo_quality.py` is wired into listing/auction front-image selection before OCR, and `/admin` now exposes a live readiness snapshot including catalog coverage gaps.

- 2026-04-13 catalog unblock: the repo now has an official One Piece bilingual importer and a resumable official Japanese Pokémon importer, so the remaining launch work is data execution + live QA rather than unknown catalog-source design.

- 2026-04-13 execution follow-up: the JP importer had a real crash on numberless official energy detail pages; that failure mode is now fixed by skipping unidentifiable rows and continuing the crawl, so the remaining blocker is runtime completion rather than importer brittleness.
- 2026-04-13 pricing hardening: PriceCharting scrape fallback is now opt-in so listing creation is not dragged down by repeated Cloudflare-blocked requests when no API token is configured.
- 2026-04-13 deeper execution note: the JP official API issue was request-shape throttling more than a hard page cap; switching to slower browser-like pacing plus longer backoff reopened progress and moved the crawl through page 85.
- 2026-04-13 importer durability note: after fixing upstream throttle sensitivity, the JP crawl also needed per-page DB reconnects to avoid long-idle Postgres timeout failures during slow runs; with both fixes, progress has moved through page 92.
- 2026-04-13 importer continuation note: page-level source deduplication was required once the crawl reached duplicate-identity JP payloads around page 95; after that fix, progress continued through page 110.
- 2026-04-14 runtime note: in this local environment, PTY-backed runs are currently more trustworthy than detached `nohup` for both the bot and the long JP importer; production readiness still requires a real always-on deployment path rather than assuming local backgrounding is solved.
- April 14, 2026 sequencing update: the buyer payment-reference + screenshot + seller-review loop is now implemented, so the remaining Phase 1 execution gap shifts from missing payment-proof product code to live Telegram QA, runtime stability, and catalog/data completeness
- April 14, 2026 execution update: voluntary claim cancellation is now DB-backed and race-safe via `/unclaim`, so the remaining Phase 1 gaps are less about claim-state mechanics and more about end-to-end Telegram QA, runtime reliability, and catalog completeness
- April 14, 2026 privacy hardening: buyer self-service claim/payment commands now require DM context, which closes the accidental public claim-leak path from discussion comments
- OCR backend sequencing changed: hosted OpenAI OCR is now the primary extraction path, with local Tesseract retained as the safety fallback rather than the default engine
- near-term OCR hardening should focus on prompt/ROI tuning, latency/cost observation, and real-photo regression coverage instead of adding more Tesseract-only heuristics first
- April 21, 2026 OCR update: the primary hosted OCR path is now optimized for one full rectified card image plus Telegram-visible provider/fallback debug, so the next tuning work should focus on real-photo latency and extraction quality rather than more ROI fan-out
- April 21, 2026 latency hardening: the OCR flow now announces `gpt-4o-mini` immediately in Telegram and uses shorter hosted timeout caps before fallback, so the next latency decision is whether hosted game detection still earns its cost versus heuristic-only detection
- April 22, 2026 reliability note: the recent Telegram photo-batch failure was a downstream classifier crash, not an OpenAI auth issue, so current OCR hardening should focus on quality/latency/fallback behavior rather than API-key wiring
- May 12, 2026 OCR simplification: the hosted OCR path now starts from the raw uploaded photo instead of card rectification, so the next decision is whether fallback thresholds should be tightened for cluttered/multi-card images
- May 12, 2026 config hardening: project `.env` values now override stale desktop-shell env values, which removes a major source of misleading live OCR auth failures during local bot testing
- May 12, 2026 backend update: the OCR path is now faster because game detection is heuristic-only, and JP matching is materially stronger because backend tokenization now understands Japanese scripts rather than only Latin OCR tokens
- May 12, 2026 resolver hardening: matching now reconciles structured OCR ratios with the rendered `IDENTIFIER:` text and prefers the more specific explicit ratio, so modern cards like `233/182 Team Rocket's Nidoking ex` should stop collapsing into legacy low-number resolver branches
- May 12, 2026 runtime hardening: local development now runs the polling bot under a `launchd` KeepAlive agent, which materially reduces “bot died again” downtime during live Telegram QA
- May 12, 2026 photo-flow hardening: local heuristic game detection no longer depends on a working Tesseract binary to keep listing/auction photo batches alive, which removes a false “bad photo” failure mode during OpenAI-first OCR runs
- May 12, 2026 auction ops update: seller tools now expose live auction counts, auction-aware inventory/detail screens, and seller-side extend/end controls, which closes one of the biggest auction hardening gaps called out in roadmap notes
- May 12, 2026 auction creation update: `/auction` now captures seller-defined rules and an explicit end time, which makes the owner-facing setup closer to real Telegram auction norms instead of a bare duration-only flow
- May 12, 2026 auction configuration update: sellers can now configure anti-snipe directly during `/auction`, and that setting survives into live bid refreshes because the listing row and render paths now carry `anti_snipe_minutes`
- auction flow is now closer to phase-ready: reserve price, anti-snipe, exact end time, rules, and per-auction payment window are wired; next gaps are polish and seller-config presets rather than core mechanics
