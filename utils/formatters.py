"""Formatting helpers for TCG Listing Bot messages."""

from __future__ import annotations

import html


def format_fixed_price_listing(
    *,
    card_name: str,
    game: str,
    price_sgd: float,
    condition_notes: str,
    custom_description: str,
    seller_display_name: str,
    payment_methods: list[str],
) -> str:
    """Build a basic fixed-price Telegram HTML listing from structured seller inputs."""

    safe_name = html.escape(card_name)
    safe_game = html.escape(game.title())
    safe_seller = html.escape(seller_display_name)
    safe_condition = html.escape(condition_notes) if condition_notes else 'Not specified'
    safe_description = html.escape(custom_description) if custom_description else ''
    payment_text = ', '.join(payment_methods) if payment_methods else 'Ask seller'
    safe_payment = html.escape(payment_text)

    lines = [
        f'🃏 <b>{safe_name}</b>',
        f'🎮 Game: <b>{safe_game}</b>',
        f'💰 Price: <b>SGD {price_sgd:.2f}</b>',
        f'✅ Seller: <b>{safe_seller}</b>',
        f'💳 Payment: <b>{safe_payment}</b>',
        f'📝 Condition: {safe_condition}',
    ]
    if safe_description:
        lines.append(f'📌 Notes: {safe_description}')
    lines.append('')
    lines.append('Reply with <b>Claim</b> to claim this item.')
    return '\n'.join(lines)



def format_sold_listing(
    *,
    card_name: str,
    game: str,
    price_sgd: float,
    condition_notes: str,
    custom_description: str,
    seller_display_name: str,
    payment_methods: list[str],
    buyer_display_name: str | None = None,
) -> str:
    """Build a SOLD version of the listing message for Telegram edits."""

    sold_text = format_fixed_price_listing(
        card_name=card_name,
        game=game,
        price_sgd=price_sgd,
        condition_notes=condition_notes,
        custom_description=custom_description,
        seller_display_name=seller_display_name,
        payment_methods=payment_methods,
    )
    sold_lines = [line for line in sold_text.split('\n') if 'Reply with <b>Claim</b>' not in line]
    header = '🔴 <b>SOLD</b>'
    if buyer_display_name:
        header += f' — <code>{html.escape(buyer_display_name)}</code>'
    return '\n'.join([header, ''] + sold_lines)
