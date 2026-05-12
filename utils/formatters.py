"""Formatting helpers for TCG Listing Bot messages."""

from __future__ import annotations

import html
from datetime import datetime, timezone


def _format_auction_end_absolute(auction_end_time: str | None) -> str:
    if not auction_end_time:
        return 'Unknown'
    try:
        normalized = str(auction_end_time).replace('Z', '+00:00')
        end_time = datetime.fromisoformat(normalized)
    except ValueError:
        return 'Unknown'
    return end_time.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


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



def _format_auction_time_remaining(auction_end_time: str | None) -> str:
    if not auction_end_time:
        return 'Unknown'
    try:
        normalized = str(auction_end_time).replace('Z', '+00:00')
        end_time = datetime.fromisoformat(normalized)
    except ValueError:
        return 'Unknown'
    remaining = end_time - datetime.now(timezone.utc)
    total_seconds = int(remaining.total_seconds())
    if total_seconds <= 0:
        return 'Ended'
    if total_seconds >= 86400:
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        return f'{days}d {hours}h'
    if total_seconds >= 3600:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f'{hours}h {minutes}m'
    minutes = max(1, total_seconds // 60)
    return f'{minutes}m'


def auction_refresh_marker(auction_end_time: str | None) -> str:
    if not auction_end_time:
        return 'unknown'
    try:
        normalized = str(auction_end_time).replace('Z', '+00:00')
        end_time = datetime.fromisoformat(normalized)
    except ValueError:
        return 'unknown'
    remaining = int((end_time - datetime.now(timezone.utc)).total_seconds())
    if remaining <= 0:
        return 'closed'
    if remaining > 86400:
        return f'days:{remaining // 86400}'
    if remaining > 3600:
        return f'hours:{remaining // 3600}'
    return f'mins:{max(1, remaining // 60)}'


def format_auction_listing(
    *,
    card_name: str,
    game: str,
    starting_bid_sgd: float,
    current_bid_sgd: float | None,
    bid_increment_sgd: float | None = None,
    anti_snipe_minutes: int | None = None,
    condition_notes: str,
    custom_description: str,
    seller_display_name: str,
    auction_end_time: str | None,
    status: str = 'auction_active',
) -> str:
    safe_name = html.escape(card_name)
    safe_game = html.escape(game.title())
    safe_seller = html.escape(seller_display_name)
    safe_condition = html.escape(condition_notes) if condition_notes else 'Not specified'
    safe_description = html.escape(custom_description) if custom_description else ''
    current_bid = current_bid_sgd if current_bid_sgd is not None else starting_bid_sgd
    time_left = _format_auction_time_remaining(auction_end_time)
    end_absolute = _format_auction_end_absolute(auction_end_time)

    lines = [
        f'🔨 <b>{safe_name}</b>',
        f'🎮 Game: <b>{safe_game}</b>',
        f'💰 Current bid: <b>SGD {current_bid:.2f}</b>',
        f'🏁 Starting bid: <b>SGD {starting_bid_sgd:.2f}</b>',
        f'📈 Min increment: <b>SGD {bid_increment_sgd:.2f}</b>' if bid_increment_sgd is not None else '📈 Min increment: <b>Ask seller</b>',
        f'🛡️ Anti-snipe: <b>{anti_snipe_minutes}m extension</b>' if anti_snipe_minutes and anti_snipe_minutes > 0 else '🛡️ Anti-snipe: <b>Off</b>',
        f'🗓️ Ends: <b>{html.escape(end_absolute)}</b>',
        f'⏳ Time left: <b>{html.escape(time_left)}</b>',
        f'✅ Seller: <b>{safe_seller}</b>',
        f'📝 Condition: {safe_condition}',
    ]
    if safe_description:
        lines.append(f'📜 Rules: {safe_description}')
    lines.append('')
    if status == 'auction_closed':
        lines.append('Auction has ended.')
    else:
        lines.append('Reply with your bid amount like <b>12</b> or <b>12.50</b> to bid.')
    return '\n'.join(lines)
