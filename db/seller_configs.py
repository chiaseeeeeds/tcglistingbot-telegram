"""Seller configuration access helpers for TCG Listing Bot."""

from __future__ import annotations

from typing import Any

from db.client import extract_single, get_client


def get_seller_config_by_seller_id(seller_id: str) -> dict[str, Any] | None:
    """Fetch seller configuration by seller primary key."""

    response = (
        get_client()
        .table('seller_configs')
        .select('*')
        .eq('seller_id', seller_id)
        .limit(1)
        .execute()
    )
    return extract_single(response)


def ensure_seller_config(*, seller_id: str, primary_channel_name: str | None = None) -> dict[str, Any]:
    """Ensure a seller has a configuration row, creating one when missing."""

    existing = get_seller_config_by_seller_id(seller_id)
    if existing is not None:
        return existing

    payload = {
        'seller_id': seller_id,
        'primary_channel_name': primary_channel_name,
    }
    response = get_client().table('seller_configs').insert(payload).execute()
    config = extract_single(response)
    if config:
        return config
    refreshed = get_seller_config_by_seller_id(seller_id)
    if refreshed is None:
        raise RuntimeError('Failed to load seller config after insert.')
    return refreshed


def update_seller_setup(
    *,
    seller_id: str,
    seller_display_name: str,
    primary_channel_name: str,
    payment_methods: list[str],
    paynow_identifier: str,
    setup_complete: bool = True,
) -> dict[str, Any]:
    """Persist the first working seller setup slice."""

    payload = {
        'seller_display_name': seller_display_name,
        'primary_channel_name': primary_channel_name,
        'payment_methods': payment_methods,
        'paynow_identifier': paynow_identifier,
        'setup_complete': setup_complete,
    }
    response = (
        get_client()
        .table('seller_configs')
        .update(payload)
        .eq('seller_id', seller_id)
        .execute()
    )
    config = extract_single(response)
    if config:
        return config
    refreshed = get_seller_config_by_seller_id(seller_id)
    if refreshed is None:
        raise RuntimeError('Failed to load seller config after update.')
    return refreshed
