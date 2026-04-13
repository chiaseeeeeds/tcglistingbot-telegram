"""Data access helpers for the transactions domain."""

from __future__ import annotations

from typing import Any

from db.client import extract_many, extract_single, get_client
from db.rpc import call_rpc



def get_transaction_by_listing_id(listing_id: str) -> dict[str, Any] | None:
    """Return the transaction for a listing when one exists."""

    response = (
        get_client()
        .table('transactions')
        .select('*')
        .eq('listing_id', listing_id)
        .limit(1)
        .execute()
    )
    return extract_single(response)



def get_transactions_for_seller(seller_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Return recent transactions for a seller."""

    response = (
        get_client()
        .table('transactions')
        .select('*')
        .eq('seller_id', seller_id)
        .order('completed_at', desc=True)
        .limit(limit)
        .execute()
    )
    return extract_many(response)


async def complete_transaction_atomic(*, listing_id: str, seller_id: str) -> dict[str, Any]:
    """Mark the winning claim as paid, create a transaction, and mark the listing sold."""

    data = await call_rpc(
        'complete_transaction_atomic',
        {
            'p_listing_id': listing_id,
            'p_seller_id': seller_id,
        },
    )
    if isinstance(data, list):
        return data[0]
    if isinstance(data, dict):
        return data
    raise RuntimeError('Complete transaction RPC returned no payload.')
