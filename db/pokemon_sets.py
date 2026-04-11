"""Pokémon set metadata helpers."""

from __future__ import annotations

from typing import Any

from db.client import extract_many, extract_single, get_client


def get_pokemon_set_by_code(*, set_code: str) -> dict[str, Any] | None:
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


def list_pokemon_sets_with_symbols() -> list[dict[str, Any]]:
    response = (
        get_client()
        .table('pokemon_sets')
        .select('*')
        .eq('language', 'en')
        .not_.is_('symbol_image_url', 'null')
        .execute()
    )
    return extract_many(response)


def list_pokemon_sets() -> list[dict[str, Any]]:
    response = (
        get_client()
        .table('pokemon_sets')
        .select('*')
        .eq('language', 'en')
        .execute()
    )
    return extract_many(response)
