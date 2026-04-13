"""Claim handler registrations for TCG Listing Bot."""

from __future__ import annotations

import asyncio
import logging
import re
import string
from typing import Any

from telegram import Message, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from config import get_config
from db.blacklist import get_blacklist_entry
from db.claims import claim_listing_atomic, get_open_claim_for_buyer
from db.listings import get_listing_by_posted_message
from db.seller_configs import get_seller_config_by_seller_id
from db.sellers import get_seller_by_id

logger = logging.getLogger(__name__)

_DEFAULT_CLAIM_KEYWORDS = ('claim', 'sold', 'mine')
_WHITESPACE_RE = re.compile(r'\s+')



def _normalize_claim_keyword(value: str) -> str:
    normalized = _WHITESPACE_RE.sub(' ', value.strip().lower())
    return normalized.strip(string.punctuation + ' ')



def _effective_claim_keywords(seller_config: dict[str, Any] | None) -> list[str]:
    raw_keywords = seller_config.get('claim_keywords') if seller_config else None
    if isinstance(raw_keywords, list):
        normalized = []
        for keyword in raw_keywords:
            normalized_keyword = _normalize_claim_keyword(str(keyword))
            if normalized_keyword and normalized_keyword not in normalized:
                normalized.append(normalized_keyword)
        if normalized:
            return normalized
    return list(_DEFAULT_CLAIM_KEYWORDS)



def _is_claim_text(text: str, claim_keywords: list[str]) -> bool:
    normalized_text = _normalize_claim_keyword(text)
    if not normalized_text:
        return False

    first_token = normalized_text.split()[0]
    single_token_keywords = {keyword for keyword in claim_keywords if ' ' not in keyword}
    phrase_keywords = {keyword for keyword in claim_keywords if ' ' in keyword}
    return (
        normalized_text in single_token_keywords
        or first_token in single_token_keywords
        or normalized_text in phrase_keywords
    )



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



def _non_claimable_message(listing_status: str | None) -> str:
    if listing_status == 'sold':
        return 'This listing is already sold.'
    return 'This listing is no longer claimable.'



def _existing_claim_message(existing_claim: dict[str, Any]) -> str:
    status = str(existing_claim.get('status') or '')
    queue_position = int(existing_claim.get('queue_position') or 1)
    if status in {'confirmed', 'payment_pending'}:
        return 'You already hold the active claim for this listing.'
    if status == 'queued':
        return f'You are already queued for this listing at position <code>{queue_position}</code>.'
    return 'You already have a claim recorded for this listing.'



def _queued_claim_public_message(queue_position: int) -> str:
    return (
        '⏳ Your claim has been queued for this listing. '
        f'Current queue position: <code>{queue_position}</code>.'
    )



def _build_seller_claim_notice(
    *,
    listing: dict[str, Any],
    buyer_display_name: str,
    buyer_username: str | None,
    deadline_hours: int,
    queue_position: int | None = None,
) -> str:
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
        lines.append(f'Payment deadline: <code>{deadline_hours}h</code>')
    return '\n'.join(lines)


async def claims_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    await update.effective_message.reply_text(
        'Claim monitoring is live for replies/comments on bot-posted listings. Sellers can configure accepted claim keywords in their seller config.',
        parse_mode='HTML',
    )


