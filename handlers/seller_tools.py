"""Seller utility handler registrations for TCG Listing Bot."""

from __future__ import annotations

import asyncio
import html
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from db.blacklist import (
    count_blacklist_entries,
    list_blacklist_entries,
    remove_blacklist_entry,
    upsert_blacklist_entry,
)
from db.claims import get_claims_for_listing, get_current_winning_claim
from db.idempotency import register_processed_event
from db.listings import (
    count_active_listings_for_seller,
    count_claim_pending_listings_for_seller,
    get_listing_by_id,
    get_open_listings_for_seller,
)
from db.sellers import get_seller_by_telegram_id, set_vacation_mode
from db.transactions import get_transactions_for_seller
from handlers.transactions import complete_sale_for_listing

PAGE_SIZE = 5


def _command_event_key(update: Update, action: str) -> str | None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or getattr(message, 'chat', None) is None:
        return None
    return f'{action}:{message.chat.id}:{message.message_id}:{user.id}'


def _callback_event_key(query_id: str, action: str) -> str:
    return f'{action}:{query_id}'


async def _require_seller(update: Update) -> dict[str, Any] | None:
    if update.effective_user is None or update.effective_message is None:
        return None
    seller = await asyncio.to_thread(get_seller_by_telegram_id, update.effective_user.id)
    if seller is None:
        await update.effective_message.reply_text(
            'Seller profile not found. Run <code>/start</code> or <code>/setup</code> first.',
            parse_mode='HTML',
        )
    return seller


async def _require_seller_from_query(update: Update) -> tuple[dict[str, Any] | None, Any | None]:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return None, query
    await query.answer()
    seller = await asyncio.to_thread(get_seller_by_telegram_id, update.effective_user.id)
    if seller is None:
        await query.edit_message_text(
            'Seller profile not found. Run /start or /setup first.',
        )
        return None, query
    return seller, query



def _dashboard_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton('Inventory', callback_data='seller:inventory:0'),
                InlineKeyboardButton('Sales', callback_data='seller:sales'),
            ],
            [
                InlineKeyboardButton('Blacklist', callback_data='seller:blacklist'),
                InlineKeyboardButton('Vacation', callback_data='seller:vacation'),
            ],
            [InlineKeyboardButton('Refresh', callback_data='seller:home')],
        ]
    )



def _back_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton('Home', callback_data='seller:home')]])



def _inventory_nav_keyboard(*, page: int, has_prev: bool, has_next: bool) -> InlineKeyboardMarkup:
    nav_row: list[InlineKeyboardButton] = []
    if has_prev:
        nav_row.append(InlineKeyboardButton('◀ Prev', callback_data=f'seller:inventory:{page - 1}'))
    nav_row.append(InlineKeyboardButton('Home', callback_data='seller:home'))
    if has_next:
        nav_row.append(InlineKeyboardButton('Next ▶', callback_data=f'seller:inventory:{page + 1}'))
    return InlineKeyboardMarkup([nav_row])



def _detail_keyboard(*, page: int, listing_id: str, status: str, has_claims: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if status == 'claim_pending':
        rows.append([InlineKeyboardButton('Mark Paid', callback_data=f'seller:paid_confirm:{page}:{listing_id}')])
    if has_claims:
        rows.append([InlineKeyboardButton('View Queue', callback_data=f'seller:queue:{page}:{listing_id}')])
    rows.append(
        [
            InlineKeyboardButton('Back', callback_data=f'seller:inventory:{page}'),
            InlineKeyboardButton('Refresh', callback_data=f'seller:detail:{page}:{listing_id}'),
            InlineKeyboardButton('Home', callback_data='seller:home'),
        ]
    )
    return InlineKeyboardMarkup(rows)



def _confirm_paid_keyboard(*, page: int, listing_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton('✅ Confirm Mark Paid', callback_data=f'seller:paid_exec:{page}:{listing_id}')],
            [
                InlineKeyboardButton('Back', callback_data=f'seller:detail:{page}:{listing_id}'),
                InlineKeyboardButton('Home', callback_data='seller:home'),
            ],
        ]
    )



