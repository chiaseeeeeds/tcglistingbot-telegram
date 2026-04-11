---
name: tcg-catalog-integrity
description: Use when working on TCG card OCR, set mapping, catalog imports, pricing-source selection, or resolver behavior in this repo, especially when the user wants generic non-hardcoded matching, abbreviation-correct set codes, source-priority rules, or an audit for hidden overfitting.
---

# TCG Catalog Integrity

Use this skill for changes around OCR-backed card identification, Pokémon/One Piece catalog mapping, set-code normalization, and external pricing sources.

## Core Rules

- Never add per-card or per-image identification shortcuts in product logic.
- Never add `if OCR text contains X -> card Y` rules.
- Never use image hashes or card-specific fallback mappings.
- Prefer catalog-driven matching from OCR evidence: card name, printed number, set code, and generic set-name aliases.
- Treat exact `name + printed number` as stronger evidence than broad series or expansion context.
- Use set/series data as a tie-breaker or sanity check, not as the primary identity signal when better card-level evidence exists.
- Fail safe when OCR evidence is weak or conflicting.

## Approved Resolver Patterns

- Generic OCR extraction windows, preprocessing, and score thresholds.
- Catalog-driven alias matching derived from canonical set metadata.
- Printed number matching against catalog rows.
- Exact or fuzzy name-token overlap scored against catalog names.
- Set-code validation against catalog metadata.
- Explicit no-match guards when evidence conflicts.

## Disallowed Patterns

- Manual card-title exception maps.
- Card-ID overrides for named examples found during debugging.
- Resolver branches written around one specific card succeeding.
- Pricing-source logic that pretends a live source exists when it is unavailable.

## Workflow

1. Confirm the behavior with a probe or query, but do not convert the probe case into product logic.
2. Check whether the fix should live in:
   - OCR extraction
   - set alias generation
   - catalog import mapping
   - generic scoring policy
   - source availability handling
3. Prefer a generic fix that improves a class of cases.
4. Validate against:
   - one or more real positive examples
   - one deliberate negative/control example
   - a broader import or catalog audit when relevant
5. If a source is unavailable, degrade honestly and say so.

## Source Priority

For pricing and external references, prefer:
1. Local catalog and local listing history
2. Official or sanctioned APIs
3. Approved browser/scrape fallback
4. Seller manual confirmation

Do not silently skip from a broken live source to fabricated confidence.

## Set Mapping Rules

- Map sets to the printed abbreviation that the card/catalog actually uses.
- Derive aliases generically from canonical set names.
- Preserve full set names and meaningful suffix aliases after separators like em dashes.
- Avoid alias generation that collapses parent/base sets into child expansions.
- When changing import mapping, run a full-source audit if possible.

## When Auditing For Hardcoding

Look for:
- specific card names in resolver branches
- one-off exception maps in importers
- prompts/examples that leak real card IDs into product behavior
- metadata/debug labels that are fine for observability but not used for decisioning

A direct probe of the resolver is acceptable as a test. It is not a hardcode unless that case is embedded into runtime logic.

## References

If external sources or tools are relevant, read `references/source_links.md`.
