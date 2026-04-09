# Catalog Import Plan

## Pokémon EN Catalog Sources

### 1. Bulbapedia expansions page
Used for set metadata and set abbreviation mapping.

Provides:
- `set_name`
- `set_code`
- `series_name`
- `release_date`
- `card_count`

### 2. Pokemon-Card-CSV repository
Used for card-level catalog rows.

Provides:
- `card_name_en`
- `card_number`
- `rarity`
- file-level set identity

## Pipeline

1. import Bulbapedia set rows into `pokemon_sets`
2. import Pokémon CSV rows into `pokemon_cards_staging`
3. join CSV set names against `pokemon_sets`
4. upsert normalized rows into `cards`
5. leave unmatched sets in staging for manual mapping review

## Tables

### `pokemon_sets`
- canonical English Pokémon set metadata
- source of `set_name -> set_code`

### `pokemon_cards_staging`
- imported raw EN Pokémon card rows
- preserves original CSV payload and mapping status

### `cards`
- normalized bot-facing card catalog
- populated for rows whose set mapping resolves successfully

## Current Scope

- Pokémon EN only
- One Piece is still TODO
- Japanese catalog is still TODO