def _vacation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton('On 3d', callback_data='seller:vac_on:3'),
                InlineKeyboardButton('On 7d', callback_data='seller:vac_on:7'),
            ],
            [InlineKeyboardButton('Turn Off', callback_data='seller:vac_off')],
            [InlineKeyboardButton('Home', callback_data='seller:home')],
        ]
    )


async def _dashboard_home_screen(seller: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    active_count, pending_count, blacklist_count, recent_transactions = await asyncio.gather(
        asyncio.to_thread(count_active_listings_for_seller, str(seller['id'])),
        asyncio.to_thread(count_claim_pending_listings_for_seller, str(seller['id'])),
        asyncio.to_thread(count_blacklist_entries, seller_id=str(seller['id'])),
        asyncio.to_thread(get_transactions_for_seller, str(seller['id']), limit=3),
    )
    lines = [
        '<b>Seller Dashboard</b>',
        '',
        f'Seller: <code>{html.escape(str(seller.get("telegram_display_name") or "Seller"))}</code>',
        f'Active listings: <code>{active_count}</code>',
        f'Claim-pending listings: <code>{pending_count}</code>',
        f'Verified sales total: <code>SGD {float(seller.get("total_sales_sgd") or 0):.2f}</code>',
        f'Blacklist entries: <code>{blacklist_count}</code>',
        f'Vacation mode: <code>{"on" if seller.get("vacation_mode") else "off"}</code>',
    ]
    if seller.get('vacation_until'):
        lines.append(f'Vacation until: <code>{seller.get("vacation_until")}</code>')
    if recent_transactions:
        lines.extend(['', '<b>Recent Sales</b>'])
        for transaction in recent_transactions:
            lines.append(
                f'• <code>SGD {float(transaction.get("final_price_sgd") or 0):.2f}</code> — '
                f'{html.escape(str(transaction.get("buyer_display_name") or transaction.get("buyer_telegram_id")))}'
            )
    return '\n'.join(lines), _dashboard_home_keyboard()


async def _inventory_screen(seller: dict[str, Any], *, page: int) -> tuple[str, InlineKeyboardMarkup]:
    listings = await asyncio.to_thread(get_open_listings_for_seller, str(seller['id']))
    if not listings:
        return '<b>Inventory</b>\n\nYou have no active or claim-pending listings.', _back_home_keyboard()

    start = page * PAGE_SIZE
    page_rows = listings[start : start + PAGE_SIZE]
    has_prev = page > 0
    has_next = start + PAGE_SIZE < len(listings)

    lines = ['<b>Inventory</b>', '']
    rows: list[list[InlineKeyboardButton]] = []
    for listing in page_rows:
        status = str(listing.get('status') or 'active')
        label = f'{listing.get("posted_message_id")} · {listing.get("card_name")}'
        if len(label) > 36:
            label = label[:33] + '...'
        rows.append(
            [
                InlineKeyboardButton(
                    f'{"🟡" if status == "claim_pending" else "🟢"} {label}',
                    callback_data=f'seller:detail:{page}:{listing.get("id")}',
                )
            ]
        )
        lines.append(
            f'• <code>{listing.get("posted_message_id")}</code> — '
            f'{html.escape(str(listing.get("card_name") or "Card"))} '
            f'(<code>{status}</code>, <code>SGD {float(listing.get("price_sgd") or 0):.2f}</code>)'
        )

    rows.extend(_inventory_nav_keyboard(page=page, has_prev=has_prev, has_next=has_next).inline_keyboard)
    return '\n'.join(lines), InlineKeyboardMarkup(rows)


async def _listing_detail_screen(
    seller: dict[str, Any],
    *,
    listing_id: str,
    page: int,
) -> tuple[str, InlineKeyboardMarkup]:
    listing = await asyncio.to_thread(get_listing_by_id, listing_id)
    if listing is None or str(listing.get('seller_id')) != str(seller['id']):
        return 'Listing not found for this seller.', _back_home_keyboard()

    claims = await asyncio.to_thread(get_claims_for_listing, str(listing['id']))
    winning_claim = next(
        (claim for claim in claims if str(claim.get('status') or '') in {'confirmed', 'payment_pending'}),
        None,
    )
    queue_count = len([claim for claim in claims if str(claim.get('status') or '') in {'queued', 'confirmed', 'payment_pending'}])
    lines = [
        '<b>Listing Detail</b>',
        '',
        f'Card: <code>{html.escape(str(listing.get("card_name") or "Card"))}</code>',
        f'Price: <code>SGD {float(listing.get("price_sgd") or 0):.2f}</code>',
        f'Status: <code>{listing.get("status")}</code>',
        f'Message ID: <code>{listing.get("posted_message_id")}</code>',
        f'Game: <code>{listing.get("game")}</code>',
        f'Queue size: <code>{queue_count}</code>',
    ]
    if winning_claim is not None:
        lines.append(
            f'Current winner: <code>{html.escape(str(winning_claim.get("buyer_display_name") or winning_claim.get("buyer_telegram_id")))}</code>'
        )
        if winning_claim.get('payment_deadline'):
            lines.append(f'Deadline: <code>{winning_claim.get("payment_deadline")}</code>')
    return '\n'.join(lines), _detail_keyboard(
        page=page,
        listing_id=str(listing['id']),
        status=str(listing.get('status') or ''),
        has_claims=bool(claims),
    )


async def _queue_screen(seller: dict[str, Any], *, listing_id: str, page: int) -> tuple[str, InlineKeyboardMarkup]:
    listing = await asyncio.to_thread(get_listing_by_id, listing_id)
    if listing is None or str(listing.get('seller_id')) != str(seller['id']):
        return 'Listing not found for this seller.', _back_home_keyboard()

    claims = await asyncio.to_thread(get_claims_for_listing, str(listing['id']))
    lines = ['<b>Claim Queue</b>', '', f'Item: <code>{html.escape(str(listing.get("card_name") or "Card"))}</code>']
    if not claims:
        lines.append('No claims recorded yet.')
    else:
        for claim in claims:
            lines.append(
                f'• <code>#{claim.get("queue_position")}</code> — '
                f'{html.escape(str(claim.get("buyer_display_name") or claim.get("buyer_telegram_id")))} '
                f'(<code>{claim.get("status")}</code>)'
            )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton('Back', callback_data=f'seller:detail:{page}:{listing_id}'),
                InlineKeyboardButton('Refresh', callback_data=f'seller:queue:{page}:{listing_id}'),
            ],
            [InlineKeyboardButton('Home', callback_data='seller:home')],
        ]
    )
    return '\n'.join(lines), keyboard


