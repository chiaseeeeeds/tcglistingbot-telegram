"""Catalog coverage audit for Phase 1 launch readiness."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db.client import get_client



def count_rows(*, table: str, eq: tuple[str, object] | None = None, not_null: str | None = None) -> int:
    query = get_client().table(table).select('id', count='exact')
    if eq is not None:
        query = query.eq(eq[0], eq[1])
    if not_null is not None:
        query = query.not_.is_(not_null, 'null')
    response = query.execute()
    return int(response.count or 0)



def main() -> None:
    payload = {
        'pokemon_total': count_rows(table='cards', eq=('game', 'pokemon')),
        'onepiece_total': count_rows(table='cards', eq=('game', 'onepiece')),
        'jp_named_total': count_rows(table='cards', not_null='card_name_jp'),
        'pricecharting_linked_total': count_rows(table='cards', not_null='pricecharting_id'),
        'seller_count': count_rows(table='sellers'),
        'setup_complete_count': count_rows(table='seller_configs', eq=('setup_complete', True)),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
