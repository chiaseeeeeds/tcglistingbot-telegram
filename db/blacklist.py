"""Data access helpers for the blacklist domain."""

from __future__ import annotations

from typing import Any

from db.client import extract_many, extract_single, get_client


def get_blacklist_entry(*, seller_id: str, blocked_telegram_id: int) -> dict[str, Any] | None:
    """Return the blacklist entry for a seller/buyer pair when it exists."""

    response = (
        get_client()
        .table('seller_buyer_blacklist')
        .select('*')
        .eq('seller_id', seller_id)
        .eq('blocked_telegram_id', blocked_telegram_id)
        .limit(1)
        .execute()
    )
    return extract_single(response)



def is_buyer_blacklisted(*, seller_id: str, buyer_telegram_id: int) -> bool:
    """Return whether the buyer is currently blacklisted by the seller."""

    return get_blacklist_entry(
        seller_id=seller_id,
        blocked_telegram_id=buyer_telegram_id,
    ) is not None



def list_blacklist_entries(*, seller_id: str) -> list[dict[str, Any]]:
    """Return blacklist entries for a seller ordered newest first."""

    response = (
        get_client()
        .table('seller_buyer_blacklist')
        .select('*')
        .eq('seller_id', seller_id)
        .order('created_at', desc=True)
        .execute()
    )
    return extract_many(response)
