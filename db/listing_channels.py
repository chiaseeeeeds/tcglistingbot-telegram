"""Data access helpers for the listing_channels domain."""

from __future__ import annotations

from typing import Any

from db.client import extract_many, get_client



def get_listing_channels_for_listing(listing_id: str) -> list[dict[str, Any]]:
    """Return all channel-message mappings for a listing."""

    response = (
        get_client()
        .table('listing_channels')
        .select('*')
        .eq('listing_id', listing_id)
        .order('created_at', desc=False)
        .execute()
    )
    return extract_many(response)
