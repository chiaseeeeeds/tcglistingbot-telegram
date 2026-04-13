"""Local catalog snapshot helpers for offline OCR/resolver evaluation."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any


SNAPSHOT_ENV_VAR = 'CARD_CATALOG_SNAPSHOT_PATH'


class CatalogSnapshotError(RuntimeError):
    """Raised when a configured local catalog snapshot is invalid."""


@lru_cache(maxsize=1)
def get_snapshot_path() -> Path | None:
    raw_path = os.getenv(SNAPSHOT_ENV_VAR, '').strip()
    if not raw_path:
        return None
    return Path(raw_path).expanduser().resolve()


@lru_cache(maxsize=1)
def load_catalog_snapshot() -> dict[str, Any] | None:
    snapshot_path = get_snapshot_path()
    if snapshot_path is None:
        return None
    if not snapshot_path.exists():
        raise CatalogSnapshotError(f'Catalog snapshot not found: {snapshot_path}')
    payload = json.loads(snapshot_path.read_text())
    if not isinstance(payload, dict):
        raise CatalogSnapshotError('Catalog snapshot payload must be a JSON object.')
    cards = payload.get('cards')
    pokemon_sets = payload.get('pokemon_sets')
    if not isinstance(cards, list) or not isinstance(pokemon_sets, list):
        raise CatalogSnapshotError('Catalog snapshot must contain list fields: cards and pokemon_sets.')
    return payload


def snapshot_cards(*, game: str | None = None) -> list[dict[str, Any]]:
    payload = load_catalog_snapshot()
    if payload is None:
        return []
    rows = [dict(row) for row in payload.get('cards', [])]
    if game is None:
        return rows
    return [row for row in rows if str(row.get('game') or '') == game]


def snapshot_pokemon_sets(*, language: str = 'en') -> list[dict[str, Any]]:
    payload = load_catalog_snapshot()
    if payload is None:
        return []
    rows = [dict(row) for row in payload.get('pokemon_sets', [])]
    return [row for row in rows if str(row.get('language') or '') == language]


def clear_catalog_snapshot_cache() -> None:
    get_snapshot_path.cache_clear()
    load_catalog_snapshot.cache_clear()
