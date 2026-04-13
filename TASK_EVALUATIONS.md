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
- user_response: positive / mixed / frustrated / blocked

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

## 2026-04-11 — OCR Latency Reduction Pass
- date: 2026-04-11
- task: reduce `/list` OCR latency without giving up the Crobat-style recovery path
- goal: make photo OCR feel meaningfully faster while preserving the current name + printed-number matching quality
- outcome: removed duplicate OCR-based candidate ranking, limited finalist scoring to the strongest crop candidates, added early exits when a crop already yields decisive identifier + name signals, and trimmed redundant Tesseract pass variants
- validation: `python -m py_compile services/ocr.py`; three-run local timing on the saved Crobat photo produced about `9.82s`, `4.25s`, and `4.27s` with the same OCR text (`IDENTIFIER: 234/182 | NAME_EN: Loananall att oo BleamiRocket`); bot restarted successfully at `2026-04-11 15:08:13`
- what went well: the largest waste was duplicate OCR work, so removing it improved latency immediately without changing the higher-level matching contract
- what was weak: cold-start latency is still noticeable, and older-card photos with weak first-crop results may still need the fallback crop to keep accuracy high
- follow-up: live-test the bot on a few real user photos and consider optional caching or a hosted OCR provider if cold-start latency still feels too slow
- confidence: high

## 2026-04-11 — Nidoking Merged-Name Matcher Recovery
- date: 2026-04-11
- task: recover modern Pokémon matches when OCR glues the card name into one noisy token
- goal: make strings like `ortNidoKine` still resolve to `Nidoking` when the printed number is strong
- outcome: added a targeted merged-name rescue path in `services/card_identifier.py` so long OCR tokens can still contribute a name signal; confirmed `IDENTIFIER: 233/182 | NAME_EN: ortNidoKine` now resolves to `Team Rocket's Nidoking ex Illustration Rare (Destined Rivals)` and restarted the live bot process with the updated code
- validation: `python -m py_compile services/card_identifier.py`; direct matcher checks now resolve both `233/182` Nidoking and `234/182` Crobat correctly; bot restarted successfully at `2026-04-11 15:40:27`
- what went well: the fix is narrow and uses the printed number to keep the added name fuzziness safe
- what was weak: this still depends on OCR getting at least a roughly card-like long token; fully mangled names may still fail
- follow-up: live-test the same Nidoking photo in Telegram and tune the merged-token threshold only if we see new false positives
- confidence: high



## 2026-04-12 — Resolver Path Transparency And Live Bot Reality Check
- date: 2026-04-12
- task: stop guessing about the Nidoking OCR failure and expose the real live resolver path
- goal: make the exact Telegram reply explain which resolver ran, whether the matcher actually produced candidates, and whether the live bot is using current code
- outcome: added resolver-path metadata to card identification results, fixed `/list` so the admin debug block is actually included in Telegram replies, revalidated the exact Nidoking/Crobat/Charizard OCR strings locally, and relaunched the bot in a persistent PTY after detached startup kept dying in this harness
- validation: `python3 -m py_compile services/card_identifier.py handlers/listing.py`; direct regression checks now resolve `IDENTIFIER: 233/182 | NAME_EN: ortNidoKine` to `Team Rocket's Nidoking ex Illustration Rare (Destined Rivals)`, `234/182 + BleamiRocket` to Crobat, and `PAF 234/091 + Charizard ex` to Paldean Fates Charizard
- what went well: this changes the debugging loop from speculation to evidence because the live Telegram response can now show the actual resolver path and candidate count
- what was weak: the user experience up to this point was poor because earlier turns overclaimed fixes before the live reply changed, and detached local process management is still flaky in Orchids
- follow-up: have the user send the same Nidoking photo once more and verify the reply now includes the debug block plus the resolved modern-identifier path before making any further OCR heuristics changes
- user reaction: frustrated that repeated claims of a fix did not change the Telegram output; this entry reflects that outcome rather than model confidence


## 2026-04-12 — Catalog Pagination Root Cause Fix
- date: 2026-04-12
- task: explain why Telegram still missed Nidoking even when the OCR string and local matcher looked correct
- goal: find the real production-path cause instead of adding more OCR heuristics blindly
- outcome: instrumented resolver-side diagnostics, discovered catalog pagination was nondeterministic because `db/cards.py` used `.range(...)` without a stable `.order(...)`, fixed the query to `.order('id')`, bumped the live build marker to `ocr-build-2026-04-12-pagination-fix-v4`, and restarted the bot cleanly in a single live PTY session
- validation: repeated fresh-process probes now consistently resolve `IDENTIFIER: 233/182 | NAME_EN: ortNidoKine` to `Team Rocket's Nidoking ex Illustration Rare (Destined Rivals)` with `resolver=pokemon_modern_identifier_first`; lock holder is a single current bot process after restart
- what went well: the added debug metadata turned a vague OCR complaint into a concrete data-access bug with a reproducible root cause
- what was weak: the user lost time because the earlier investigation focused on OCR confidence before proving the catalog paging path was deterministic
- follow-up: have the user resend the same photo and confirm the reply now shows build `ocr-build-2026-04-12-pagination-fix-v4` and resolves the card correctly before making any new OCR changes
- user reaction: frustrated, rightly, because the same bad Telegram reply persisted; this root-cause fix is aimed directly at that mismatch


## 2026-04-12 — OCR ROI And Ratio Selection Fix
- date: 2026-04-12
- task: improve OCR itself after a new Lucario photo proved the bot was still reading the wrong identifier from foil-heavy text
- goal: make the OCR pipeline read real name/number text better without any per-card hardcoding
- outcome: found that the Pokémon title ROI was too high and the identifier pass over-weighted a thresholded crop that hallucinated `797/732`; updated the OCR pipeline to use lower name windows, softer identifier preprocessing, more Tesseract pass variants, explicit-only set-code extraction, and ratio plausibility scoring so `179/132` wins over implausible noisy ratios
- validation: local run on the attached image now returns `IDENTIFIER: 179/132 | NAME_EN: ... Mega Lucario` and the resolver matches `Mega Lucario ex Illustration Rare (Mega Evolution)`; live bot restarted on build `ocr-build-2026-04-12-ocr-window-fix-v5`
- what went well: this was a real OCR improvement, not a matcher shortcut, and it should help other foil-heavy older Pokémon cards too
- what was weak: card isolation still falls back to center crops on some otherwise clean photos, so there is still headroom in `services/card_detection.py`
- follow-up: retest the Lucario photo live, then improve card detection so fewer photos depend on fallback center crops
- user reaction: explicitly rejected any hardcoded image identification and asked for OCR quality to improve instead; this work follows that requirement directly


