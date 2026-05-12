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
    price_sgd: float | None = None,
    condition_notes: str,
    custom_description: str,
    posted_channel_id: int,
    posted_message_id: int,
    primary_image_path: str | None = None,
    secondary_image_path: str | None = None,
    tcgplayer_price_sgd: float | None = None,
    pricecharting_price_sgd: float | None = None,
    yuyutei_price_sgd: float | None = None,
    listing_type: str = 'fixed',
    status: str | None = None,
    starting_bid_sgd: float | None = None,
    current_bid_sgd: float | None = None,
    bid_increment_sgd: float | None = None,
    auction_end_time: str | None = None,
    anti_snipe_minutes: int | None = None,
) -> dict[str, Any]:
    """Insert a posted listing row and return the created record."""

    payload = {
        'seller_id': seller_id,
        'card_id': card_id,
        'card_name': card_name,
        'game': game,
        'price_sgd': round(price_sgd, 2) if price_sgd is not None else None,
        'condition_notes': condition_notes,
        'custom_description': custom_description,
        'posted_channel_id': posted_channel_id,
        'posted_message_id': posted_message_id,
        'primary_image_path': primary_image_path,
        'secondary_image_path': secondary_image_path,
        'tcgplayer_price_sgd': round(tcgplayer_price_sgd, 2) if tcgplayer_price_sgd is not None else None,
        'pricecharting_price_sgd': round(pricecharting_price_sgd, 2) if pricecharting_price_sgd is not None else None,
        'yuyutei_price_sgd': round(yuyutei_price_sgd, 2) if yuyutei_price_sgd is not None else None,
        'listing_type': listing_type,
        'status': status or ('auction_active' if listing_type == 'auction' else 'active'),
        'starting_bid_sgd': round(starting_bid_sgd, 2) if starting_bid_sgd is not None else None,
        'current_bid_sgd': round(current_bid_sgd, 2) if current_bid_sgd is not None else None,
        'bid_increment_sgd': round(bid_increment_sgd, 2) if bid_increment_sgd is not None else None,
        'auction_end_time': auction_end_time,
        'anti_snipe_minutes': int(anti_snipe_minutes) if anti_snipe_minutes is not None else None,
    }
    response = get_client().table('listings').insert(payload).execute()
    listing = extract_single(response)
    if listing is None:
        raise RuntimeError('Failed to create listing row.')
    return listing


def get_listing_by_id(listing_id: str) -> dict[str, Any] | None:
    """Return a listing by primary key."""

    response = get_client().table('listings').select('*').eq('id', listing_id).limit(1).execute()
    return extract_single(response)


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


def get_claim_pending_listings_for_seller(seller_id: str) -> list[dict[str, Any]]:
    """Return claim-pending listings for a seller ordered by newest first."""

    response = (
        get_client()
        .table('listings')
        .select('*')
        .eq('seller_id', seller_id)
        .eq('status', 'claim_pending')
        .order('created_at', desc=True)
        .execute()
    )
    return extract_many(response)


def get_open_listings_for_seller(seller_id: str) -> list[dict[str, Any]]:
    """Return active and claim-pending listings for a seller ordered newest first."""

    response = (
        get_client()
        .table('listings')
        .select('*')
        .eq('seller_id', seller_id)
        .in_('status', ['active', 'claim_pending'])
        .order('created_at', desc=True)
        .execute()
    )
    return extract_many(response)


def count_claim_pending_listings_for_seller(seller_id: str) -> int:
    """Return the number of claim-pending listings for a seller."""

    response = (
        get_client()
        .table('listings')
        .select('id', count='exact')
        .eq('seller_id', seller_id)
        .eq('status', 'claim_pending')
        .execute()
    )
    return int(response.count or 0)


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


def count_active_auctions_for_seller(seller_id: str) -> int:
    """Return the number of live auctions for a seller."""

    response = (
        get_client()
        .table('listings')
        .select('id', count='exact')
        .eq('seller_id', seller_id)
        .eq('listing_type', 'auction')
        .eq('status', 'auction_active')
        .execute()
    )
    return int(response.count or 0)


def get_live_auction_listings(*, limit: int = 25) -> list[dict[str, Any]]:
    """Return active auctions that may need message refreshes or closeout."""

    response = (
        get_client()
        .table('listings')
        .select('*')
        .eq('listing_type', 'auction')
        .eq('status', 'auction_active')
        .order('auction_end_time', desc=False)
        .limit(limit)
        .execute()
    )
    return extract_many(response)


def update_listing_status(*, listing_id: str, status: str) -> dict[str, Any] | None:
    """Update a listing status and return the updated row."""

    response = get_client().table('listings').update({'status': status}).eq('id', listing_id).execute()
    return extract_single(response)


def update_listing_auction_end_time(*, listing_id: str, auction_end_time: str) -> dict[str, Any] | None:
    """Update the auction end time for a live auction listing."""

    response = (
        get_client()
        .table('listings')
        .update({'auction_end_time': auction_end_time})
        .eq('id', listing_id)
        .eq('listing_type', 'auction')
        .eq('status', 'auction_active')
        .execute()
    )
    return extract_single(response)


def get_listing_by_posted_message(*, posted_message_id: int, posted_channel_id: int | None = None) -> dict[str, Any] | None:
    """Return an active or claim-pending listing by channel message identity."""

    query = (
        get_client()
        .table('listings')
        .select('*')
        .eq('posted_message_id', posted_message_id)
        .in_('status', ['active', 'claim_pending', 'auction_active'])
    )
    if posted_channel_id is not None:
        query = query.eq('posted_channel_id', posted_channel_id)
    response = query.limit(1).execute()
    return extract_single(response)
