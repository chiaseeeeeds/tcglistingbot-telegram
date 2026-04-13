"""Admin handler registrations for TCG Listing Bot."""

from __future__ import annotations

import asyncio
from typing import Any

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import get_config
from db.client import get_client



def _is_admin(telegram_id: int | None) -> bool:
    if telegram_id is None:
        return False
    return telegram_id in set(get_config().bot_admin_telegram_ids)



def _count_rows(table: str, *, filters: list[tuple[str, str, Any]] | None = None) -> int:
    query = get_client().table(table).select('id', count='exact')
    for operator, field, value in filters or []:
        if operator == 'eq':
            query = query.eq(field, value)
        elif operator == 'neq':
            query = query.neq(field, value)
        elif operator == 'in':
            query = query.in_(field, value)
        elif operator == 'not_null':
            query = query.not_.is_(field, 'null')
        else:
            raise ValueError(f'Unsupported filter operator: {operator}')
    response = query.execute()
    return int(response.count or 0)



def _admin_snapshot() -> dict[str, int]:
    return {
        'sellers_total': _count_rows('sellers'),
        'sellers_active': _count_rows('sellers', filters=[('eq', 'is_active', True)]),
        'setup_complete': _count_rows('seller_configs', filters=[('eq', 'setup_complete', True)]),
        'listings_active': _count_rows('listings', filters=[('eq', 'status', 'active')]),
        'listings_claim_pending': _count_rows('listings', filters=[('eq', 'status', 'claim_pending')]),
        'listings_auction_active': _count_rows('listings', filters=[('eq', 'status', 'auction_active')]),
        'listings_sold': _count_rows('listings', filters=[('eq', 'status', 'sold')]),
        'claims_total': _count_rows('claims'),
        'claims_queued': _count_rows('claims', filters=[('eq', 'status', 'queued')]),
        'claims_payment_pending': _count_rows('claims', filters=[('eq', 'status', 'payment_pending')]),
        'transactions_total': _count_rows('transactions'),
        'cards_pokemon': _count_rows('cards', filters=[('eq', 'game', 'pokemon')]),
        'cards_onepiece': _count_rows('cards', filters=[('eq', 'game', 'onepiece')]),
        'cards_jp_named': _count_rows('cards', filters=[('not_null', 'card_name_jp', None)]),
        'cards_pricecharting_linked': _count_rows('cards', filters=[('not_null', 'pricecharting_id', None)]),
    }


async def admin_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show an operational Phase 1 snapshot for bot admins."""

    if update.effective_message is None:
        return
    if not _is_admin(getattr(update.effective_user, 'id', None)):
        await update.effective_message.reply_text('This command is restricted to bot admins.', parse_mode='HTML')
        return

    snapshot = await asyncio.to_thread(_admin_snapshot)
    scheduler = context.application.bot_data.get('scheduler')
    scheduler_running = bool(scheduler is not None and getattr(scheduler, 'running', False))
    jobs = []
    if scheduler is not None:
        try:
            jobs = sorted(job.id for job in scheduler.get_jobs())
        except Exception:
            jobs = []

    config = get_config()
    lines = [
        '<b>Admin Snapshot</b>',
        '',
        f'Runtime mode: <code>{"webhook" if config.telegram_webhook_url else "polling"}</code>',
        f'Scheduler running: <code>{"yes" if scheduler_running else "no"}</code>',
        f'Scheduler jobs: <code>{", ".join(jobs) if jobs else "none"}</code>',
        '',
        '<b>Sellers</b>',
        f'Total sellers: <code>{snapshot["sellers_total"]}</code>',
        f'Active sellers: <code>{snapshot["sellers_active"]}</code>',
        f'Setup complete: <code>{snapshot["setup_complete"]}</code>',
        '',
        '<b>Listings</b>',
        f'Active: <code>{snapshot["listings_active"]}</code>',
        f'Claim pending: <code>{snapshot["listings_claim_pending"]}</code>',
        f'Auction active: <code>{snapshot["listings_auction_active"]}</code>',
        f'Sold: <code>{snapshot["listings_sold"]}</code>',
        '',
        '<b>Claims</b>',
        f'Total claims: <code>{snapshot["claims_total"]}</code>',
        f'Queued: <code>{snapshot["claims_queued"]}</code>',
        f'Payment pending: <code>{snapshot["claims_payment_pending"]}</code>',
        f'Transactions: <code>{snapshot["transactions_total"]}</code>',
        '',
        '<b>Catalog Coverage</b>',
        f'Pokémon cards: <code>{snapshot["cards_pokemon"]}</code>',
        f'One Piece cards: <code>{snapshot["cards_onepiece"]}</code>',
        f'Japanese-name rows: <code>{snapshot["cards_jp_named"]}</code>',
        f'PriceCharting-linked rows: <code>{snapshot["cards_pricecharting_linked"]}</code>',
    ]
    if snapshot['cards_onepiece'] < 100 or snapshot['cards_jp_named'] < 100:
        lines.extend(
            [
                '',
                '⚠️ <b>Launch-scope warning</b>',
                'The database still lacks meaningful One Piece / Japanese catalog coverage, so strict Phase 1 launch scope is not fully satisfied yet.',
            ]
        )

    await update.effective_message.reply_text('\n'.join(lines), parse_mode='HTML')



def register_admin_handlers(application: Application) -> None:
    """Register admin-related command handlers on the Telegram application."""

    application.add_handler(CommandHandler('admin', admin_status))