## 2026-04-12 — Hardcoding Audit And Prompt Cleanup
- date: 2026-04-12
- task: evaluate whether the identification system contains hardcoded card matches and remove them if present
- goal: ensure card resolution stays driven by OCR text plus catalog data rather than hidden per-card shortcuts
- outcome: audited the runtime OCR and resolver codepaths and found no literal per-card title hardcodes in product logic; cleaned up the remaining user-facing example identifiers so prompts now use the generic placeholder `ABC 123/456` instead of a real card code
- validation: repository search found no runtime product code referencing specific card titles like Nidoking, Crobat, Lucario, or Charizard for matching; `python3 -m py_compile handlers/listing.py services/card_identifier.py services/ocr.py db/cards.py` passed
- what went well: this makes the system easier to reason about because specific card examples are no longer mixed into the live seller flow
- what was weak: the resolver still contains domain heuristics for Pokémon OCR quality, which are generic but can still feel overfit when they are not clearly explained
- follow-up: if desired, the next cleanup pass should separate generic OCR configuration from game-specific resolver policy into explicit config blocks so the behavior is more auditable
- user reaction: concerned that successful matches were coming from hidden hardcoded identification; this audit directly addressed that concern


## 2026-04-12 — Generic Overmatch Guard
- date: 2026-04-12
- task: tighten the resolver after the hardcoding audit exposed that fake placeholder OCR could still overmatch a random card
- goal: prevent the generic matcher from looking like hidden hardcoding by refusing weak set-code-mismatch matches
- outcome: added a guard in `services/card_identifier.py` so when OCR claims a set code but the best catalog hit is from another set, the bot now returns no match unless there is genuinely strong name evidence
- validation: `IDENTIFIER: ABC 123/456 | NAME_EN: Placeholder` now returns `generic_set_code_mismatch_guard` instead of matching `Rosa's Encouragement`, while the validated Nidoking and Mega Lucario cases still resolve correctly; live bot restarted on build `ocr-build-2026-04-12-hardcoding-audit-v6`
- what went well: this reduces hallucinated matches and makes the system's behavior better aligned with the user's no-hardcoding requirement
- what was weak: the resolver still depends on heuristics rather than a formal confidence model, so there is still room to make the policy cleaner and more auditable
- follow-up: if desired, the next step should be to centralize resolver policy thresholds in config so OCR extraction and catalog decisioning are easier to inspect separately
- user reaction: wanted reassurance that wins were coming from OCR plus catalog evidence rather than hidden hardcoded card IDs; this guard directly reduces that failure mode


## 2026-04-12 — Pricing Source Audit And Button Selection
- date: 2026-04-12
- task: explain why PriceCharting no longer appears and improve the seller pricing UX
- goal: identify the actual source gap and replace manual price typing with quick source-selection buttons
- outcome: confirmed that PriceCharting is not live in the current stack because `services/pricecharting.py` is still only a scaffold and the `cards` catalog has 0 populated `pricecharting_id` rows; added inline Telegram buttons so sellers can tap a returned price reference or choose custom pricing during `/list`; listing persistence now also has hooks for `pricecharting_price_sgd` and `yuyutei_price_sgd` when those sources are restored
- validation: repository/runtime checks confirmed no live PriceCharting source path and 0 populated `pricecharting_id` rows; local smoke check verified callback data generation for the new price buttons and `python3 -m py_compile handlers/listing.py db/listings.py services/price_lookup.py` passed; live bot restarted on build `ocr-build-2026-04-12-price-buttons-v7`
- what went well: the pricing UX is materially better now even before adding more sources because sellers can use source prices with one tap
- what was weak: PriceCharting itself is still absent, so this is a UX improvement plus source audit, not a full source restoration
- follow-up: if PriceCharting needs to come back, the next task is to decide whether to restore it from imported IDs/data or build a sanctioned live lookup path instead of leaving the scaffold unused
- user reaction: noticed that sources had regressed and explicitly asked for button selectors for pricing; this task addressed both points directly

## 2026-04-12 — Generic Set Alias Resolution And Live PriceCharting Path
- date: 2026-04-12
- task: remove another hidden resolver failure mode and restore a real PriceCharting integration path
- goal: keep identification generic and catalog-driven while making pricing sources/buttons work in the actual Telegram flow
- outcome: fixed a generic Pokémon set-name gap by matching separator-derived aliases from catalog metadata, so OCR like `Phantasmal Flames 130/94` now resolves to the correct `PFL` card without any per-card hardcoding; wired the missing inline price keyboard into `/list`; upgraded `services/pricecharting.py` from a scaffold into a real token-first + Scrapling-fallback lookup path; added `PRICECHARTING_API_TOKEN` to env examples; and restarted the bot after clearing a stale single-instance lock
- validation: `python -m py_compile` passed for the updated resolver/pricing files; direct live probes now resolve `233/182 + ortNidoKine`, `179/132 + Mega Lucario`, and `130/94 + Phantasmal Flames` correctly while `ABC 123/456` still fails safe; live bot restarted successfully and logged `Bot ready as @TCGlistingbot` at 2026-04-12 01:52 local time
- what went well: the fix addressed a real catalog-normalization bug instead of papering over one bad card, and the price buttons now actually reach the seller UI
- what was weak: public PriceCharting scraping is still constrained by Cloudflare in this environment, so the sanctioned API token path is the only reliable live source today
- follow-up: if PriceCharting is mission-critical, the next step is to add a real `PRICECHARTING_API_TOKEN` and validate one live lookup end-to-end in Telegram; separately, consider resolving the PTB `per_message` callback warning if the price buttons behave inconsistently in live chat
- user reaction: explicitly rejected hardcoded identification and asked for a real pricing source plus button selectors; this task aligned the implementation with that expectation

