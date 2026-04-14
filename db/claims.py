"""Data access helpers for the claims domain."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from db.client import extract_many, extract_single, get_client
from db.rpc import call_rpc

OPEN_CLAIM_STATUSES: tuple[str, ...] = ('queued', 'confirmed', 'payment_pending')
WINNING_CLAIM_STATUSES: tuple[str, ...] = ('confirmed', 'payment_pending')



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



def get_claim_by_id(claim_id: str) -> dict[str, Any] | None:
    """Return a claim by primary key."""

    response = get_client().table('claims').select('*').eq('id', claim_id).limit(1).execute()
    return extract_single(response)



def get_open_claim_for_buyer(*, listing_id: str, buyer_telegram_id: int) -> dict[str, Any] | None:
    """Return the buyer's current open claim for a listing, if one exists."""

    response = (
        get_client()
        .table('claims')
        .select('*')
        .eq('listing_id', listing_id)
        .eq('buyer_telegram_id', buyer_telegram_id)
        .in_('status', list(OPEN_CLAIM_STATUSES))
        .order('queue_position', desc=False)
        .limit(1)
        .execute()
    )
    return extract_single(response)



def get_current_winning_claim(*, listing_id: str) -> dict[str, Any] | None:
    """Return the current winning claim for a listing, if one exists."""

    response = (
        get_client()
        .table('claims')
        .select('*')
        .eq('listing_id', listing_id)
        .in_('status', list(WINNING_CLAIM_STATUSES))
        .order('queue_position', desc=False)
        .limit(1)
        .execute()
    )
    return extract_single(response)



def get_due_payment_claims(*, now_utc: datetime | None = None, limit: int = 25) -> list[dict[str, Any]]:
    """Return claims whose payment deadlines have expired and still need worker action."""

    due_time = (now_utc or datetime.now(timezone.utc)).isoformat()
    response = (
        get_client()
        .table('claims')
        .select('*')
        .in_('status', list(WINNING_CLAIM_STATUSES))
        .lte('payment_deadline', due_time)
        .order('payment_deadline', desc=False)
        .limit(limit)
        .execute()
    )
    return extract_many(response)


def list_open_payment_claims_for_buyer(*, buyer_telegram_id: int) -> list[dict[str, Any]]:
    """Return open winning claims for a buyer ordered by newest confirmation first."""

    response = (
        get_client()
        .table('claims')
        .select('*')
        .eq('buyer_telegram_id', buyer_telegram_id)
        .in_('status', list(WINNING_CLAIM_STATUSES))
        .order('confirmed_at', desc=True)
        .order('claimed_at', desc=True)
        .execute()
    )
    return extract_many(response)


def get_claim_by_payment_reference(*, payment_reference: str) -> dict[str, Any] | None:
    """Return the claim that owns a payment reference, if any."""

    response = (
        get_client()
        .table('claims')
        .select('*')
        .eq('payment_reference', payment_reference)
        .limit(1)
        .execute()
    )
    return extract_single(response)


def ensure_payment_reference(*, claim_id: str) -> dict[str, Any]:
    """Ensure the claim has a payment reference and is marked payment-pending."""

    claim = get_claim_by_id(claim_id)
    if claim is None:
        raise RuntimeError(f'Claim not found: {claim_id}')

    payment_reference = str(claim.get('payment_reference') or '').strip()
    if not payment_reference:
        normalized_id = claim_id.replace('-', '').upper()
        payment_reference = f'TCG-{normalized_id[:8]}'

    next_status = 'payment_pending' if str(claim.get('status') or '') in WINNING_CLAIM_STATUSES else claim.get('status')
    payload = {
        'payment_reference': payment_reference,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }
    if next_status == 'payment_pending' and str(claim.get('status') or '') != 'payment_pending':
        payload['status'] = 'payment_pending'

    response = get_client().table('claims').update(payload).eq('id', claim_id).execute()
    updated = extract_single(response)
    if updated is None:
        refreshed = get_claim_by_id(claim_id)
        if refreshed is None:
            raise RuntimeError(f'Failed to refresh claim after payment reference update: {claim_id}')
        return refreshed
    return updated


def mark_payment_prompt_sent(*, claim_id: str, message_id: int | None) -> dict[str, Any] | None:
    """Persist that the bot sent payment instructions to the buyer."""

    payload: dict[str, Any] = {
        'payment_prompt_sent': True,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }
    if message_id is not None:
        payload['payment_prompt_message_id'] = message_id
    response = get_client().table('claims').update(payload).eq('id', claim_id).execute()
    return extract_single(response)


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




async def record_auction_bid_atomic(
    *,
    listing_id: str,
    buyer_telegram_id: int,
    buyer_username: str | None,
    buyer_display_name: str,
    bid_amount_sgd: float,
) -> dict[str, Any]:
    """Atomically record an auction bid and return the updated bid state."""

    data = await call_rpc(
        'record_auction_bid_atomic',
        {
            'p_listing_id': listing_id,
            'p_buyer_telegram_id': buyer_telegram_id,
            'p_buyer_username': buyer_username,
            'p_buyer_display_name': buyer_display_name,
            'p_bid_amount_sgd': round(bid_amount_sgd, 2),
        },
    )
    if isinstance(data, list):
        return data[0]
    if isinstance(data, dict):
        return data
    raise RuntimeError('Auction bid RPC returned no payload.')


async def close_auction_atomic(*, listing_id: str, payment_deadline_hours: int) -> dict[str, Any]:
    """Close a due auction atomically and promote the highest bidder when present."""

    payment_deadline = datetime.now(timezone.utc) + timedelta(hours=payment_deadline_hours)
    data = await call_rpc(
        'close_auction_atomic',
        {
            'p_listing_id': listing_id,
            'p_payment_deadline': payment_deadline.isoformat(),
        },
    )
    if isinstance(data, list):
        return data[0]
    if isinstance(data, dict):
        return data
    raise RuntimeError('Close auction RPC returned no payload.')

async def advance_claim_queue(*, claim_id: str, payment_deadline_hours: int) -> dict[str, Any]:
    """Expire the current winning claim and promote the next queued claim when available."""

    next_payment_deadline = datetime.now(timezone.utc) + timedelta(hours=payment_deadline_hours)
    data = await call_rpc(
        'advance_claim_queue',
        {
            'p_claim_id': claim_id,
            'p_next_payment_deadline': next_payment_deadline.isoformat(),
        },
    )
    if isinstance(data, list):
        return data[0]
    if isinstance(data, dict):
        return data
    raise RuntimeError('Advance claim queue RPC returned no payload.')