async def _sales_screen(seller: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    transactions = await asyncio.to_thread(get_transactions_for_seller, str(seller['id']), limit=15)
    if not transactions:
        return '<b>Recent Sales</b>\n\nNo completed sales yet.', _back_home_keyboard()

    lines = ['<b>Recent Sales</b>', '']
    for transaction in transactions:
        lines.append(
            f'• <code>{transaction.get("completed_at")}</code> — '
            f'<code>SGD {float(transaction.get("final_price_sgd") or 0):.2f}</code> — '
            f'{html.escape(str(transaction.get("buyer_display_name") or transaction.get("buyer_telegram_id")))}'
        )
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton('Refresh', callback_data='seller:sales')],
            [InlineKeyboardButton('Home', callback_data='seller:home')],
        ]
    )
    return '\n'.join(lines), keyboard


async def _blacklist_screen(seller: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    entries = await asyncio.to_thread(list_blacklist_entries, seller_id=str(seller['id']))
    lines = ['<b>Blacklist</b>', '']
    if not entries:
        lines.append('Your blacklist is empty.')
    else:
        for entry in entries[:15]:
            reason = entry.get('reason') or 'No reason recorded'
            lines.append(
                f'• <code>{entry.get("blocked_telegram_id")}</code> — {html.escape(str(reason))}'
            )
    lines.extend(
        [
            '',
            'Use <code>/blacklist add &lt;telegram_id&gt; [reason]</code> to add entries.',
            'Use <code>/blacklist remove &lt;telegram_id&gt;</code> to remove entries.',
        ]
    )
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton('Refresh', callback_data='seller:blacklist')],
            [InlineKeyboardButton('Home', callback_data='seller:home')],
        ]
    )
    return '\n'.join(lines), keyboard