## 2026-04-12 — Full Set Alias Mapping Audit And Name+Number Priority
- date: 2026-04-12
- task: make Pokémon set mapping generic and reliable while shifting identification priority toward exact card name plus printed number
- goal: ensure printed-card abbreviations like `PFL` and `ASC` are reached through correct generic set-name mapping, and reduce dependence on broad series matching in OCR resolution
- outcome: upgraded the Pokémon CSV import mapping to use generic suffix-aware set aliases from catalog metadata instead of depending mainly on manual exceptions; verified `Phantasmal Flames -> PFL`, `Ascended Heroes -> ASC`, and umbrella/base sets like `Black & White -> BLW`; audited all 172 current Pokémon CSV files and reduced unmapped sets to 0; also increased generic resolver weight for strong `exact name + printed number` evidence so card identity wins earlier when OCR captures both pieces
- validation: `python -m py_compile scripts/import_pokemon_card_csv.py services/card_identifier.py` passed; direct checks confirmed `Phantasmal Flames`, `Ascended Heroes`, `Mega Evolution`, `Black and White`, `Diamond and Pearl`, `Platinum`, `Sun and Moon`, `Sword and Shield`, and `Scarlet and Violet` all resolve to the expected set codes; full CSV audit reported `csv_files=172` and `unmapped=0`; bot restarted successfully and logged ready at 2026-04-12 02:01 local time
- what went well: the fix is generic rather than a growing pile of one-off maps, and the validation covered the full imported EN source set list instead of only hand-picked examples
- what was weak: this audit only covers the current English source pipeline; Japanese set imports and their aliases are still not present in the catalog yet
- follow-up: when JP imports are added, reuse the same suffix-alias strategy and run the same full-source audit so JP set codes and aliases are equally deterministic
- user reaction: explicitly wanted abbreviation-correct set mapping and a matcher that leans on `name + number` instead of vague series dependence; this work directly aligned the system with that requirement

## 2026-04-12 — TCG Catalog Integrity Skill
- date: 2026-04-12
- task: package the anti-hardcoding OCR/catalog rules and source links into a reusable repo-local skill
- goal: make future sessions follow the same no-hardcoding, generic alias mapping, and source-priority rules without re-explaining them each time
- outcome: added `skills/tcg-catalog-integrity/SKILL.md` plus `skills/tcg-catalog-integrity/references/source_links.md`; the skill defines disallowed hardcoding patterns, approved generic resolver patterns, validation workflow, set-mapping rules, pricing source priority, and includes the requested external links such as CLI-Anything and Scrapling
- validation: reviewed the generated skill files locally and confirmed they are concise, repo-relevant, and directly aligned with the user's stated constraints about OCR, set abbreviations, and non-hardcoded behavior
- what went well: this captures the product-specific matching philosophy in one reusable place instead of scattering it across chat history
- what was weak: repo-local skills are only useful when future agents read/use them, so this helps guidance but does not itself change runtime logic
- follow-up: if desired, add a second skill specifically for JP Pokémon import workflow once that pipeline is built
- user reaction: wanted the anti-hardcoding rules and source-selection guidance implemented as a skill; this does exactly that

## 2026-04-12 — Noisy Set-Code Recovery And Unique Ratio Match
- date: 2026-04-12
- task: fix a bad live OCR result where a gold Pokémon card with visible `PFL 130/094` still surfaced `Aerodactyl (Team Up)` as the shortlist top hit
- goal: make the resolver trust generic OCR evidence more intelligently without adding any per-card exception logic
- outcome: reproduced the exact image locally, confirmed OCR debug artifacts already contained noisy `PFLEN ... 130/094` chunks, strengthened set-code extraction in `services/ocr.py` to recover known codes from noisy alphanumeric identifier text near the ratio, and added a generic `unique_print_ratio_match` resolver path so a unique `left-number + printed total` catalog hit resolves directly instead of drifting to same-number cards from unrelated sets
- validation: local run on the attached image now returns `IDENTIFIER: PFL 130/094 | ...` and resolves to `Mega Charizard X ex (Phantasmal Flames)` with `resolver=exact_identifier`; `python -m py_compile handlers/listing.py services/ocr.py services/card_identifier.py` passed; live bot restarted successfully and logged ready at 2026-04-12 02:07 local time
- what went well: the fix came from OCR/debug evidence already present in the system and improves an entire class of noisy foil-card identifier reads rather than hardcoding a single card
- what was weak: the visible listing build marker had lagged behind the real OCR/service changes and needed to be bumped so live debugging remains trustworthy
- follow-up: retest the same photo live and then stress-test more cards where the set code is partially visible but noisy, especially foil cards with tiny bottom-left abbreviations
- user reaction: rightly called the previous result "really bad" because the printed ratio should not have ended at `Aerodactyl`; this task specifically addressed that generic failure mode

## 2026-04-12 — OCR Resolver Evaluation Harness
- date: 2026-04-12
- task: stop relying on user-reported examples by building a reusable evaluation pipeline for OCR and resolver behavior
- goal: make regressions and class-level failures visible through a manifest plus synthetic catalog audits instead of waiting for live chat complaints
- outcome: added `scripts/evaluate_ocr_resolver.py` and `eval_cases/ocr_resolver_cases.json`; the script evaluates manifest cases and synthetic Pokémon catalog cases, reports pass/fail summaries plus failure reasons, and can emit JSON reports; while exercising synthetic cases it also exposed a generic parser bug, which was fixed by allowing digit-containing set codes like `B2` in `services/card_identifier.py`
- validation: `python -m py_compile scripts/evaluate_ocr_resolver.py services/card_identifier.py` passed; seeded regression run passed `5/5`; synthetic cross-set smoke run passed `20/20`; bot restarted successfully and logged ready at 2026-04-12 02:20 local time
- what went well: this changes the workflow from reactive patching toward repeatable evaluation, and it already surfaced one parser issue without the user needing to find it manually
- what was weak: full synthetic sweeps are still relatively slow, and promo/alphanumeric identifier formats are not yet covered by the current numeric-focused synthetic generator
- follow-up: add progress output and batching to the evaluator for larger full-catalog runs, then add a second audit mode for promo/alphanumeric identifiers like `BW95` and `TG28`
- user reaction: explicitly said they should not have to keep doing the legwork of finding examples; this harness is the first concrete step toward fixing that process problem

