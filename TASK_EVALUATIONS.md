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



## 2026-04-10 — Multi-Candidate OCR And Full-Catalog Matching
- date: 2026-04-10
- task: make OCR resilient when one crop has the right number but another crop has the right name
- goal: correctly resolve real Pokémon photos even when contour detection is imperfect and OCR signals are split across multiple candidate crops
- outcome: added centered fallback card candidates, top-name OCR, cross-candidate signal aggregation, mismatch penalties in fuzzy matching, and fixed Supabase card pagination so the resolver can see all 19,917 imported Pokémon cards
- validation: the same saved real Charizard photo now resolves in code to `Charizard ex Illustration Rare (Paldean Fates)` after OCR + catalog matching; bot restarted cleanly in polling mode
- what went well: the pipeline now behaves like a recognizer instead of a single-pass OCR crop, and the pagination fix removed a major hidden catalog blind spot
- what was weak: OCR still misreads the set code itself (`SEN` vs `PAF`), so the current success depends on combining number + name rather than exact identifier parsing alone
- follow-up: live-test `/list` again on real Telegram photos, then add top-3 candidate UI when confidence stays medium
- confidence: medium



## 2026-04-10 — Auto Game Detection And Safer OCR Matching
- date: 2026-04-10
- task: remove the manual game prompt and stop weak OCR from forcing clearly wrong catalog matches
- goal: auto-detect the game on photo upload, reduce seller friction, and make low-quality OCR fail safe instead of confidently picking random cards
- outcome: `/list` now auto-detects the game on photo upload, weak one-digit / number-only OCR no longer drives fuzzy matches, and the tested Crobat photo now returns `Unknown card` instead of a false `Alakazam` hit
- validation: `python3 -m py_compile handlers/listing.py services/game_detection.py services/ocr.py services/card_identifier.py`; live OCR checks show the Charizard photo resolves while the Crobat photo safely does not match the wrong card
- what went well: seller friction is lower and the matcher now prefers no answer over a bad answer when catalog evidence is weak
- what was weak: auto game detection currently biases toward Pokémon because the One Piece path and catalog are still underbuilt; local Tesseract runtime is still slow on multi-candidate scans
- follow-up: add One Piece-specific OCR/catalog support, then replace slow local OCR with a faster high-accuracy vision path or staged hosted fallback
- confidence: medium



## 2026-04-10 — Claim Wiring And OCR Provider Upgrade Path
- date: 2026-04-10
- task: wire basic comment claims and add an OCR provider path beyond local Tesseract
- goal: make `Claim` comments start doing something on bot-posted listings and prepare a faster/more-accurate OCR option for production
- outcome: added discussion-thread claim handling backed by the existing atomic claim RPC, seller/buyer DM notifications on successful claims, and optional Google Vision OCR support behind the existing `OCR_PROVIDER` config
- validation: `python3 -m py_compile handlers/listing.py handlers/claims.py services/game_detection.py services/ocr.py services/card_identifier.py db/claims.py db/listings.py db/sellers.py`; bot restarted cleanly in polling mode
- what went well: the repo now has a real path for discussion claim handling instead of a placeholder, and OCR can now graduate beyond local Tesseract without changing the listing flow shape
- what was weak: live comment handling still depends on Telegram discussion reply mapping in the deployed chat configuration, and live external pricing is still not fully wired because provider access is missing or anti-bot protected
- follow-up: live-test `Claim` in the linked discussion thread, then either add provider credentials or choose a sanctioned live price source that can be queried reliably from the bot
- confidence: medium



