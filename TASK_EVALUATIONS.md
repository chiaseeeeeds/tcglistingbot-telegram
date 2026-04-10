# TASK_EVALUATIONS.md — TCG Listing Bot

Use this log after meaningful implementation tasks.

## Review Format
- date:
- task:
- goal:
- outcome:
- validation:
- what went well:
- what was weak:
- follow-up:
- confidence: low / medium / high

---

## 2026-04-09 — Command Stability Recovery
- date: 2026-04-09
- task: restore bot responsiveness for `/commands`
- goal: make the bot consistently respond in DM again
- outcome: fixed polling instability, reduced stale updates, added `/ping`, and enabled conversation re-entry
- validation: live DM testing confirmed `/commands` worked again
- what went well: issue was isolated quickly once hidden duplicate/stale polling behavior was identified
- what was weak: detached background execution in this Orchids runtime is still unreliable
- follow-up: move runtime to Railway or another always-on host
- confidence: high

## 2026-04-09 — Photo-First Listing Flow Foundation
- date: 2026-04-09
- task: shift `/list` away from manual title-first intake
- goal: accept a photo first, run OCR, suggest a title, then ask price after references
- outcome: `/list` now begins with a photo, runs Tesseract OCR, attempts local card matching, shows best-effort price references, and posts with the uploaded image
- validation: code compiled successfully; live Telegram retest required for full flow confirmation
- what went well: flow now matches the intended seller mental model much better
- what was weak: live website price providers are not fully wired yet; current references rely on internal bot history when available
- follow-up: integrate external price providers and front/back image support
- confidence: medium


## 2026-04-09 — OCR Identifier Tuning
- date: 2026-04-09
- task: improve OCR for Japanese cards and printed card identifiers
- goal: better detect lower-card set code and printed number such as `PAF EN 234/091`
- outcome: added multi-pass Tesseract OCR, lower-left and bottom-strip crops, and stronger identifier extraction in matching
- validation: language pack verification confirmed `jpn` and `jpn_vert` are installed; live Telegram retest is next
- what went well: the pipeline now targets the area where printed identifiers usually live instead of relying only on full-image OCR
- what was weak: local catalog coverage is still sparse, so identifier extraction may work before full card auto-match does
- follow-up: expand catalog imports and add OCR debug snapshots for failed cards
- confidence: medium


## 2026-04-09 — OCR Lane Separation
- date: 2026-04-09
- task: separate identifier OCR from JP name OCR
- goal: stop JP OCR from polluting English lower-left set code / card number extraction
- outcome: bottom-left identifier OCR now runs English-only with a strict alphanumeric whitelist; JP OCR is kept for broader name text only
- validation: code compiled and bot restarted successfully; live Telegram retest is next
- what went well: this matches the actual structure of TCG cards better than mixed-language full-image OCR
- what was weak: exact crop ratios may still need tuning across different photo framing styles
- follow-up: add OCR debug output for identifier lane and support seller-submitted tighter crops when needed
- confidence: medium


## 2026-04-09 — PriceCharting Catalog Staging Import
- date: 2026-04-09
- task: add a bulk PriceCharting catalog ingest path
- goal: preserve external catalog data for later mapping into the bot's normalized `cards` table
- outcome: added a staging table migration, CSV import script, and import workflow documentation
- validation: importer script compiled successfully
- what went well: avoids unsafe assumptions about PriceCharting field structure by storing raw payloads first
- what was weak: still requires a downloaded PriceCharting CSV export and a follow-up resolver to map staged rows into `cards`
- follow-up: apply the migration, import a real CSV export, then build the Pokémon resolver from staged rows
- confidence: medium


## 2026-04-09 — Pokémon EN Catalog Pipeline
- date: 2026-04-09
- task: build a real Pokémon EN catalog pipeline from Bulbapedia + Pokemon-Card-CSV
- goal: create resolver-friendly set metadata and card rows for OCR-based identifier matching
- outcome: added `pokemon_sets`, `pokemon_cards_staging`, Bulbapedia importer, Pokémon CSV importer, and normalization docs
- validation: Bulbapedia parser returns 179 set rows; set mapping dry run resolves 163 of 172 CSV files; live import has started populating staging and `cards`
- what went well: the two-source architecture cleanly separates set-code mapping from card-row ingestion
- what was weak: the full bulk import is still relatively slow and a handful of set aliases still need tuning
- follow-up: finish the full import, review unresolved aliases, then connect OCR resolution to `pokemon_sets` + `cards`
- confidence: medium


## 2026-04-09 — Pokémon EN Alias Completion
- date: 2026-04-09
- task: close the remaining set-name resolution gaps between Bulbapedia and Pokemon-Card-CSV
- goal: get full set mapping coverage before OCR resolver hookup
- outcome: explicit alias rules now resolve all 172 CSV files to a set mapping
- validation: dry run reports `resolved 172 unresolved 0`
- what went well: most remaining gaps were naming-style mismatches rather than missing catalog data
- what was weak: the full importer is still slower than expected and needs better commit/progress behavior
- follow-up: optimize the bulk importer, finish the clean load, then connect OCR lookup to `cards`
- confidence: high


## 2026-04-09 — PRD Gap Checklist and Roadmap
- date: 2026-04-09
- task: compare current build against the repo PRD and turn the result into execution docs
- goal: create a shared, repo-native checklist and phased roadmap instead of relying on chat memory
- outcome: added `TODO.md` as the PRD gap checklist and `ROADMAP.md` as the phased delivery plan
- validation: docs written and linked into project memory
- what went well: gives a clear sequence that matches the product guardrails and current implementation state
- what was weak: status still depends on the in-flight Pokémon EN import finishing cleanly
- follow-up: use `TODO.md` and `ROADMAP.md` as the primary planning surface for the next implementation phases
- confidence: high