## 2026-04-12 — Documentation Update Rule Tightening
- date: 2026-04-12
- task: make post-task documentation updates explicit in repo instructions
- goal: ensure future work sessions consistently update the operational docs, not just memory and task notes
- outcome: updated `AGENTS.md` so meaningful implementation work now explicitly requires reviewing and updating `TODO.md` and `ROADMAP.md` whenever gaps, priorities, readiness, or sequencing have changed
- validation: confirmed the new instruction block is present in `AGENTS.md` under `Project Memory And Review`
- what went well: this turns an implied expectation into a written repo rule
- what was weak: the rule helps future behavior but does not retroactively fix older sessions that missed those doc updates
- follow-up: none beyond following the rule consistently
- user reaction: explicitly requested that `TODO.md` and `ROADMAP.md` always be updated when necessary; this change captures that requirement in the repo instructions
- date: 2026-04-12
- goal: remove anything that looked like runtime hardcoding in OCR evaluation and fix the attached old-card Electrode miss generically
- outcome: audited the live OCR/resolver path, removed the repo-shipped `eval_cases/ocr_resolver_cases.json` manifest so evaluation is synthetic-first, cached Pokémon set card counts in `services/card_identifier.py` to eliminate hot-loop metadata queries, and strengthened the generic `nearby_ratio_name_match` scorer so old cards can resolve from `printed total + nearby ratio + fuzzy name` evidence without any per-card mapping
- validation: `.venv/bin/python -m py_compile services/card_identifier.py services/ocr.py handlers/listing.py` passed; local end-to-end run on `/var/folders/x9/ffgkn9zj5f96zsngx6n5pqm00000gn/T/orchids-local-attachments/e96e1db7-5b36-4dee-b14c-79d8cb26b95b-kdcGBo/1-photo_2026-04-12-15.42.03-1775997732316.jpeg` returned `IDENTIFIER: 3/101 | NAME_EN: lectrode oe fFd` and still resolved to `Electrode Holo (Hidden Legends)` with `resolver=nearby_ratio_name_match` in about `0.8s` for identification after OCR
- what was weak: OCR still misread the visible `5/101` as `3/101`, so the current win is a generic resolver rescue rather than a complete OCR-digit fix
- follow-up: keep improving legacy bottom-right ratio OCR for old cards, then add synthetic or bucketed audits for promo/alphanumeric identifiers and glare-heavy photos
- user reaction: explicitly rejected anything that smelled like hardcoding, including repo-shipped named eval cases, so the fix had to stay generic both at runtime and in evaluation artifacts
- date: 2026-04-12
- goal: improve the OCR digit read itself for old Pokémon cards so the bottom-right printed ratio is read correctly instead of relying mainly on resolver rescue
- outcome: tightened the generic legacy Pokémon ratio OCR in `services/ocr.py` by switching from one broad bottom-right crop to several narrower bottom-right windows, and added generic compact recovery for clean 4-digit old-card reads like `5101 -> 5/101` when the last three digits form a plausible printed total
- validation: `.venv/bin/python -m py_compile services/ocr.py handlers/listing.py services/card_identifier.py` passed; direct OCR probes on `/var/folders/x9/ffgkn9zj5f96zsngx6n5pqm00000gn/T/tcg-listing-bot-ocr-debug/1-photo_2026-04-12-15.42.03-1775997732316/detected_canny/card.png` now yield repeated `5/101` hits from the legacy pass; `_score_candidate(...)` now emits `IDENTIFIER: 5/101 | NAME_EN: lectrode oe fFd` for that saved card crop, while modern debug crops still emit `PFL 130/094` and `179/132`
- what was weak: the original full user attachment had already expired from the temp directory, so validation used the saved normalized debug crop rather than the raw incoming photo file
- follow-up: re-run the same live photo through Telegram to confirm the full bot path now surfaces `5/101` in the seller-facing OCR text, then continue with foil/glare robustness and promo/alphanumeric identifiers
- user reaction: explicitly asked to improve the OCR itself, not just rely on the resolver, so this change targets the raw identifier read path directly
- date: 2026-04-12
- goal: explain why the user was still receiving old `v7` OCR replies after newer OCR fixes had already been implemented
- outcome: traced the mismatch to a stale polling process started around 1:32 AM on April 12, 2026 that was still handling Telegram updates with old code; killed all `main.py` bot processes, cleared the stale lock/pid files, and restarted a single clean poller so the active bot now serves the current OCR build
- validation: before the fix, `ps aux` showed an older `/Python -u main.py` process with long elapsed time while the user-facing output still reported `ocr-build-2026-04-12-price-buttons-v7`; after the fix, only one fresh `main.py` process remained and `.logs/bot.out` logged `Bot ready as @TCGlistingbot` at `2026-04-12 19:07:09` local time
- what was weak: the local startup flow allowed a stale manual poller to survive across work sessions, so restarting from the repo alone was not enough to guarantee that Telegram was hitting the newest code
- follow-up: keep using a full `pkill -f 'main.py'` cleanup before restarting during live debugging, and consider tightening the single-instance guard so stale external pollers are surfaced more aggressively
- user reaction: frustrated because the pasted reply clearly proved the old build was still answering, which was correct; the fix needed to address the running process state, not just the source files
- date: 2026-04-12
- goal: recover the bot after the user reported it was still down even after a restart
- outcome: confirmed the earlier background-launched process was no longer running, then started the bot directly in-process and verified it stayed alive; refreshed `.logs/bot.pid` to the real live process so the runtime state matched reality again
- validation: direct foreground start reached `Bot ready as @TCGlistingbot` at `2026-04-12 21:21:33` local time and remained running; current live pid was refreshed to `96425` and `ps` confirmed the process stayed alive beyond startup
- what was weak: the pid file had drifted from the real process state, which made the restart status look healthier than it really was
- follow-up: if this recurs, replace the ad hoc restart flow with a small checked launcher script that verifies the process remains alive for a short grace period before reporting success
- user reaction: reported the bot was still down, which was accurate; the previous restart confirmation was not sufficient because it relied on startup logs instead of sustained liveness
- date: 2026-04-12
- goal: fix the generic Medicham shortlist miss where OCR correctly read `186/203` but the resolver suggested unrelated non-Evolving-Skies Medicham cards
- outcome: found a generic parser bug in `services/card_identifier.py` where `_SET_BLOCK_RE` could misread the leading digits of a plain ratio like `186/203` as a fake set code (`18`) and then downgrade the real ratio to `6/203`; digit-only set-code captures are now ignored so plain numeric ratios remain intact and can flow into unique printed-ratio resolution
- validation: local run on `/var/folders/x9/ffgkn9zj5f96zsngx6n5pqm00000gn/T/orchids-local-attachments/9dbd0ab9-11e4-45f8-987f-10386bffd976-1HWkA0/1-photo_2026-04-12-21.36.48-1776019015406.jpeg` now returns `IDENTIFIER: 186/203 | NAME_EN: Medicham sa` and resolves to `Medicham V (Evolving Skies)` with `resolver=unique_print_ratio_match`; `python -m py_compile services/card_identifier.py` passed
- what was weak: OCR still drops the trailing `V` from the card name text, but the printed ratio is now preserved correctly so the generic ratio resolver can still identify the right card
- follow-up: add a synthetic evaluation case class for digit-only false set-code captures so regressions like `186/203 -> 18 + 6/203` are caught automatically
- user reaction: correctly pointed out that the shortlist was obviously wrong because Evolving Skies was missing despite the printed number pointing there; the fix had to target the generic ratio parser, not ranking cosmetics
- date: 2026-04-12
- goal: convert the user's architecture feedback into a concrete repo plan instead of continuing ad hoc OCR/resolver patching
- outcome: wrote `OCR_ARCHITECTURE_RESET.md`, which defines the intended end-state: structured OCR signal extraction, generic catalog candidate generation, one unified evidence scorer, honest abstention, and evaluation by failure class instead of named examples; updated `TODO.md`, `ROADMAP.md`, and `MEMORY.md` so future work is directed by that architecture reset rather than by accumulating rescue heuristics
- validation: reviewed the reset plan locally to ensure it stays aligned with the user's stated constraints: no per-card hardcoding, no example-shaped runtime behavior, broader evaluation, and production trust over fragile single-image wins
- what was weak: this is a planning/reset artifact, not yet the code refactor itself
- follow-up: implement Phase A from `OCR_ARCHITECTURE_RESET.md` next by defining the structured OCR signal schema and migrating current OCR outputs into it
- user reaction: made clear that the real end goal is a robust generalized OCR + catalog engine, not a resolver that keeps getting shaped by reported misses; this reset captures that explicitly
- date: 2026-04-12
- goal: start Phase A of the OCR architecture reset by introducing structured OCR signals without breaking the current bot flow
- outcome: added `services/ocr_signals.py` with `OCRSignal` and `OCRStructuredResult`; updated `services/ocr.py` so the OCR pipeline now emits a structured signal object alongside the legacy merged OCR text; wired `handlers/listing.py` to persist the structured OCR payload in conversation state while keeping the seller-facing behavior unchanged
- validation: `python -m py_compile services/ocr_signals.py services/ocr.py handlers/listing.py` passed; direct structured-output probes on saved debug crops showed `pokemon_legacy_bottom_right` with `printed_ratio=5/101` for the Electrode sample and `pokemon_modern_identifier_zone` with `set_code_text=PFL` plus `printed_ratio=130/094` for the modern Charizard sample
- what was weak: the matcher still consumes the legacy merged OCR text today, so this is an interface-layer start rather than the full candidate-generation/scoring refactor
- follow-up: implement the next Phase A slice by teaching the identification layer to consume structured OCR signals directly instead of reparsing the merged OCR string
- user reaction: asked to start the architecture reset immediately; this begins the shift away from text-only OCR handling and toward the generalized pipeline they want
- date: 2026-04-12
- goal: complete the necessary refactor so the matcher consumes structured OCR signals directly instead of reparsing the merged OCR text for identifier metadata
- outcome: updated `services/card_identifier.py` to accept `OCRStructuredResult` and extract `detected_set_code` / `detected_print_number` from structured OCR signals first, with the old text parser retained as fallback; updated `handlers/listing.py` to pass `ocr_result.structured` into identification so the live listing flow now uses the structured path end-to-end for identifier metadata
- validation: `python -m py_compile services/card_identifier.py handlers/listing.py services/ocr.py services/ocr_signals.py` passed; direct structured matcher probes on saved legacy and modern debug crops still resolved `Electrode Holo (Hidden Legends)` and `Mega Charizard X ex (Phantasmal Flames)` correctly while using the structured OCR object as input
- what was weak: only identifier metadata is now sourced from structured signals directly; most of the broader candidate scoring logic still uses the legacy merged text and should be migrated in later Phase A / Phase B work
- follow-up: next, move name/variant/set-text consumption into structured inputs too, then split candidate generation from scoring as planned in `OCR_ARCHITECTURE_RESET.md`
- user reaction: approved the refactor only if it was necessary; this one was necessary because otherwise the new OCR signal layer would still be bypassed by a text reparser at the matcher boundary
- date: 2026-04-12
- goal: complete the next necessary refactor by moving name, variant, and set-text consumption onto structured OCR signals too
- outcome: added `_structured_search_text(...)` and `_ocr_text_context(...)` in `services/card_identifier.py`; the matcher now builds its lowercase search text, token set, and word-token context from structured OCR signals first, and only falls back to the legacy merged OCR string when structured signals are unavailable; threaded this through the remaining text-dependent helpers such as shortlist generation, exact identifier scoring, nearby-ratio scoring, modern-ratio scoring, and generic match scoring
- validation: `python -m py_compile services/card_identifier.py handlers/listing.py services/ocr.py services/ocr_signals.py` passed; direct structured matcher probes on saved legacy and modern debug crops still resolved `Electrode Holo (Hidden Legends)` and `Mega Charizard X ex (Phantasmal Flames)` correctly while using structured OCR-derived search context
- what was weak: candidate generation and scoring are still coupled inside `services/card_identifier.py`, so the broader Phase B split is still ahead
- follow-up: implement the actual candidate-generation layer next, then migrate scoring onto candidate evidence instead of iterating the full catalog inside one large function
- user reaction: asked to continue only if the refactor was necessary; this one was necessary because the matcher still depended on merged text for most of its semantic context even after structured identifier metadata was introduced
- date: 2026-04-12
- goal: start Phase B by separating candidate generation from scoring in a narrow, necessary way
- outcome: added `services/candidate_generation.py` to build a recall-oriented generic candidate pool from structured OCR signals, printed number hints, set-code hints, and fuzzy name evidence; updated `services/card_identifier.py` so the main generic catalog scoring path now scores that candidate pool instead of iterating the full catalog inline
- validation: `python -m py_compile services/candidate_generation.py services/card_identifier.py handlers/listing.py services/ocr.py services/ocr_signals.py` passed; validation still resolved `Medicham V (Evolving Skies)` from `IDENTIFIER: 186/203 | NAME_EN: Medicham sa` and `Electrode Holo (Hidden Legends)` from the saved legacy structured sample
- what was weak: the exact/unique/nearby resolver branches still live in `services/card_identifier.py`, and the candidate pool is recall-oriented rather than yet being a clean standalone candidate-generation service with provenance-rich scoring inputs
- follow-up: extract candidate provenance explicitly and continue moving more matching branches onto the shared candidate-generation + scorer pipeline
- user reaction: asked to proceed with the candidate-generation split; this is the first narrow Phase B cut that is necessary without over-refactoring in one step
- date: 2026-04-12
- goal: complete the next necessary refactor by wiring the shared evidence scorer into the matcher without adding any per-card runtime rules
- outcome: updated `services/card_identifier.py` to use `services/candidate_scoring.py` for shortlist, exact-identifier, nearby-ratio, modern-ratio, and generic scoring; fixed the undefined `candidate_catalog` bug in the modern branch; switched the main generic loop onto `candidate_catalog`; and added a guard so legacy nearby-ratio rescue no longer intercepts modern high-number identifier cases
- validation: `.venv/bin/python -m py_compile services/candidate_scoring.py services/card_identifier.py services/ocr.py services/ocr_signals.py handlers/listing.py` passed; synthetic catalog probes confirmed `PFL 130/094` -> `Mega Charizard X ex (Phantasmal Flames)`, `5/101 + Electrode OCR` -> `Electrode Holo (Hidden Legends)`, and `ABC 123/456` still no-matches safely
- what was weak: live Supabase-backed resolver probes still hung in this shell session, so validation had to rely on compile checks and synthetic catalog probes instead of the full remote catalog
- follow-up: finish the split by extracting the remaining branch policy from `services/card_identifier.py` and add a stable local/snapshot eval path so OCR regression checks are not blocked by live catalog latency
- user reaction: explicitly wanted only necessary refactoring and no hardcoded resolves; this change stays generic by unifying evidence scoring and by making ambiguous modern cases fail safe instead of inventing a match
- date: 2026-04-12
- goal: add a stable snapshot-backed eval path so OCR/resolver validation no longer depends on live Supabase latency during every evaluation run
- outcome: added `db/catalog_snapshot.py`, taught `db/cards.py` and `db/pokemon_sets.py` to serve local snapshot data when `CARD_CATALOG_SNAPSHOT_PATH` is set, added `scripts/export_catalog_snapshot.py` to export a local catalog snapshot, and updated `scripts/evaluate_ocr_resolver.py` so synthetic audits can run entirely from `--catalog-snapshot` without live catalog reads during resolver execution
- validation: `.venv/bin/python -m py_compile db/catalog_snapshot.py db/cards.py db/pokemon_sets.py scripts/evaluate_ocr_resolver.py scripts/export_catalog_snapshot.py` passed; `.venv/bin/python scripts/export_catalog_snapshot.py --out .snapshots/catalog_snapshot.json --game pokemon` exported 19,917 cards and 180 set rows; snapshot-backed evaluator runs passed 20/20 smoke cases and 100/100 broader synthetic cases
- what was weak: the first full uncapped snapshot audit was slower than desired, so this session validated with smoke plus 100-case baseline rather than waiting indefinitely on a very large first run
- follow-up: add snapshot refresh workflow/docs and layer failure-class real-photo manifests on top of the new offline snapshot baseline
- user reaction: asked for the next necessary step so they do not have to keep doing manual QA against live catalog latency; this gives them a reproducible local audit path
- date: 2026-04-12
- goal: make the new snapshot-backed offline eval path easy to run as a routine regression command instead of a multi-step manual sequence
- outcome: added `scripts/run_snapshot_eval.py` to wrap snapshot export plus snapshot-backed evaluation into one command and added `Makefile` target `ocr-eval-snapshot` as the stable shorthand entrypoint
- validation: `.venv/bin/python -m py_compile scripts/run_snapshot_eval.py` passed; `make ocr-eval-snapshot OCR_EVAL_LIMIT=20` exported the snapshot and then completed a passing 20/20 offline audit, writing a timestamped report to `.logs/ocr_eval_snapshot_20260412-235821.json`
- what was weak: the wrapper currently defaults to synthetic audits only; class-based real-photo manifest runs still need to be layered onto this command as the next step
- follow-up: extend the wrapper to accept manifest paths and standardize snapshot refresh cadence so eval baselines stay fresh without ad hoc manual judgment
- user reaction: asked to "do it" for the one-command flow; this removes another chunk of manual QA legwork from future sessions
- date: 2026-04-12
- goal: implement the important listing-photo upgrade so sellers can upload multiple images per listing and the bot can recognize front vs back for buyer condition visibility
- outcome: added `services/listing_image_classifier.py`; refactored `handlers/listing.py` so `/list` now collects a photo batch until the seller replies `done`; selected likely front/back images before OCR; posted multi-image listings via Telegram media groups; and persisted both `primary_image_path` and `secondary_image_path` through `db/listings.py`
- validation: `.venv/bin/python -m py_compile handlers/listing.py services/listing_image_classifier.py db/listings.py` passed; a monkeypatched smoke test confirmed the classifier picks the synthetic front image as front and the blue low-text image as back
- what was weak: this first cut does not yet expose a seller override button if the front/back guess is wrong, and album uploads still generate one acknowledgment per Telegram photo message because the flow currently collects photos message-by-message
- follow-up: add explicit seller override for front/back roles and smooth out media-group UX so album uploads feel less chatty while keeping the batch-based OCR pipeline
- user reaction: asked for batch uploads plus front/back recognition because buyers need condition photos; this implements that core workflow without waiting for a bigger redesign
- date: 2026-04-12
- goal: record a standing workflow preference from the user for handling future feature requests
- outcome: updated `MEMORY.md` with the instruction that new feature requests should be evaluated thoughtfully before suggesting execution, so future sessions start with that expectation in mind
- validation: documentation-only change; no code path changed
- what was weak: this is guidance in repo memory, not an enforced runtime rule
- follow-up: apply this consistently in future feature-planning turns and surface evaluation reasoning before implementation proposals
- user reaction: explicitly asked that this be remembered in a relevant project document
- date: 2026-04-13
- goal: evaluate the full project against the original product docs and produce a sharper roadmap to reach a truthful minimal Phase 1 GA
- outcome: rewrote `ROADMAP.md` around a minimum-GA definition that prioritizes fixed-price seller ops completion over further scope expansion; added supporting priority notes to `TODO.md` and `MEMORY.md`
- validation: documentation-only planning change based on current repo state, TODOs, memory, and source product docs; no code path changed
- what was weak: this is still a planning recommendation and does not by itself reduce the remaining implementation gap
- follow-up: execute the new top sequence in order — claims, payment/queue, SOLD/transactions, seller ops, then launch hardening
- user reaction: asked for an evaluation and a roadmap to finish the project to minimally Phase 1 GA

