"""Shared payment-request helpers for claims and seller verification."""

from __future__ import annotations

from typing import Any

from db.claims import ensure_payment_reference


def payment_methods_text(seller_config: dict[str, Any] | None) -> str:
    """Return a compact payment-method label for buyer messages."""

    return ', '.join((seller_config or {}).get('payment_methods') or ['PayNow'])


def paynow_text(seller_config: dict[str, Any] | None) -> str:
    """Return the configured PayNow identifier line, when present."""

    paynow_identifier = str((seller_config or {}).get('paynow_identifier') or '').strip()
    return f'PayNow: <code>{paynow_identifier}</code>\n' if paynow_identifier else ''


def ensure_payment_request_for_claim(*, claim: dict[str, Any]) -> dict[str, Any]:
    """Ensure the active winning claim has a payment reference and pending state."""

    return ensure_payment_reference(claim_id=str(claim['id']))


def build_buyer_payment_message(
    *,
    listing: dict[str, Any],
    claim: dict[str, Any],
    seller_config: dict[str, Any] | None,
    deadline_hours: int,
    intro: str,
) -> str:
    """Build the buyer-facing payment instructions message."""

    return (
        f'<b>{intro}</b>\n\n'
        f'Item: <code>{listing.get("card_name")}</code>\n'
        f'Price: <code>SGD {float(listing.get("price_sgd") or 0):.2f}</code>\n'
        f'Payment methods: <code>{payment_methods_text(seller_config)}</code>\n'
        f'{paynow_text(seller_config)}'
        f'Reference: <code>{claim.get("payment_reference")}</code>\n'
        f'Deadline: <code>{deadline_hours}h</code>\n\n'
        'After payment, send your screenshot here in this bot chat.\n'
        'If you have multiple pending purchases, run <code>/pay</code> first and choose the correct reference.\n'
        'If you need to back out, run <code>/unclaim</code> before the seller marks payment received.'
    )


def build_seller_claim_notice(
    *,
    listing: dict[str, Any],
    claim: dict[str, Any] | None,
    buyer_display_name: str,
    buyer_username: str | None,
    deadline_hours: int,
    queue_position: int | None = None,
) -> str:
    """Build the seller-facing claim notification."""

    is_queued = queue_position is not None and queue_position > 1
    heading = '<b>Claim queued.</b>' if is_queued else '<b>New claim received.</b>'
    lines = [
        heading,
        '',
        f'Item: <code>{listing.get("card_name")}</code>',
        f'Buyer: <code>{buyer_display_name}</code>',
    ]
    if buyer_username:
        lines.append(f'Username: <code>@{buyer_username}</code>')
    if is_queued:
        lines.append(f'Queue position: <code>{queue_position}</code>')
    else:
        if claim and claim.get('payment_reference'):
            lines.append(f'Reference: <code>{claim.get("payment_reference")}</code>')
        lines.append(f'Payment deadline: <code>{deadline_hours}h</code>')
    return '\n'.join(lines)
