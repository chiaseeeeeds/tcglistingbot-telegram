"""Pokémon set metadata helpers."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from db.catalog_snapshot import snapshot_pokemon_sets
from db.client import extract_many, extract_single, get_client


def get_pokemon_set_by_code(*, set_code: str) -> dict[str, Any] | None:
    snapshot_rows = snapshot_pokemon_sets(language='en')
    if snapshot_rows:
        for row in snapshot_rows:
            if str(row.get('set_code') or '') == set_code:
                return dict(row)
        return None
    response = (
        get_client()
        .table('pokemon_sets')
        .select('*')
        .eq('language', 'en')
        .eq('set_code', set_code)
        .limit(1)
        .execute()
    )
    return extract_single(response)


def get_pokemon_set_by_name(*, set_name: str) -> dict[str, Any] | None:
    snapshot_rows = snapshot_pokemon_sets(language='en')
    if snapshot_rows:
        for row in snapshot_rows:
            if str(row.get('set_name') or '') == set_name:
                return dict(row)
        return None
    response = (
        get_client()
        .table('pokemon_sets')
        .select('*')
        .eq('language', 'en')
        .eq('set_name', set_name)
        .limit(1)
        .execute()
    )
    return extract_single(response)


@lru_cache(maxsize=1)
def _list_pokemon_sets_cached() -> tuple[dict[str, Any], ...]:
    response = (
        get_client()
        .table('pokemon_sets')
        .select('*')
        .eq('language', 'en')
        .execute()
    )
    return tuple(extract_many(response))


def list_pokemon_sets_with_symbols() -> list[dict[str, Any]]:
    snapshot_rows = snapshot_pokemon_sets(language='en')
    if snapshot_rows:
        return [dict(row) for row in snapshot_rows if row.get('symbol_image_url') is not None]
    return [dict(row) for row in _list_pokemon_sets_cached() if row.get('symbol_image_url') is not None]


def list_pokemon_sets() -> list[dict[str, Any]]:
    snapshot_rows = snapshot_pokemon_sets(language='en')
    if snapshot_rows:
        return [dict(row) for row in snapshot_rows]
    return [dict(row) for row in _list_pokemon_sets_cached()]


def clear_pokemon_set_cache() -> None:
    _list_pokemon_sets_cached.cache_clear()