- date: 2026-04-13
- goal: convert the high-level minimum-GA roadmap into a concrete execution plan grounded in the actual claim/payment code and schema baseline
- outcome: updated `ROADMAP.md` with six execution milestones, milestone dependencies, and acceptance criteria; updated `TODO.md` to reflect which claim/transaction/seller-op areas are already scaffolded versus still missing; and updated `MEMORY.md` so future sessions start from the new execution sequence instead of drifting back to lower-priority OCR work
- validation: documentation-only planning pass cross-checked against `handlers/claims.py`, `db/claims.py`, `jobs/payment_deadlines.py`, `handlers/transactions.py`, `db/transactions.py`, `handlers/seller_tools.py`, `migrations/001_initial_schema.sql`, and `migrations/004_atomic_rpc.sql`; no runtime code changed
- what was weak: this pass clarifies the execution order, but the repo still has not implemented the worker, transaction, or seller-op milestones themselves
- follow-up: start Milestone 1 by validating live linked-discussion claim resolution and then lock down the claim-state contract before touching payment or SOLD lifecycle logic
- user reaction: asked to continue from the evaluation and turn it into a concrete roadmap to finish minimal Phase 1 GA

- date: 2026-04-13
- goal: begin Milestone 1 implementation by hardening the live claim path before touching queue/payment logic
- outcome: replaced the hardcoded claim-keyword check with seller-config-backed keyword matching in `handlers/claims.py`, added blacklist lookup helpers in `db/blacklist.py`, blocked blacklisted buyers before the atomic claim RPC, improved claim-state messaging/logging, and updated setup persistence so `primary_channel_id` is stored in seller config
- validation: `.venv/bin/python -m py_compile handlers/claims.py handlers/setup.py db/blacklist.py db/seller_configs.py` passed; `.venv/bin/python` helper probes confirmed seller keyword normalization and claim-text matching behavior
- what was weak: this pass does not yet verify real linked-discussion update shapes live, and it intentionally does not implement queued later claims or payment expiry
- follow-up: live-test the linked discussion flow, then expand the claim RPC/state model so second and later claims can queue safely instead of failing closed
- user reaction: asked to start Phase 1, so this first cut focuses on the highest-value live claim hardening work without overreaching into later milestones

