"""Seller data access helpers for TCG Listing Bot."""

from __future__ import annotations

from typing import Any

from db.client import extract_single, get_client


def get_seller_by_telegram_id(telegram_id: int) -> dict[str, Any] | None:
    """Fetch a seller row by Telegram user ID."""

    response = (
        get_client()
        .table('sellers')
        .select('*')
        .eq('telegram_id', telegram_id)
        .limit(1)
        .execute()
    )
    return extract_single(response)


def upsert_seller(*, telegram_id: int, telegram_username: str | None, telegram_display_name: str) -> dict[str, Any]:
    """Create or update a seller using Telegram identity fields."""

    payload = {
        'telegram_id': telegram_id,
        'telegram_username': telegram_username,
        'telegram_display_name': telegram_display_name,
    }
    response = (
        get_client()
        .table('sellers')
        .upsert(payload, on_conflict='telegram_id')
        .execute()
    )
    seller = extract_single(response)
    if seller:
        return seller
    refreshed = get_seller_by_telegram_id(telegram_id)
    if refreshed is None:
        raise RuntimeError('Failed to load seller after upsert.')
    return refreshed


def get_seller_by_id(seller_id: str) -> dict[str, Any] | None:
    """Fetch a seller row by primary key."""

    response = get_client().table('sellers').select('*').eq('id', seller_id).limit(1).execute()
    return extract_single(response)
