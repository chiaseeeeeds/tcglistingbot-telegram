"""Card catalog access helpers for TCG Listing Bot."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from db.client import extract_many, extract_single, get_client

_PAGE_SIZE = 1000


@lru_cache(maxsize=8)
def _list_cards_for_game_cached(game: str) -> tuple[dict[str, Any], ...]:
    all_rows: list[dict[str, Any]] = []
    start = 0
    while True:
        end = start + _PAGE_SIZE - 1
        response = (
            get_client()
            .table('cards')
            .select('*')
            .eq('game', game)
            .eq('is_active', True)
            .range(start, end)
            .execute()
        )
        rows = extract_many(response)
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < _PAGE_SIZE:
            break
        start += _PAGE_SIZE
    return tuple(all_rows)


def list_cards_for_game(game: str) -> list[dict[str, Any]]:
    """Return all active catalog cards for a supported game."""

    return [dict(row) for row in _list_cards_for_game_cached(game)]


@lru_cache(maxsize=512)
def _get_card_by_id_cached(card_id: str) -> dict[str, Any] | None:
    response = get_client().table('cards').select('*').eq('id', card_id).limit(1).execute()
    card = extract_single(response)
    return dict(card) if card is not None else None


def get_card_by_id(card_id: str) -> dict[str, Any] | None:
    """Return a single card row by primary key."""

    card = _get_card_by_id_cached(card_id)
    return dict(card) if card is not None else None


def list_cards_by_identifier(*, game: str, set_code: str, card_number: str) -> list[dict[str, Any]]:
    """Return active catalog cards matching a specific set code and card number."""

    normalized_code = set_code.strip().upper()
    normalized_number = card_number.strip().lstrip('0') or '0'
    padded_number = normalized_number.zfill(3)
    matches: list[dict[str, Any]] = []
    for row in list_cards_for_game(game):
        row_set_code = str(row.get('set_code') or '').strip().upper()
        row_number = str(row.get('card_number') or '').strip()
        row_number_unpadded = row_number.lstrip('0') or '0'
        if row_set_code != normalized_code:
            continue
        if row_number in {card_number, normalized_number, padded_number} or row_number_unpadded == normalized_number:
            matches.append(row)
    return matches


def clear_card_catalog_cache() -> None:
    """Clear in-process catalog caches after imports or maintenance tasks."""

    _list_cards_for_game_cached.cache_clear()
    _get_card_by_id_cached.cache_clear()
