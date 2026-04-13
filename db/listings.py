"""Listing data access helpers for TCG Listing Bot."""

from __future__ import annotations

from typing import Any

from db.client import extract_many, extract_single, get_client


def create_listing(
    *,
    seller_id: str,
    card_id: str | None = None,
    card_name: str,
    game: str,
    price_sgd: float,
    condition_notes: str,
    custom_description: str,
    posted_channel_id: int,
    posted_message_id: int,
    primary_image_path: str | None = None,
    secondary_image_path: str | None = None,
    tcgplayer_price_sgd: float | None = None,
    pricecharting_price_sgd: float | None = None,
    yuyutei_price_sgd: float | None = None,
) -> dict[str, Any]:
    """Insert a posted listing row and return the created record."""

    payload = {
        'seller_id': seller_id,
        'card_id': card_id,
        'card_name': card_name,
        'game': game,
        'price_sgd': round(price_sgd, 2),
        'condition_notes': condition_notes,
        'custom_description': custom_description,
        'posted_channel_id': posted_channel_id,
        'posted_message_id': posted_message_id,
        'primary_image_path': primary_image_path,
        'secondary_image_path': secondary_image_path,
        'tcgplayer_price_sgd': round(tcgplayer_price_sgd, 2) if tcgplayer_price_sgd is not None else None,
        'pricecharting_price_sgd': round(pricecharting_price_sgd, 2) if pricecharting_price_sgd is not None else None,
        'yuyutei_price_sgd': round(yuyutei_price_sgd, 2) if yuyutei_price_sgd is not None else None,
        'listing_type': 'fixed',
        'status': 'active',
    }
    response = get_client().table('listings').insert(payload).execute()
    listing = extract_single(response)
    if listing is None:
        raise RuntimeError('Failed to create listing row.')
    return listing


def get_active_listings_for_seller(seller_id: str) -> list[dict[str, Any]]:
    """Return active listings for a seller ordered by newest first."""

    response = (
        get_client()
        .table('listings')
        .select('*')
        .eq('seller_id', seller_id)
        .eq('status', 'active')
        .order('created_at', desc=True)
        .execute()
    )
    return extract_many(response)


def count_active_listings_for_seller(seller_id: str) -> int:
    """Return the number of active listings for a seller."""

    response = (
        get_client()
        .table('listings')
        .select('id', count='exact')
        .eq('seller_id', seller_id)
        .eq('status', 'active')
        .execute()
    )
    return int(response.count or 0)


def get_listing_by_posted_message(*, posted_message_id: int, posted_channel_id: int | None = None) -> dict[str, Any] | None:
    """Return an active or claim-pending listing by channel message identity."""

    query = (
        get_client()
        .table('listings')
        .select('*')
        .eq('posted_message_id', posted_message_id)
        .in_('status', ['active', 'claim_pending'])
    )
    if posted_channel_id is not None:
        query = query.eq('posted_channel_id', posted_channel_id)
    response = query.limit(1).execute()
    return extract_single(response)