## 2026-04-11 — Live Pokémon Pricing And OCR/Claim Hardening
- date: 2026-04-11
- task: harden modern Pokémon OCR, add real external price references, and make linked-discussion claims easier to resolve
- goal: improve real-photo card identification, stop stale history-only pricing, and reduce silent claim misses in Telegram discussion threads
- outcome: cached full-card catalog reads, improved OCR identifier recovery from noisy bottom-left blobs, safer/less ambiguous catalog matching, Pokémon live price references via Pokémon TCG API + FX conversion, and broader reply-to-listing resolution for discussion-thread claims
- validation: `python -m py_compile main.py config.py handlers/*.py db/*.py services/*.py jobs/*.py utils/*.py scripts/*.py`; local real-photo probes now resolve `Team Rocket's Crobat ex Illustration Rare (Destined Rivals)` from a noisy `234/182` OCR result and return live price references; bot restarted successfully in polling mode
- what went well: the fix targeted the actual failure modes instead of overfitting one crop, and live pricing is now genuinely external for matched Pokémon cards
- what was weak: local Tesseract latency is still noticeable, and linked discussion-thread claim behavior still needs real Telegram verification beyond code-path hardening
- follow-up: live-test `/list` and `Claim` on Telegram, then decide whether to switch production OCR to Google Vision or another faster hosted path
- confidence: medium


## 2026-04-11 — Old-Card Name+Number Shortlist Flow
- date: 2026-04-11
- task: build an era-aware fallback for older Pokémon cards that do not expose OCR-friendly set abbreviations
- goal: use name + printed number to generate candidates for old/icon-era cards without forcing bad auto-matches
- outcome: the matcher now returns ranked candidate options, low-number old-card matches fall back to shortlist mode, and `/list` accepts `1` / `2` / `3` replies to choose one of the suggested candidates directly
- validation: `python -m py_compile main.py config.py handlers/*.py db/*.py services/*.py jobs/*.py utils/*.py scripts/*.py`; local probes show modern `234/182` Crobat still resolves while ambiguous older inputs like `Alakazam 1/06` and `Charizard 4/102` now return top-3 shortlist options instead of a single wrong match
- what went well: the fallback is targeted to the old-card ambiguity problem and preserves the safer modern-number path
- what was weak: shortlist ranking still relies on OCR text only, so some old-card ties will remain unresolved until set-symbol or layout cues are added
- follow-up: add set-symbol/layout disambiguation for old sets and consider inline Telegram buttons instead of numeric replies for shortlist selection
- confidence: high


## 2026-04-11 — Local Bot Process Stability Triage
- date: 2026-04-11
- task: investigate repeated local bot downtime and make Orchids startup less fragile
- goal: determine whether the bot is crashing versus being lost due to local process lifecycle, then relaunch it in a more stable way
- outcome: verified there was no fresh crash trace in app logs, relaunched the bot successfully in detached mode, added pidfile tracking, and updated `.orchids/orchids.json` to start the bot with `nohup` and tail the log instead of relying on a foreground process
- validation: bot restarted successfully and is running as PID from `.logs/bot.pid`; `.logs/bot.out` shows successful polling startup on 2026-04-11
- what went well: this isolated the issue to local runtime/process supervision rather than an application exception path
- what was weak: this is still a local-machine workaround, so sleep, restarts, or Orchids session changes can still interrupt service compared with Railway/webhook hosting
- follow-up: move the bot to a real always-on host with process supervision and webhook delivery
- confidence: high

## 2026-04-11 — Safe Old-Card Set Symbol Reranking
- date: 2026-04-11
- task: add Pokémon set-symbol metadata and use it safely for old-card shortlist ranking
- goal: improve Base/Jungle/Fossil-era disambiguation without introducing more confident wrong matches
- outcome: imported Bulbapedia set symbol/logo URLs into `pokemon_sets`, added a symbol matcher that searches the classic right-side symbol area, limited reranking to ambiguous old-style Pokémon cards, and only applies reordering when symbol evidence is decisive; the local bot was also relaunched cleanly in detached polling mode
- validation: `python -m py_compile main.py config.py handlers/*.py db/*.py services/*.py jobs/*.py utils/*.py scripts/*.py`; smoke tests confirmed modern `234/182` Crobat matching still works and weak symbol evidence no longer reorders the old `4/102 Charizard` shortlist incorrectly; bot log shows startup at `2026-04-11 14:31:05`
- what went well: the matcher is now much safer because weak icon similarity is treated as a hint instead of overriding name+number ranking
- what was weak: real old-card photos are still needed to prove the chosen symbol windows generalize across classic layouts and e-reader/ex-era variants
- follow-up: live-test a few actual Base/Jungle/Fossil/Base Set 2 photos and tune symbol windows or thresholds only if the decisive-rerank rule proves too conservative
- confidence: medium

