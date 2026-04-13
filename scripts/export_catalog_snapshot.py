"""Export a local JSON snapshot of catalog tables for offline OCR/resolver evaluation."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db.cards import clear_card_catalog_cache, list_cards_for_game
from db.catalog_snapshot import SNAPSHOT_ENV_VAR, clear_catalog_snapshot_cache
from db.pokemon_sets import clear_pokemon_set_cache, list_pokemon_sets


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Export a local catalog snapshot for offline OCR/resolver evaluation.')
    parser.add_argument('--out', default='.snapshots/catalog_snapshot.json', help='Output JSON path.')
    parser.add_argument('--game', action='append', default=['pokemon'], help='Game(s) to include from cards table. Repeatable.')
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.out).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    games = sorted({str(game).strip() for game in args.game if str(game).strip()})
    if not games:
        raise SystemExit('At least one --game must be provided.')

    os.environ.pop(SNAPSHOT_ENV_VAR, None)
    clear_catalog_snapshot_cache()
    clear_card_catalog_cache()
    clear_pokemon_set_cache()

    cards: list[dict] = []
    for game in games:
        cards.extend(list_cards_for_game(game))
    pokemon_sets = list_pokemon_sets()

    payload = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'source': 'supabase_http_snapshot',
        'games': games,
        'cards': cards,
        'pokemon_sets': pokemon_sets,
    }
    output_path.write_text(json.dumps(payload, indent=2, default=str))
    print(json.dumps({
        'out': str(output_path),
        'cards': len(cards),
        'pokemon_sets': len(pokemon_sets),
        'games': games,
    }, indent=2))


if __name__ == '__main__':
    main()