async def handle_claim_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or message.text is None:
        return

    reply = message.reply_to_message
    if reply is None:
        return

    listing = None
    resolved_via = 'unresolved'
    resolution_attempts = _candidate_listing_keys(reply)
    for posted_channel_id, posted_message_id, reason in resolution_attempts:
        listing = await asyncio.to_thread(
            get_listing_by_posted_message,
            posted_message_id=posted_message_id,
            posted_channel_id=posted_channel_id,
        )
        if listing is not None:
            resolved_via = reason
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
            {
                key: value
                for key, value in (reply.to_dict() or {}).items()
                if key in {'message_id', 'is_automatic_forward', 'sender_chat', 'forward_origin', 'external_reply'}
            },
        )
        return

    seller_config = await asyncio.to_thread(get_seller_config_by_seller_id, str(listing['seller_id']))
    claim_keywords = _effective_claim_keywords(seller_config)
    if not _is_claim_text(message.text, claim_keywords):
        logger.debug(
            'Ignoring non-claim reply for listing %s. text=%r keywords=%s',
            listing.get('id'),
            message.text,
            claim_keywords,
        )
        return

    blacklist_entry = await asyncio.to_thread(
        get_blacklist_entry,
        seller_id=str(listing['seller_id']),
        blocked_telegram_id=user.id,
    )
    if blacklist_entry is not None:
        logger.info(
            'Rejected blacklisted buyer claim. listing_id=%s seller_id=%s buyer_id=%s reason=%s resolved_via=%s',
            listing.get('id'),
            listing.get('seller_id'),
            user.id,
            blacklist_entry.get('reason'),
            resolved_via,
        )
        await message.reply_text(
            'Your claim was not accepted automatically for this listing.',
            parse_mode='HTML',
        )
        seller = await asyncio.to_thread(get_seller_by_id, str(listing['seller_id']))
        if seller is not None:
            seller_notice = (
                '<b>Blocked claim attempt detected.</b>\n\n'
                f'Item: <code>{listing.get("card_name")}</code>\n'
                f'Buyer: <code>{user.full_name}</code>\n'
                f'Reason: <code>{blacklist_entry.get("reason") or "blacklisted buyer"}</code>'
            )
            try:
                await context.bot.send_message(
                    chat_id=int(seller['telegram_id']),
                    text=seller_notice,
                    parse_mode='HTML',
                )
            except Exception as exc:
                logger.info('Could not DM seller %s about blocked claim: %s', seller.get('telegram_id'), exc)
        return

    listing_status = str(listing.get('status') or '')
    if listing_status not in {'active', 'claim_pending'}:
        await message.reply_text(_non_claimable_message(listing_status), parse_mode='HTML')
        return

    existing_claim = await asyncio.to_thread(
        get_open_claim_for_buyer,
        listing_id=str(listing['id']),
        buyer_telegram_id=user.id,
    )
    if existing_claim is not None:
        await message.reply_text(_existing_claim_message(existing_claim), parse_mode='HTML')
        return

    config = get_config()
    deadline_hours = int(
        (seller_config or {}).get('payment_deadline_hours') or config.default_payment_deadline_hours
    )

    try:
        claim = await claim_listing_atomic(
            listing_id=str(listing['id']),
            buyer_telegram_id=user.id,
            buyer_username=user.username,
            buyer_display_name=user.full_name,
            payment_deadline_hours=deadline_hours,
        )
    except Exception as exc:
        logger.info(
            'Claim attempt failed for listing %s by %s. resolved_via=%s error=%s',
            listing.get('id'),
            user.id,
            resolved_via,
            exc,
        )
        refreshed_listing = await asyncio.to_thread(
            get_listing_by_posted_message,
            posted_message_id=int(listing['posted_message_id']),
            posted_channel_id=int(listing['posted_channel_id']) if listing.get('posted_channel_id') is not None else None,
        )
        refreshed_status = str((refreshed_listing or {}).get('status') or '')
        await message.reply_text(_non_claimable_message(refreshed_status), parse_mode='HTML')
        return

    claim_status = str(claim.get('status') or '')
    queue_position = int(claim.get('queue_position') or 1)
    seller = await asyncio.to_thread(get_seller_by_id, str(listing['seller_id']))

    if claim_status == 'queued':
        await message.reply_text(_queued_claim_public_message(queue_position), parse_mode='HTML')
        try:
            await context.bot.send_message(
                chat_id=user.id,
                text=(
                    '<b>Your claim is queued.</b>\n\n'
                    f'Item: <code>{listing.get("card_name")}</code>\n'
                    f'Queue position: <code>{queue_position}</code>'
                ),
                parse_mode='HTML',
            )
        except Exception as exc:
            logger.info('Could not DM queued buyer %s: %s', user.id, exc)
        if seller is not None:
            try:
                await context.bot.send_message(
                    chat_id=int(seller['telegram_id']),
                    text=_build_seller_claim_notice(
                        listing=listing,
                        buyer_display_name=user.full_name,
                        buyer_username=user.username,
                        deadline_hours=deadline_hours,
                        queue_position=queue_position,
                    ),
                    parse_mode='HTML',
                )
            except Exception as exc:
                logger.info('Could not DM seller %s after queued claim: %s', seller.get('telegram_id'), exc)
        logger.info(
            'Claim %s queued for listing %s by buyer %s at position %s using keyword_set=%s resolved_via=%s.',
            claim.get('id'),
            listing.get('id'),
            user.id,
            queue_position,
            claim_keywords,
            resolved_via,
        )
        return

    await message.reply_text(
        f'✅ Claim recorded for <b>{user.full_name}</b>. Payment window: <code>{deadline_hours}h</code>.',
        parse_mode='HTML',
    )

    paynow_identifier = (seller_config or {}).get('paynow_identifier') or ''
    payment_methods = ', '.join((seller_config or {}).get('payment_methods') or ['PayNow'])

    dm_text = (
        '<b>You successfully claimed a listing.</b>\n\n'
        f'Item: <code>{listing.get("card_name")}</code>\n'
        f'Price: <code>SGD {float(listing.get("price_sgd") or 0):.2f}</code>\n'
        f'Payment methods: <code>{payment_methods}</code>\n'
        + (f'PayNow: <code>{paynow_identifier}</code>\n' if paynow_identifier else '')
        + f'Deadline: <code>{deadline_hours}h</code>'
    )
    try:
        await context.bot.send_message(chat_id=user.id, text=dm_text, parse_mode='HTML')
    except Exception as exc:
        logger.info('Could not DM buyer %s after claim: %s', user.id, exc)

    if seller is not None:
        try:
            await context.bot.send_message(
                chat_id=int(seller['telegram_id']),
                text=_build_seller_claim_notice(
                    listing=listing,
                    buyer_display_name=user.full_name,
                    buyer_username=user.username,
                    deadline_hours=deadline_hours,
                ),
                parse_mode='HTML',
            )
        except Exception as exc:
            logger.info('Could not DM seller %s after claim: %s', seller.get('telegram_id'), exc)

    logger.info(
        'Claim %s confirmed for listing %s by buyer %s using keyword_set=%s resolved_via=%s.',
        claim.get('id'),
        listing.get('id'),
        user.id,
        claim_keywords,
        resolved_via,
    )



def register_claim_handlers(application: Application) -> None:
    application.add_handler(CommandHandler('claims', claims_placeholder))
    application.add_handler(
        MessageHandler(
            (filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP) & filters.TEXT & ~filters.COMMAND,
            handle_claim_comment,
        )
    )
