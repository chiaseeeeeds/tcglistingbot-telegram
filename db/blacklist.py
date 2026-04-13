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



def count_blacklist_entries(*, seller_id: str) -> int:
    """Return the total blacklist count for a seller."""

    response = (
        get_client()
        .table('seller_buyer_blacklist')
        .select('id', count='exact')
        .eq('seller_id', seller_id)
        .execute()
    )
    return int(response.count or 0)



def upsert_blacklist_entry(
    *,
    seller_id: str,
    blocked_telegram_id: int,
    blocked_username: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Create or update a blacklist entry for a seller."""

    payload = {
        'seller_id': seller_id,
        'blocked_telegram_id': blocked_telegram_id,
        'blocked_username': blocked_username,
        'reason': reason or '',
    }
    response = (
        get_client()
        .table('seller_buyer_blacklist')
        .upsert(payload, on_conflict='seller_id,blocked_telegram_id')
        .execute()
    )
    row = extract_single(response)
    if row is not None:
        return row
    refreshed = get_blacklist_entry(seller_id=seller_id, blocked_telegram_id=blocked_telegram_id)
    if refreshed is None:
        raise RuntimeError('Failed to load blacklist entry after upsert.')
    return refreshed



def remove_blacklist_entry(*, seller_id: str, blocked_telegram_id: int) -> bool:
    """Remove a blacklist entry and return whether one existed."""

    existing = get_blacklist_entry(seller_id=seller_id, blocked_telegram_id=blocked_telegram_id)
    if existing is None:
        return False
    get_client().table('seller_buyer_blacklist').delete().eq('seller_id', seller_id).eq(
        'blocked_telegram_id', blocked_telegram_id
    ).execute()
    return True
