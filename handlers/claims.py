"""Claim handler registrations for TCG Listing Bot."""

from __future__ import annotations

import asyncio
import logging
import string
from typing import Any

from telegram import Message, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from config import get_config
from db.claims import claim_listing_atomic
from db.listings import get_listing_by_posted_message
from db.seller_configs import get_seller_config_by_seller_id
from db.sellers import get_seller_by_id

logger = logging.getLogger(__name__)

_CLAIM_KEYWORDS = {'claim', 'sold', 'mine'}


def _is_claim_text(text: str) -> bool:
    normalized = text.strip().lower()
    if not normalized:
        return False
    first_token = normalized.split()[0].strip(string.punctuation)
    return first_token in _CLAIM_KEYWORDS


def _candidate_listing_keys(reply: Message) -> list[tuple[int | None, int, str]]:
    candidates: list[tuple[int | None, int, str]] = []
    if reply.message_id:
        candidates.append((None, reply.message_id, 'reply_message_id'))

    sender_chat = getattr(reply, 'sender_chat', None)
    if sender_chat is not None and getattr(sender_chat, 'id', None) and reply.message_id:
        candidates.append((int(sender_chat.id), int(reply.message_id), 'sender_chat+reply_message_id'))

    forward_origin = getattr(reply, 'forward_origin', None)
    origin_chat_id = getattr(getattr(forward_origin, 'chat', None), 'id', None)
    origin_message_id = getattr(forward_origin, 'message_id', None)
    if origin_message_id is not None:
        candidates.append((int(origin_chat_id) if origin_chat_id is not None else None, int(origin_message_id), 'forward_origin'))

    external_reply = getattr(reply, 'external_reply', None)
    external_origin = getattr(external_reply, 'origin', None)
    external_chat_id = getattr(getattr(external_origin, 'chat', None), 'id', None)
    external_message_id = getattr(external_origin, 'message_id', None)
    if external_message_id is not None:
        candidates.append((int(external_chat_id) if external_chat_id is not None else None, int(external_message_id), 'external_reply_origin'))

    deduped: list[tuple[int | None, int, str]] = []
    seen: set[tuple[int | None, int]] = set()
    for channel_id, message_id, reason in candidates:
        key = (channel_id, message_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((channel_id, message_id, reason))
    return deduped


async def claims_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    await update.effective_message.reply_text(
        'Claim monitoring is now live for replies/comments on bot-posted listings. Use <code>Claim</code> in the linked discussion thread.',
        parse_mode='HTML',
    )


async def handle_claim_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or message.text is None:
        return
    if not _is_claim_text(message.text):
        return

    reply = message.reply_to_message
    if reply is None:
        return

    listing = None
    resolution_attempts = _candidate_listing_keys(reply)
    for posted_channel_id, posted_message_id, reason in resolution_attempts:
        listing = await asyncio.to_thread(
            get_listing_by_posted_message,
            posted_message_id=posted_message_id,
            posted_channel_id=posted_channel_id,
        )
        if listing is not None:
            logger.info(
                'Resolved claim reply to listing %s via %s channel_id=%s message_id=%s discussion_chat=%s discussion_message=%s',
                listing.get('id'),
                reason,
                posted_channel_id,
                posted_message_id,
                getattr(message.chat, 'id', None),
                message.message_id,
            )
            break

    if listing is None:
        logger.info(
            'Could not resolve claim reply to a bot-posted listing. attempts=%s reply_payload=%s',
            resolution_attempts,
            {key: value for key, value in (reply.to_dict() or {}).items() if key in {'message_id', 'is_automatic_forward', 'sender_chat', 'forward_origin', 'external_reply'}},
        )
        return

    if str(listing.get('status')) != 'active':
        await message.reply_text('This listing is no longer claimable.', parse_mode='HTML')
        return

    try:
        claim = await claim_listing_atomic(
            listing_id=str(listing['id']),
            buyer_telegram_id=user.id,
            buyer_username=user.username,
            buyer_display_name=user.full_name,
            payment_deadline_hours=get_config().default_payment_deadline_hours,
        )
    except Exception as exc:
        logger.info('Claim attempt failed for listing %s by %s: %s', listing.get('id'), user.id, exc)
        await message.reply_text('Claim not accepted. The listing may already be claimed.', parse_mode='HTML')
        return

    await message.reply_text(
        f'✅ Claim recorded for <b>{user.full_name}</b>. Payment window: <code>{get_config().default_payment_deadline_hours}h</code>.',
        parse_mode='HTML',
    )

    seller = await asyncio.to_thread(get_seller_by_id, str(listing['seller_id']))
    seller_config = await asyncio.to_thread(get_seller_config_by_seller_id, str(listing['seller_id']))
    paynow_identifier = seller_config.get('paynow_identifier') if seller_config else ''
    payment_methods = ', '.join(seller_config.get('payment_methods') or ['PayNow']) if seller_config else 'PayNow'

    dm_text = (
        '<b>You successfully claimed a listing.</b>\n\n'
        f'Item: <code>{listing.get("card_name")}</code>\n'
        f'Price: <code>SGD {float(listing.get("price_sgd") or 0):.2f}</code>\n'
        f'Payment methods: <code>{payment_methods}</code>\n'
        + (f'PayNow: <code>{paynow_identifier}</code>\n' if paynow_identifier else '')
        + f'Deadline: <code>{get_config().default_payment_deadline_hours}h</code>'
    )
    try:
        await context.bot.send_message(chat_id=user.id, text=dm_text, parse_mode='HTML')
    except Exception as exc:
        logger.info('Could not DM buyer %s after claim: %s', user.id, exc)

    if seller is not None:
        seller_notice = (
            '<b>New claim received.</b>\n\n'
            f'Item: <code>{listing.get("card_name")}</code>\n'
            f'Buyer: <code>{user.full_name}</code>\n'
            f'Username: <code>@{user.username}</code>\n' if user.username else f'Buyer: <code>{user.full_name}</code>\n'
        )
        try:
            await context.bot.send_message(chat_id=int(seller['telegram_id']), text=seller_notice, parse_mode='HTML')
        except Exception as exc:
            logger.info('Could not DM seller %s after claim: %s', seller.get('telegram_id'), exc)

    logger.info('Claim %s confirmed for listing %s by buyer %s.', claim.get('id'), listing.get('id'), user.id)


def register_claim_handlers(application: Application) -> None:
    application.add_handler(CommandHandler('claims', claims_placeholder))
    application.add_handler(
        MessageHandler(
            (filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP) & filters.TEXT & ~filters.COMMAND,
            handle_claim_comment,
        )
    )
