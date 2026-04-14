"""Database helpers for claim payment proof review flows."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from db.client import extract_many, extract_single, get_client


def create_payment_proof(
    *,
    claim_id: str,
    listing_id: str,
    seller_id: str,
    buyer_telegram_id: int,
    payment_reference: str,
    storage_path: str,
    telegram_file_id: str,
    telegram_message_id: int | None,
    buyer_caption: str | None,
) -> dict[str, Any]:
    """Create or replace the current submitted proof for a claim."""

    client = get_client()
    client.table('claim_payment_proofs').update(
        {
            'status': 'replaced',
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }
    ).eq('claim_id', claim_id).eq('status', 'submitted').execute()

    response = client.table('claim_payment_proofs').insert(
        {
            'claim_id': claim_id,
            'listing_id': listing_id,
            'seller_id': seller_id,
            'buyer_telegram_id': buyer_telegram_id,
            'payment_reference': payment_reference,
            'storage_path': storage_path,
            'telegram_file_id': telegram_file_id,
            'telegram_message_id': telegram_message_id,
            'buyer_caption': buyer_caption,
        }
    ).execute()
    proof = extract_single(response)
    if proof is None:
        raise RuntimeError('Failed to create payment proof row.')
    return proof


def get_payment_proof_by_id(proof_id: str) -> dict[str, Any] | None:
    """Fetch a payment proof by primary key."""

    response = get_client().table('claim_payment_proofs').select('*').eq('id', proof_id).limit(1).execute()
    return extract_single(response)


def get_latest_payment_proof_for_claim(*, claim_id: str) -> dict[str, Any] | None:
    """Return the newest payment proof submitted for a claim."""

    response = (
        get_client()
        .table('claim_payment_proofs')
        .select('*')
        .eq('claim_id', claim_id)
        .order('created_at', desc=True)
        .limit(1)
        .execute()
    )
    return extract_single(response)


def list_submitted_payment_proofs_for_buyer(*, buyer_telegram_id: int) -> list[dict[str, Any]]:
    """Return still-pending payment proofs for a buyer."""

    response = (
        get_client()
        .table('claim_payment_proofs')
        .select('*')
        .eq('buyer_telegram_id', buyer_telegram_id)
        .eq('status', 'submitted')
        .order('created_at', desc=True)
        .execute()
    )
    return extract_many(response)


def review_payment_proof(
    *,
    proof_id: str,
    seller_id: str,
    reviewed_by_telegram_id: int,
    status: str,
    seller_note: str | None = None,
) -> dict[str, Any] | None:
    """Mark a submitted payment proof as approved or rejected."""

    if status not in {'approved', 'rejected'}:
        raise ValueError(f'Unsupported proof review status: {status}')

    response = (
        get_client()
        .table('claim_payment_proofs')
        .update(
            {
                'status': status,
                'seller_note': seller_note,
                'reviewed_at': datetime.now(timezone.utc).isoformat(),
                'reviewed_by_telegram_id': reviewed_by_telegram_id,
                'updated_at': datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq('id', proof_id)
        .eq('seller_id', seller_id)
        .eq('status', 'submitted')
        .execute()
    )
    return extract_single(response)