async def _vacation_screen(seller: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    lines = ['<b>Vacation Mode</b>', '']
    lines.append(f'Status: <code>{"on" if seller.get("vacation_mode") else "off"}</code>')
    if seller.get('vacation_until'):
        lines.append(f'Until: <code>{seller.get("vacation_until")}</code>')
    lines.append('')
    lines.append('While vacation mode is on, new claims are rejected automatically.')
    return '\n'.join(lines), _vacation_keyboard()


async def _render_dashboard_message(update: Update, *, text: str, reply_markup: InlineKeyboardMarkup) -> None:
    query = update.callback_query
    if query is not None:
        try:
            await query.edit_message_text(text=text, parse_mode='HTML', reply_markup=reply_markup)
        except Exception:
            await query.message.reply_text(text=text, parse_mode='HTML', reply_markup=reply_markup)
        return
    if update.effective_message is not None:
        await update.effective_message.reply_text(text, parse_mode='HTML', reply_markup=reply_markup)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    seller = await _require_seller(update)
    if seller is None:
        return
    text, keyboard = await _dashboard_home_screen(seller)
    await _render_dashboard_message(update, text=text, reply_markup=keyboard)


async def inventory_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    seller = await _require_seller(update)
    if seller is None:
        return
    text, keyboard = await _inventory_screen(seller, page=0)
    await _render_dashboard_message(update, text=text, reply_markup=keyboard)


async def sales_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    seller = await _require_seller(update)
    if seller is None:
        return
    text, keyboard = await _sales_screen(seller)
    await _render_dashboard_message(update, text=text, reply_markup=keyboard)


async def blacklist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    seller = await _require_seller(update)
    if seller is None:
        return

    args = list(context.args)
    if not args or args[0].lower() == 'list':
        text, keyboard = await _blacklist_screen(seller)
        await _render_dashboard_message(update, text=text, reply_markup=keyboard)
        return

    action = args[0].lower()
    if action not in {'add', 'remove'}:
        await update.effective_message.reply_text(
            'Usage:\n<code>/blacklist list</code>\n<code>/blacklist add &lt;telegram_id&gt; [reason]</code>\n<code>/blacklist remove &lt;telegram_id&gt;</code>',
            parse_mode='HTML',
        )
        return

    if len(args) < 2 or not args[1].lstrip('-').isdigit():
        await update.effective_message.reply_text('Provide a numeric Telegram ID.', parse_mode='HTML')
        return

    blocked_telegram_id = int(args[1])
    if action == 'add':
        reason = ' '.join(args[2:]).strip() or 'Seller blocked buyer'
        event_key = _command_event_key(update, 'blacklist-add')
        if event_key is not None:
            first_seen = await asyncio.to_thread(
                register_processed_event,
                source='seller_command',
                event_key=event_key,
                metadata={'seller_id': str(seller['id']), 'blocked_telegram_id': blocked_telegram_id},
            )
            if not first_seen:
                return
        entry = await asyncio.to_thread(
            upsert_blacklist_entry,
            seller_id=str(seller['id']),
            blocked_telegram_id=blocked_telegram_id,
            reason=reason,
        )
        await update.effective_message.reply_text(
            f'Added blacklist entry for <code>{entry.get("blocked_telegram_id")}</code>.',
            parse_mode='HTML',
        )
        return

    event_key = _command_event_key(update, 'blacklist-remove')
    if event_key is not None:
        first_seen = await asyncio.to_thread(
            register_processed_event,
            source='seller_command',
            event_key=event_key,
            metadata={'seller_id': str(seller['id']), 'blocked_telegram_id': blocked_telegram_id},
        )
        if not first_seen:
            return
    removed = await asyncio.to_thread(
        remove_blacklist_entry,
        seller_id=str(seller['id']),
        blocked_telegram_id=blocked_telegram_id,
    )
    if removed:
        await update.effective_message.reply_text(
            f'Removed blacklist entry for <code>{blocked_telegram_id}</code>.',
            parse_mode='HTML',
        )
        return
    await update.effective_message.reply_text('No blacklist entry matched that Telegram ID.', parse_mode='HTML')


async def vacation_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    seller = await _require_seller(update)
    if seller is None:
        return

    args = list(context.args)
    if not args:
        text, keyboard = await _vacation_screen(seller)
        await _render_dashboard_message(update, text=text, reply_markup=keyboard)
        return

    action = args[0].lower()
    if action == 'off':
        event_key = _command_event_key(update, 'vacation-off')
        if event_key is not None:
            first_seen = await asyncio.to_thread(
                register_processed_event,
                source='seller_command',
                event_key=event_key,
                metadata={'seller_id': str(seller['id']), 'enabled': False},
            )
            if not first_seen:
                return
        await asyncio.to_thread(set_vacation_mode, seller_id=str(seller['id']), enabled=False)
        await update.effective_message.reply_text('Vacation mode is now <code>off</code>.', parse_mode='HTML')
        return

    if action == 'on':
        days = 7
        if len(args) > 1:
            if not args[1].isdigit() or int(args[1]) <= 0:
                await update.effective_message.reply_text('Vacation days must be a positive integer.', parse_mode='HTML')
                return
            days = int(args[1])
        event_key = _command_event_key(update, 'vacation-on')
        if event_key is not None:
            first_seen = await asyncio.to_thread(
                register_processed_event,
                source='seller_command',
                event_key=event_key,
                metadata={'seller_id': str(seller['id']), 'enabled': True, 'days': days},
            )
            if not first_seen:
                return
        updated = await asyncio.to_thread(set_vacation_mode, seller_id=str(seller['id']), enabled=True, days=days)
        await update.effective_message.reply_text(
            f'Vacation mode is now <code>on</code> for <code>{days}</code> day(s).\nUntil: <code>{updated.get("vacation_until")}</code>',
            parse_mode='HTML',
        )
        return

    await update.effective_message.reply_text('Use <code>/vacation on 7</code> or <code>/vacation off</code>.', parse_mode='HTML')


async def seller_dashboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    seller, query = await _require_seller_from_query(update)
    if seller is None or query is None:
        return

    parts = (query.data or '').split(':')
    if len(parts) < 2 or parts[0] != 'seller':
        return

    action = parts[1]
    if action == 'home':
        text, keyboard = await _dashboard_home_screen(seller)
        await _render_dashboard_message(update, text=text, reply_markup=keyboard)
        return

    if action == 'inventory':
        page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        text, keyboard = await _inventory_screen(seller, page=page)
        await _render_dashboard_message(update, text=text, reply_markup=keyboard)
        return

    if action == 'detail' and len(parts) >= 4:
        page = int(parts[2]) if parts[2].isdigit() else 0
        listing_id = parts[3]
        text, keyboard = await _listing_detail_screen(seller, listing_id=listing_id, page=page)
        await _render_dashboard_message(update, text=text, reply_markup=keyboard)
        return

    if action == 'queue' and len(parts) >= 4:
        page = int(parts[2]) if parts[2].isdigit() else 0
        listing_id = parts[3]
        text, keyboard = await _queue_screen(seller, listing_id=listing_id, page=page)
        await _render_dashboard_message(update, text=text, reply_markup=keyboard)
        return

    if action == 'sales':
        text, keyboard = await _sales_screen(seller)
        await _render_dashboard_message(update, text=text, reply_markup=keyboard)
        return

    if action == 'blacklist':
        text, keyboard = await _blacklist_screen(seller)
        await _render_dashboard_message(update, text=text, reply_markup=keyboard)
        return

    if action == 'vacation':
        refreshed_seller = await asyncio.to_thread(get_seller_by_telegram_id, seller['telegram_id'])
        text, keyboard = await _vacation_screen(refreshed_seller or seller)
        await _render_dashboard_message(update, text=text, reply_markup=keyboard)
        return

    if action == 'vac_on' and len(parts) >= 3 and parts[2].isdigit():
        event_key = _callback_event_key(query.id, 'vacation-on-callback')
        first_seen = await asyncio.to_thread(
            register_processed_event,
            source='seller_callback',
            event_key=event_key,
            metadata={'seller_id': str(seller['id']), 'enabled': True, 'days': int(parts[2])},
        )
        if not first_seen:
            return
        refreshed_seller = await asyncio.to_thread(set_vacation_mode, seller_id=str(seller['id']), enabled=True, days=int(parts[2]))
        text, keyboard = await _vacation_screen(refreshed_seller)
        await _render_dashboard_message(update, text=text, reply_markup=keyboard)
        return

    if action == 'vac_off':
        event_key = _callback_event_key(query.id, 'vacation-off-callback')
        first_seen = await asyncio.to_thread(
            register_processed_event,
            source='seller_callback',
            event_key=event_key,
            metadata={'seller_id': str(seller['id']), 'enabled': False},
        )
        if not first_seen:
            return
        refreshed_seller = await asyncio.to_thread(set_vacation_mode, seller_id=str(seller['id']), enabled=False)
        text, keyboard = await _vacation_screen(refreshed_seller)
        await _render_dashboard_message(update, text=text, reply_markup=keyboard)
        return

    if action == 'paid_confirm' and len(parts) >= 4:
        page = int(parts[2]) if parts[2].isdigit() else 0
        listing_id = parts[3]
        listing = await asyncio.to_thread(get_listing_by_id, listing_id)
        if listing is None or str(listing.get('seller_id')) != str(seller['id']):
            await _render_dashboard_message(update, text='Listing not found for this seller.', reply_markup=_back_home_keyboard())
            return
        text = (
            '<b>Confirm Mark Paid</b>\n\n'
            f'Item: <code>{html.escape(str(listing.get("card_name") or "Card"))}</code>\n'
            f'Message ID: <code>{listing.get("posted_message_id")}</code>\n\n'
            'Only confirm after you have actually received payment.'
        )
        await _render_dashboard_message(update, text=text, reply_markup=_confirm_paid_keyboard(page=page, listing_id=listing_id))
        return

    if action == 'paid_exec' and len(parts) >= 4:
        event_key = _callback_event_key(query.id, 'paid-exec-callback')
        first_seen = await asyncio.to_thread(
            register_processed_event,
            source='seller_callback',
            event_key=event_key,
            metadata={'seller_id': str(seller['id']), 'listing_id': parts[3]},
        )
        if not first_seen:
            return
        page = int(parts[2]) if parts[2].isdigit() else 0
        listing_id = parts[3]
        listing = await asyncio.to_thread(get_listing_by_id, listing_id)
        if listing is None or str(listing.get('seller_id')) != str(seller['id']):
            await _render_dashboard_message(update, text='Listing not found for this seller.', reply_markup=_back_home_keyboard())
            return
        try:
            result = await complete_sale_for_listing(context=context, seller=seller, listing=listing)
        except ValueError as exc:
            await _render_dashboard_message(update, text=str(exc), reply_markup=_detail_keyboard(page=page, listing_id=listing_id, status=str(listing.get('status') or ''), has_claims=True))
            return
        except Exception:
            await _render_dashboard_message(update, text='I could not mark this listing as sold just now. Please try again.', reply_markup=_detail_keyboard(page=page, listing_id=listing_id, status=str(listing.get('status') or ''), has_claims=True))
            return

        action_result = str(result.get('action') or 'completed')
        latest_listing = result.get('listing') or listing
        paid_claim = result.get('paid_claim') or {}
        transaction = result.get('transaction') or {}
        if action_result == 'already_completed':
            text = 'This listing was already completed earlier.'
        else:
            text = (
                '✅ <b>Marked as sold.</b>\n\n'
                f'Item: <code>{html.escape(str(latest_listing.get("card_name") or "Card"))}</code>\n'
                f'Transaction ID: <code>{transaction.get("id")}</code>\n'
                f'Buyer: <code>{html.escape(str(paid_claim.get("buyer_display_name") or paid_claim.get("buyer_telegram_id")))}</code>'
            )
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton('Inventory', callback_data=f'seller:inventory:{page}')],
                [InlineKeyboardButton('Home', callback_data='seller:home')],
            ]
        )
        await _render_dashboard_message(update, text=text, reply_markup=keyboard)
        return



def register_seller_tool_handlers(application: Application) -> None:
    """Register seller utility command handlers on the Telegram application."""

    application.add_handler(CommandHandler('stats', stats_command))
    application.add_handler(CommandHandler('inventory', inventory_command))
    application.add_handler(CommandHandler('sales', sales_command))
    application.add_handler(CommandHandler('blacklist', blacklist_command))
    application.add_handler(CommandHandler('vacation', vacation_command))
    application.add_handler(CallbackQueryHandler(seller_dashboard_callback, pattern=r'^seller:'))