- date: 2026-04-13
- goal: continue Phase 1 claim work by moving queued-claim semantics into the database contract instead of faking queue behavior in the handler
- outcome: added queue-aware claim helpers in `db/claims.py`, updated `handlers/claims.py` to support confirmed vs queued outcomes and duplicate-buyer short-circuiting, strengthened `handlers/setup.py` to verify linked discussion access, added `migrations/005_claim_queue_semantics.sql`, and applied the new `claim_listing_atomic(...)` function to the current Supabase DB via the pooler connection
- validation: `.venv/bin/python -m py_compile handlers/claims.py handlers/setup.py db/claims.py` passed; a live rolled-back Postgres integration probe verified first claim -> `confirmed`, second claim -> `queued`, duplicate second buyer -> same queued record, and listing status -> `claim_pending`
- what was weak: this still does not prove end-to-end Telegram update shapes from the real linked discussion thread, and queue advancement after missed payment is still not implemented
- follow-up: run a real Telegram claim test with two buyers in the linked discussion, then implement `advance_claim_queue` / payment-deadline worker semantics
- user reaction: asked to continue, so this pass completed the next necessary queue-state contract work instead of drifting into unrelated features

- date: 2026-04-13
- goal: verify the bot runtime after the Phase 1 claim/queue changes instead of leaving the repo in a code-only state
- outcome: attempted a clean local restart, cleared a stale `.logs/bot.lock`, and confirmed the app can still boot to `Bot ready as @TCGlistingbot`; Telegram then returned a `Conflict: terminated by other getUpdates request`, which shows another polling instance is active on the same token outside this session
- validation: local log reached startup at `2026-04-13 11:17:00` and then emitted the Telegram conflict error immediately after `Application started`
- what was weak: the local process cannot stay active until the other polling instance is stopped or the bot is moved to webhook mode
- follow-up: stop the other polling process or switch to a single webhook deployment before relying on this local poller for live testing
- user reaction: asked to continue implementation, so runtime verification was done as a follow-up check after the code/database changes landed

