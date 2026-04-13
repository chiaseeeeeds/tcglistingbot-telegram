"""Smoke-test Phase 1 card resolution on live catalog samples."""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db.cards import list_cards_for_game
from services.card_identifier import identify_card_from_text



def _sample_cards(*, game: str, require_jp: bool = False, limit: int = 10) -> list[dict]:
    rows = list_cards_for_game(game)
    filtered = []
    for row in rows:
        if require_jp and not row.get('card_name_jp'):
            continue
        set_code = str(row.get('set_code') or '').strip()
        card_number = str(row.get('card_number') or '').strip()
        if not set_code or not card_number:
            continue
        filtered.append(row)
    random.seed(42)
    if len(filtered) <= limit:
        return filtered
    return random.sample(filtered, limit)



def _probe(row: dict, *, game: str) -> dict:
    set_code = str(row.get('set_code') or '').strip().upper()
    card_number = str(row.get('card_number') or '').strip().lstrip('0') or '0'
    name = str(row.get('card_name_jp') or row.get('card_name_en') or '').strip()
    if game == 'pokemon' and row.get('card_name_jp'):
        raw_text = f'IDENTIFIER: {set_code} {card_number}/999 | NAME_JP: {name}'
    else:
        raw_text = f'IDENTIFIER: {set_code} {card_number}/999 | NAME_EN: {name}'
    result = identify_card_from_text(raw_text=raw_text, game=game)
    observed_set = str((result.metadata or {}).get('set_code') or (result.metadata or {}).get('detected_set_code') or '')
    return {
        'input': raw_text,
        'expected_name': str(row.get('card_name_en') or row.get('card_name_jp') or ''),
        'expected_set': set_code,
        'matched': result.matched,
        'display_name': result.display_name,
        'confidence': result.confidence,
        'resolver': str((result.metadata or {}).get('resolver') or ''),
        'observed_set': observed_set,
        'pass': bool(result.matched and observed_set.upper() == set_code),
    }



def main() -> None:
    suites = [
        ('onepiece', _sample_cards(game='onepiece', limit=12)),
        ('pokemon_jp', _sample_cards(game='pokemon', require_jp=True, limit=12)),
    ]
    report = {}
    for suite_name, cards in suites:
        game = 'onepiece' if suite_name == 'onepiece' else 'pokemon'
        outcomes = [_probe(card, game=game) for card in cards]
        report[suite_name] = {
            'total': len(outcomes),
            'passed': sum(1 for item in outcomes if item['pass']),
            'failures': [item for item in outcomes if not item['pass']][:5],
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
