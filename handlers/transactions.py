"""Transaction handler registrations for TCG Listing Bot."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from db.claims import get_current_winning_claim
from db.idempotency import register_processed_event
from db.listings import get_claim_pending_listings_for_seller
from db.seller_configs import get_seller_config_by_seller_id
from db.sellers import get_seller_by_telegram_id
from db.transactions import complete_transaction_atomic
from services.listing_message_editor import edit_listing_messages
from utils.formatters import format_sold_listing

logger = logging.getLogger(__name__)



def _sold_command_event_key(update: Update) -> str | None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or getattr(message, 'chat', None) is None:
        return None
    return f'sold-command:{message.chat.id}:{message.message_id}:{user.id}'


def _looks_like_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except Exception:
        return False



def _resolve_listing_reference(listings: list[dict[str, Any]], reference: str | None) -> dict[str, Any] | None:
    if not listings:
        return None
    if not reference:
        return listings[0] if len(listings) == 1 else None

    normalized = reference.strip()
    if _looks_like_uuid(normalized):
        for listing in listings:
            if str(listing.get('id')) == normalized:
                return listing

    if normalized.isdigit():
        for listing in listings:
            if str(listing.get('posted_message_id')) == normalized:
                return listing

    return None



def _sold_usage_message(listings: list[dict[str, Any]]) -> str:
    if not listings:
        return 'You have no claim-pending listings ready to mark as paid.'
    if len(listings) == 1:
        listing = listings[0]
        return (
            'Use <code>/sold</code> to complete your only claim-pending listing, or pass the channel message ID explicitly.\n\n'
            f'Pending listing: <code>{listing.get("card_name")}</code> — message <code>{listing.get("posted_message_id")}</code>'
        )
    lines = ['Multiple claim-pending listings were found. Use <code>/sold &lt;message_id&gt;</code>.', '']
    for listing in listings[:10]:
        lines.append(
            f'• <code>{listing.get("posted_message_id")}</code> — {listing.get("card_name")}'
        )
    return '\n'.join(lines)


async def _edit_listing_messages_to_sold(
    *,
    application: Application,
    listing: dict[str, Any],
    seller_config: dict[str, Any] | None,
    buyer_display_name: str | None,
) -> None:
    sold_text = format_sold_listing(
        card_name=str(listing.get('card_name') or 'Card'),
        game=str(listing.get('game') or 'pokemon'),
        price_sgd=float(listing.get('price_sgd') or 0),
        condition_notes=str(listing.get('condition_notes') or ''),
        custom_description=str(listing.get('custom_description') or ''),
        seller_display_name=(seller_config or {}).get('seller_display_name') or 'Seller',
        payment_methods=(seller_config or {}).get('payment_methods') or ['PayNow'],
        buyer_display_name=buyer_display_name,
    )
    await edit_listing_messages(application=application, listing=listing, text=sold_text)


async def complete_sale_for_listing(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    seller: dict[str, Any],
    listing: dict[str, Any],
) -> dict[str, Any]:
    """Complete the sale for a seller-owned claim-pending listing."""

    winning_claim = await asyncio.to_thread(get_current_winning_claim, listing_id=str(listing['id']))
    if winning_claim is None:
        raise ValueError('This listing has no active winning claim to complete yet.')

    result = await complete_transaction_atomic(
        listing_id=str(listing['id']),
        seller_id=str(seller['id']),
    )

    paid_claim = result.get('paid_claim') or winning_claim
    latest_listing = result.get('listing') or listing
    seller_config = await asyncio.to_thread(get_seller_config_by_seller_id, str(seller['id']))

    await _edit_listing_messages_to_sold(
        application=context.application,
        listing=latest_listing,
        seller_config=seller_config,
        buyer_display_name=paid_claim.get('buyer_display_name'),
    )

    if str(result.get('action') or '') != 'already_completed':
        buyer_telegram_id = paid_claim.get('buyer_telegram_id')
        if buyer_telegram_id:
            try:
                await context.bot.send_message(
                    chat_id=int(buyer_telegram_id),
                    text=(
                        '<b>Payment received.</b>\n\n'
                        f'Item: <code>{latest_listing.get("card_name")}</code>\n'
                        'The seller has marked this listing as sold.'
                    ),
                    parse_mode='HTML',
                )
            except Exception as exc:
                logger.info('Could not DM buyer %s after sold completion: %s', buyer_telegram_id, exc)

    result['paid_claim'] = paid_claim
    result['listing'] = latest_listing
    return result


async def sold_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Allow the seller to mark payment received and close the listing."""

    if update.effective_message is None or update.effective_user is None:
        return

    seller = await asyncio.to_thread(get_seller_by_telegram_id, update.effective_user.id)
    if seller is None:
        await update.effective_message.reply_text(
            'Seller profile not found. Run <code>/start</code> or <code>/setup</code> first.',
            parse_mode='HTML',
        )
        return

    pending_listings = await asyncio.to_thread(get_claim_pending_listings_for_seller, str(seller['id']))
    reference = ' '.join(context.args).strip() if context.args else None
    listing = _resolve_listing_reference(pending_listings, reference)
    if listing is None:
        await update.effective_message.reply_text(_sold_usage_message(pending_listings), parse_mode='HTML')
        return

    event_key = _sold_command_event_key(update)
    if event_key is not None:
        first_seen = await asyncio.to_thread(
            register_processed_event,
            source='sold_command',
            event_key=event_key,
            metadata={'seller_id': str(seller['id']), 'listing_id': str(listing['id'])},
        )
        if not first_seen:
            logger.info('Skipping duplicate /sold command event %s.', event_key)
            return

    try:
        result = await complete_sale_for_listing(context=context, seller=seller, listing=listing)
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc), parse_mode='HTML')
        return
    except Exception as exc:
        logger.exception('Failed to complete transaction for listing %s: %s', listing.get('id'), exc)
        await update.effective_message.reply_text(
            'I could not mark this listing as sold just now. Please try again.',
            parse_mode='HTML',
        )
        return

    action = str(result.get('action') or 'completed')
    transaction = result.get('transaction') or {}
    paid_claim = result.get('paid_claim') or {}
    latest_listing = result.get('listing') or listing

    if action == 'already_completed':
        await update.effective_message.reply_text(
            'This listing was already completed earlier.',
            parse_mode='HTML',
        )
        return

    await update.effective_message.reply_text(
        (
            '✅ Marked as sold.\n\n'
            f'Item: <code>{latest_listing.get("card_name")}</code>\n'
            f'Transaction ID: <code>{transaction.get("id")}</code>\n'
            f'Buyer: <code>{paid_claim.get("buyer_display_name") or paid_claim.get("buyer_telegram_id")}</code>'
        ),
        parse_mode='HTML',
    )



def register_transaction_handlers(application: Application) -> None:
    """Register transaction-related command handlers on the Telegram application."""

    application.add_handler(CommandHandler('sold', sold_command))
