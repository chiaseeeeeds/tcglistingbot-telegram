"""Card catalog access helpers for TCG Listing Bot."""

from __future__ import annotations

from typing import Any

from db.client import extract_many, extract_single, get_client

_PAGE_SIZE = 1000


def list_cards_for_game(game: str) -> list[dict[str, Any]]:
    """Return all active catalog cards for a supported game."""

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
    return all_rows


def get_card_by_id(card_id: str) -> dict[str, Any] | None:
    """Return a single card row by primary key."""

    response = get_client().table('cards').select('*').eq('id', card_id).limit(1).execute()
    return extract_single(response)


def list_cards_by_identifier(*, game: str, set_code: str, card_number: str) -> list[dict[str, Any]]:
    """Return active catalog cards matching a specific set code and card number."""

    response = (
        get_client()
        .table('cards')
        .select('*')
        .eq('game', game)
        .eq('set_code', set_code)
        .eq('card_number', card_number)
        .eq('is_active', True)
        .execute()
    )
    return extract_many(response)
