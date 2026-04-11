"""Data access helpers for the claims domain."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from db.client import extract_many, extract_single, get_client
from db.rpc import call_rpc


def get_claims_for_listing(listing_id: str) -> list[dict[str, Any]]:
    response = (
        get_client()
        .table('claims')
        .select('*')
        .eq('listing_id', listing_id)
        .order('queue_position', desc=False)
        .execute()
    )
    return extract_many(response)


async def claim_listing_atomic(
    *,
    listing_id: str,
    buyer_telegram_id: int,
    buyer_username: str | None,
    buyer_display_name: str,
    payment_deadline_hours: int,
) -> dict[str, Any]:
    payment_deadline = datetime.now(timezone.utc) + timedelta(hours=payment_deadline_hours)
    data = await call_rpc(
        'claim_listing_atomic',
        {
            'p_listing_id': listing_id,
            'p_buyer_telegram_id': buyer_telegram_id,
            'p_buyer_username': buyer_username,
            'p_buyer_display_name': buyer_display_name,
            'p_payment_deadline': payment_deadline.isoformat(),
        },
    )
    if isinstance(data, list):
        return data[0]
    if isinstance(data, dict):
        return data
    raise RuntimeError('Atomic claim RPC returned no claim payload.')