- date: 2026-04-13
- goal: implement missed-payment expiry and queue advancement as the next minimum-GA milestone after queued claims were landed
- outcome: added `advance_claim_queue(...)` support in `migrations/006_advance_claim_queue.sql` and `db/claims.py`, implemented the APScheduler-backed worker in `jobs/payment_deadlines.py`, wired scheduler startup/shutdown in `main.py`, and added listing lookup support in `db/listings.py` so expiry handling can notify the seller and newly promoted buyer
- validation: `.venv/bin/python -m py_compile main.py db/claims.py db/listings.py jobs/payment_deadlines.py jobs/scheduler.py` passed; a live rolled-back Postgres integration probe verified `advance_claim_queue(...)` returns `promoted` when a queued buyer exists and `reactivated` when no queued buyer remains
- what was weak: the worker has not yet been verified against real Telegram discussion-thread traffic because another polling instance is still conflicting on the bot token, and buyer strike issuance is still deferred
- follow-up: implement seller-paid -> SOLD -> transaction closure, then add duplicate-update protection around claim/payment side effects
- user reaction: asked to continue with the next step, so this pass focused on the payment-expiry/queue-advance milestone rather than jumping ahead to seller dashboards or transactions

- date: 2026-04-13
- goal: implement the next minimum-GA milestone by letting a seller mark a winning claim as paid and close the sale end-to-end
- outcome: added `complete_transaction_atomic(...)` in `migrations/007_complete_transaction_atomic.sql` and `db/transactions.py`, added claim-pending listing lookup in `db/listings.py`, added listing-channel lookup in `db/listing_channels.py`, added SOLD message formatting in `utils/formatters.py`, and replaced the placeholder `/sold` handler with a working seller-paid completion path in `handlers/transactions.py` that edits the posted listing to SOLD and notifies the buyer when possible
- validation: `.venv/bin/python -m py_compile handlers/transactions.py db/transactions.py db/listings.py db/listing_channels.py utils/formatters.py` passed; a live rolled-back Postgres integration probe verified `complete_transaction_atomic(...)` marks the claim `paid`, sets the listing `sold`, creates exactly one transaction row, increments seller `total_sales_sgd`, and returns `already_completed` on duplicate invocation
- what was weak: the `/sold` UX is still command-driven rather than button-driven, and live Telegram verification is still blocked by the other polling instance on the same bot token
- follow-up: build seller active/sold history views and then add duplicate-update protection around claim/payment completion side effects
- user reaction: asked to continue with the next step, so this pass completed the seller-paid/SOLD/transaction milestone before moving on to seller dashboards or optional polish

- date: 2026-04-13
- goal: implement the minimum seller-ops surface after the claim, expiry, and SOLD transaction path were in place
- outcome: replaced the seller-tools placeholder with working `/stats`, `/inventory`, `/sales`, `/blacklist`, and `/vacation` commands in `handlers/seller_tools.py`; added blacklist CRUD/count helpers in `db/blacklist.py`; added open-listing and claim-pending counts in `db/listings.py`; added vacation toggling in `db/sellers.py`; updated bot command registration in `main.py`; and enforced vacation mode in `handlers/claims.py` so away sellers stop accepting new claims automatically
- validation: `.venv/bin/python -m py_compile handlers/seller_tools.py db/blacklist.py db/listings.py db/sellers.py main.py handlers/claims.py` passed; an import-level registration probe confirmed seller tool handlers can be added to a PTB application cleanly
- what was weak: seller ops are command-based and minimal, not yet button-driven or paginated, and the live Telegram runtime conflict still blocks full end-to-end verification against the actual bot token
- follow-up: implement duplicate-update protection and move the bot to one stable always-on runtime path so the now-complete seller flow can be verified live without polling conflicts
- user reaction: asked to implement seller ops next, so this pass focused on the minimum operational command surface instead of adding dashboard-like UI or optional analytics

