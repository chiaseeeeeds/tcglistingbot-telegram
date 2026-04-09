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