## 2026-04-10 — Pokémon EN Catalog Completion
- date: 2026-04-10
- task: finish the clean Pokémon EN catalog load into `pokemon_cards_staging` and `cards`
- goal: fully import the Pokemon-Card-CSV source into Supabase with stable set mapping and identity normalization
- outcome: completed 172/172 source file import, loaded 20,202 staging rows, and materialized 19,917 distinct Pokémon card identities with zero unresolved set codes and zero unlinked normalized rows
- validation: final DB checks confirmed `source_files=172`, `unresolved_rows=0`, `null_normalized_rows=0`, `distinct_card_identities_in_staging=19917`, and `duplicate_live_identities=0`
- what went well: set-based SQL upserts plus per-file resumable execution turned an unstable bulk import into a finishable workflow
- what was weak: long-lived bulk DB sessions remained fragile against transient network failures, so a one-file-per-process fallback was needed to finish reliably
- follow-up: point the OCR resolver at the completed Pokémon EN catalog and add a first-class import report script
- confidence: high


## 2026-04-10 — OCR To Catalog Resolver Wiring
- date: 2026-04-10
- task: connect `/list` identifier OCR and manual fallback to the imported Pokémon EN `cards` catalog
- goal: resolve cards by printed identifier before falling back to manual title entry
- outcome: added DB-backed exact lookup by `set_code + card_number`, kept fuzzy catalog matching as fallback, and updated `/list` so sellers can reply with identifiers like `PAF 234/091` when OCR is uncertain
- validation: direct resolver checks matched `PAF 234/091`, `WHT 050/086`, `BLK 060/086`, and `SSP 001/191` against live catalog rows
- what went well: the completed catalog made exact identifier matching straightforward and much more reliable than token-only fuzzy search
- what was weak: live Telegram retest is still needed to tune conversational UX and confidence thresholds with real seller photos
- follow-up: test `/list` live with Pokémon EN cards, then tie pricing to resolved card identity
- confidence: medium


## 2026-04-10 — Card-Aware Price References
- date: 2026-04-10
- task: make `/list` pricing prefer resolved card identity instead of title-only matching
- goal: show sellers tighter history-based price references once OCR/manual identifier resolution finds a `card_id`
- outcome: updated price lookup to query exact `listings.card_id` history first, then gracefully fall back to title matching when exact-card history does not exist yet
- validation: code compiled successfully and direct service checks returned cleanly for exact-card and fallback inputs
- what went well: the change stayed small because `listing_card_id` was already flowing through the conversation state
- what was weak: there is still little or no historical listing data for many exact cards, so most sellers will still see empty refs until more listings accumulate or external providers are added
- follow-up: integrate external pricing providers and add live Telegram flow testing with resolved Pokémon cards
- confidence: high


## 2026-04-10 — Product Status Checklist
- date: 2026-04-10
- task: summarize the bot into a plain-language readiness checklist
- goal: make it easy to see what works now, what is partial, what is missing, and what comes next
- outcome: added `STATUS.md` with working-now, partial, missing, and next-milestone sections
- validation: checklist content matches current `TODO.md` and `MEMORY.md` state
- what went well: turns a large feature set into a practical operator-facing snapshot
- what was weak: status still depends on live Telegram testing for real-world OCR quality
- follow-up: keep `STATUS.md` updated after each major milestone
- confidence: high


## 2026-04-10 — Bottom-Left OCR Hard Focus
- date: 2026-04-10
- task: force OCR and matching to focus on the bottom-left printed identifier lane
- goal: stop false matches caused by stray full-card text such as a lone `N`
- outcome: narrowed OCR crops to tighter bottom-left regions, removed broader name OCR from the live matching payload, and ignored one-letter alphabetic tokens in fuzzy matching
- validation: `python3 -m py_compile services/ocr.py services/card_identifier.py handlers/listing.py main.py`; bot restarted cleanly in polling mode
- what went well: the change attacks both sources of bad matches: noisy crop area and overly permissive token overlap
- what was weak: live Telegram retesting on real photos is still needed to tune the exact crop ratios
- follow-up: test `/list` on several Pokémon EN cards and inspect failed identifiers to tune crop bounds again if needed
- confidence: medium



## 2026-04-10 — Card Rectification OCR Pipeline
- date: 2026-04-10
- task: replace raw-photo bottom-left OCR with card-detected, rectified, card-relative OCR
- goal: stop reading the playmat/background and make the identifier zone relative to the actual card
- outcome: added OpenCV-based card detection and perspective rectification, moved OCR to run after game selection, introduced Pokémon-specific identifier ROI windows on normalized cards, and saved OCR debug artifacts locally for failed tuning sessions
- validation: `python3 -m py_compile services/card_detection.py services/ocr.py services/card_identifier.py handlers/listing.py`; synthetic end-to-end smoke test extracted `IDENTIFIER: PAF234/091`; bot restarted cleanly in polling mode
- what went well: the architecture now matches the real problem by converting raw photos into card-relative coordinate space before OCR
- what was weak: real-user photos still need live tuning for crop windows, glare, and edge cases where contour detection is imperfect
- follow-up: test `/list` on several real Pokémon cards and inspect saved debug artifacts for any misses before adding top-3 candidate selection
- confidence: medium

