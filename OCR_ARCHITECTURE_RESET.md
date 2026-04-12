# OCR_ARCHITECTURE_RESET.md

## Goal
Replace the current branchy OCR rescue flow with a production-ready identification pipeline that generalizes across card photos instead of improving one reported miss at a time.

## What This Reset Optimizes For
- robust OCR across glare, tilt, foil, cropping, and old/new layouts
- generic catalog matching, not per-card or per-image rescue logic
- truthful abstention when evidence is weak
- broad evaluation by failure class, not handpicked named examples
- low-maintenance behavior that does not require the user to keep discovering misses manually

## Non-Goals
- no runtime per-card hardcoding
- no repo-shipped named OCR case manifests that feel like hidden memorization
- no growing tree of narrowly targeted resolver branches for one image pattern at a time
- no forcing a confident single match from weak evidence

## Target Architecture

### 1. Structured OCR Extraction
The OCR stage should stop returning mainly one concatenated text blob and instead emit a structured signal object.

#### Required extracted signals
- `layout_family`
  - examples: `pokemon_modern_bottom_left`, `pokemon_legacy_bottom_right`, `pokemon_full_art`, `pokemon_jp_modern`
- `name_text`
- `name_tokens`
- `printed_ratio`
- `set_code_text`
- `set_name_text`
- `variant_tokens`
  - examples: `v`, `vmax`, `vstar`, `gx`, `ex`, `illustration rare`, `trainer gallery`
- `symbol_guess`
- `ocr_confidence_by_signal`
- `raw_regions`
  - metadata for which ROI produced each signal

#### Design rules
- multiple OCR regions can vote on the same signal
- signals must remain separate; do not collapse everything into one string too early
- OCR should prefer preserving uncertainty over forcing a normalized value
- each extractor must be reusable across all cards in a layout family

### 2. Generic Candidate Generation
Candidate generation should be broad and catalog-grounded.

#### Inputs
- extracted structured signals only
- imported catalog data only

#### Candidate sources
- exact `set_code + printed_number`
- exact `printed_number + set_total`
- fuzzy `name + variant`
- `set_name alias + printed_number`
- `symbol_guess + printed_number`
- `name only` fallback when OCR is weak

#### Rules
- candidate generation must be recall-oriented
- candidate generation must not rank final winners aggressively
- candidate generation must never contain card-specific exceptions

### 3. One Evidence Scorer
Replace multiple rescue-style resolver paths with one generic evidence scorer.

#### Positive evidence examples
- exact printed ratio match
- exact set code match
- exact set total match
- strong name similarity
- variant token agreement
- symbol agreement
- layout-family compatibility

#### Negative evidence examples
- impossible number for set total
- variant mismatch, like OCR sees `V` but candidate is plain non-`V`
- strong set contradiction
- symbol contradiction
- layout contradiction

#### Output
- top ranked candidates
- calibrated match confidence
- abstain if confidence or separation is too weak
- machine-readable explanation of which signals helped and which contradicted

### 4. Honest Decision Policy
The runtime must separate:
- `auto_match`
- `shortlist`
- `abstain`

#### Auto-match only when
- there is strong evidence
- there is little contradiction
- the top candidate clearly separates from the rest

#### Shortlist when
- name is good but number is uncertain
- ratio is plausible but symbol/set is uncertain
- several candidates fit the evidence similarly

#### Abstain when
- OCR signals contradict each other materially
- layout or variant is unclear
- there is insufficient evidence to be useful

## Evaluation Reset

### Replace example-driven validation with failure-class validation
The system should be evaluated by classes of problems, not by named card examples.

#### Required evaluation buckets
- modern Pokémon bottom-left ratio
- legacy Pokémon bottom-right ratio
- full-art / secret rare / high-number cards
- foil / glare-heavy cards
- skewed / angled photos
- weak crop / imperfect isolate cases
- variant token loss, like missing `V` or `ex`
- false set-code parse cases
- promo / alphanumeric printed identifiers
- Japanese Pokémon OCR and matching

#### Evaluation types
- synthetic catalog audits for parser and scorer invariants
- managed real-photo buckets by failure class
- holdout sets not used during development iteration

#### Explicitly disallowed
- shipping a growing in-repo manifest of named cards that directly shapes runtime behavior

## Implementation Sequence

### Phase A — Extractor Foundations
1. define a structured OCR signal schema
2. split OCR into reusable extractors by region and layout family
3. preserve per-signal confidence and source region metadata
4. stop depending on one merged OCR string as the primary runtime interface

### Phase B — Candidate Generation
1. implement one candidate generation module
2. query by exact numeric and textual evidence separately
3. return a broad candidate pool with provenance
4. remove ranking assumptions from candidate generation

### Phase C — Unified Evidence Scorer
1. implement one scorer over extracted signals and generated candidates
2. centralize positive and negative evidence weights
3. expose score breakdowns for debugging
4. replace branchy rescue resolvers with the unified scorer

### Phase D — Decision Policy
1. define calibrated thresholds for auto-match vs shortlist vs abstain
2. tune with broad failure-class evals
3. make seller-facing uncertainty truthful and stable

### Phase E — Evaluation and Operations
1. create managed eval buckets by failure class
2. add recurring synthetic audits for parser invariants
3. add recurring real-photo audits for holdout buckets
4. report metrics by failure class, not only pass/fail totals

## Codebase Refactor Targets

### Likely new modules
- `services/ocr_signals.py`
- `services/ocr_layouts.py`
- `services/candidate_generation.py`
- `services/candidate_scoring.py`
- `services/decision_policy.py`
- `scripts/evaluate_ocr_failure_buckets.py`

### Existing modules to shrink
- `services/card_identifier.py`
- `services/ocr.py`

### End-state for `services/card_identifier.py`
It should mostly orchestrate:
- parse structured OCR signals
- generate candidates
- score candidates
- apply decision policy

It should not keep accumulating bespoke resolver branches.

## Immediate Next Work
1. define the structured OCR signal dataclass and migrate current OCR outputs into it
2. implement a generic candidate-generation layer separate from scoring
3. implement a unified scorer with explicit positive and negative evidence
4. freeze new rescue-style resolver branches unless they are clearly generic extractor improvements
5. build evaluation buckets for real-photo failure classes so the user is not the primary QA loop

## Decision Rule For Future Work
If a proposed fix mainly helps because it matches one previously seen image pattern, reject it.
If a proposed fix improves a reusable extractor, a generic candidate generator, a generic scorer, or a broad evaluation bucket, accept it.