- date: 2026-04-13
- goal: build the Telegram-native seller dashboard so active listings can be managed by buttons instead of relying only on commands and message IDs
- outcome: refactored `handlers/transactions.py` to expose reusable sale-completion logic, then upgraded `handlers/seller_tools.py` into a button-driven dashboard with home, paginated inventory, listing detail, queue view, sales view, blacklist view, vacation controls, and a safe mark-paid confirmation flow; dashboard actions operate on concrete `listing_id` values so sellers can manage multiple similar items without ambiguity
- validation: `.venv/bin/python -m py_compile handlers/seller_tools.py handlers/transactions.py main.py db/blacklist.py db/listings.py db/sellers.py db/transactions.py` passed; a registration probe confirmed callback handlers register cleanly; callback-data length checks passed within Telegram's 64-byte limit
- what was weak: blacklist add/remove is still text-command-based even though blacklist viewing is now on the dashboard, and the new button flows are not yet verified live because the Telegram polling conflict still exists
- follow-up: add duplicate-update protection around dashboard callbacks and claim/payment actions, then remove the competing poller so the dashboard can be verified against the real bot token
- user reaction: asked to build out the Telegram dashboard for sellers when viewing active listings, so this pass prioritized listing-specific button flows over backend hardening work

- date: 2026-04-13
- goal: add a first-pass idempotency layer so duplicate Telegram deliveries stop causing duplicate claim/payment side effects while still allowing multiple similar listings
- outcome: added `migrations/008_processed_events.sql` plus `db/idempotency.py`, then wrapped claim comments, `/sold`, blacklist/vacation commands, and mutating seller dashboard callbacks with DB-backed processed-event keys; dedupe is keyed on Telegram event identity, not on card identity, so sellers can still list multiple copies of the same item safely
- validation: `.venv/bin/python -m py_compile db/idempotency.py handlers/claims.py handlers/transactions.py handlers/seller_tools.py` passed; live pooler-backed probe confirmed `register_processed_event(...)` returns `True` on first insert and `False` on duplicate insert for the same `(source, event_key)`
- what was weak: this is a first-pass idempotency layer, not a full distributed runtime-hardening solution yet; read-only dashboard callbacks are intentionally not deduped, and live verification is still blocked by the competing polling instance on the bot token
- follow-up: move to one stable runtime path, then extend the same dedupe pattern to any remaining mutating handlers/jobs and verify behavior under real webhook/polling retry conditions
- user reaction: asked to implement idempotency next and raised the concern about multiple quantities of the same item, so this pass explicitly dedupes event deliveries instead of deduping item identity

- date: 2026-04-13
- goal: answer the real-time Telegram message-edit question by building the reusable live-edit infrastructure without overcommitting to full auction scope before bid parsing exists
- outcome: added `services/listing_message_editor.py` as the shared Telegram post-edit utility, refactored SOLD edits in `handlers/transactions.py` to use it, extended `utils/formatters.py` with auction countdown/current-bid formatting, added live auction listing queries in `db/listings.py`, and replaced the auction-close placeholder with `jobs/auction_close.py`, which can now refresh auction posts on a minute schedule and mark expired auction listings as `auction_closed`
- validation: `.venv/bin/python -m py_compile jobs/auction_close.py services/listing_message_editor.py utils/formatters.py handlers/transactions.py main.py` passed; pure checks confirmed countdown markers and auction message formatting work, and scheduler registration for auction jobs succeeded
- what was weak: auction creation, bid parsing, highest-bid updates, and anti-snipe behavior are still not implemented, so the new refresh worker is infrastructure-first rather than a complete live auction feature
- follow-up: if auctions are reprioritized, wire bid parsing plus atomic bid updates next; otherwise keep focus on runtime hardening and live verification of the current fixed-price flow
- user reaction: asked whether the bot can edit Telegram posts in real time and then asked to do it, so this pass implemented the reusable edit layer and the auction refresh scaffold rather than pretending auctions were already complete


## 2026-04-13 — Real Auction Lifecycle
- date: 2026-04-13
- goal: move auctions from scaffolding to a working Telegram-native flow without forking into brittle hardcoded paths
- outcome: added a dedicated `/auction` photo-first conversation, extended listing persistence for auction fields, added `record_auction_bid_atomic(...)` and `close_auction_atomic(...)`, routed discussion comments to claim-vs-bid behavior based on listing type, enabled live auction post edits on every accepted bid, applied anti-snipe in the bid RPC, and awarded the winner into the existing payment deadline path on close
- validation: `python3 -m py_compile $(rg --files -g '*.py')` passed after wiring `handlers/auctions.py`, `handlers/claims.py`, `db/claims.py`, `db/listings.py`, `jobs/auction_close.py`, `utils/formatters.py`, and `main.py`
- what went well: the feature reused the existing OCR/front-back flow and payment lifecycle instead of inventing a separate hardcoded resolver path, so auctions now sit on the same product rails as fixed-price listings
- what was weak: live linked-discussion bidding still needs real Telegram QA, and seller-facing auction controls like cancel / end early are not built yet
- follow-up: run live auction tests in the real channel/discussion setup, then add seller auction management controls and any missing cross-post edit synchronization
- user reaction: asked to build out auctions after confirming the bot can edit Telegram posts in real time, while explicitly pushing against brittle hardcoded logic

- date: 2026-04-13
- goal: close a few truthful Phase 1 gaps instead of claiming launch readiness prematurely
- outcome: expanded `/setup` to store seller-configurable claim keywords plus default postage, added `utils/photo_quality.py` and wired quality scoring into listing/auction front-image selection before OCR, replaced the `/admin` placeholder with a live operational snapshot, and swapped the generic game-adapter placeholders for real wrappers over the current identifier pipeline
- validation: `.venv/bin/python -m py_compile handlers/listing.py handlers/auctions.py handlers/setup.py handlers/admin.py services/listing_image_classifier.py services/game_adapters.py utils/photo_quality.py db/seller_configs.py` passed; a live Supabase probe via `handlers.admin._admin_snapshot()` confirmed the current launch blocker counts (`cards_onepiece=2`, `cards_jp_named=2`)
- what was weak: this still does not conjure the missing One Piece / Japanese catalog data, PriceCharting linkage, or live linked-discussion QA, so strict PRD Phase 1 remains incomplete even after these core UX/runtime improvements
- follow-up: import real One Piece + Japanese catalog data, finish provider-status reporting in pricing, and run live linked-discussion claim/payment QA on the current bot
