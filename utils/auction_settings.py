"""Helpers for auction-specific listing settings."""

from __future__ import annotations

from typing import Any


def resolve_listing_payment_deadline_hours(
    *,
    listing: dict[str, Any] | None,
    seller_config: dict[str, Any] | None,
    default_hours: int,
) -> int:
    """Resolve the payment deadline hours for a listing.

    Auction listings may override the seller default on a per-listing basis. All other
    listing types fall back to the seller configuration and finally the application default.
    """

    if listing is not None and str(listing.get('listing_type') or '') == 'auction':
        override = listing.get('auction_payment_deadline_hours')
        try:
            override_hours = int(override)
        except (TypeError, ValueError):
            override_hours = 0
        if override_hours > 0:
            return override_hours

    seller_value = (seller_config or {}).get('payment_deadline_hours')
    try:
        seller_hours = int(seller_value)
    except (TypeError, ValueError):
        seller_hours = 0
    if seller_hours > 0:
        return seller_hours

    return max(int(default_hours), 1)
