"""Claim and auction-comment handler registrations for TCG Listing Bot."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import re
import string
from typing import Any

from telegram import Message, Update
from telegram.error import Forbidden
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from config import get_config
from db.blacklist import get_blacklist_entry
from db.claims import claim_listing_atomic, get_open_claim_for_buyer, mark_payment_prompt_sent, record_auction_bid_atomic
from db.idempotency import register_processed_event
from db.listings import get_listing_by_posted_message
from db.seller_configs import get_seller_config_by_seller_id
from db.sellers import get_seller_by_id
from services.listing_message_editor import edit_listing_messages
from services.payment_requests import (
    build_buyer_payment_message,
    build_seller_claim_notice,
    ensure_payment_request_for_claim,
)
from utils.auction_settings import resolve_listing_payment_deadline_hours
from utils.formatters import format_auction_listing

logger = logging.getLogger(__name__)

_DEFAULT_CLAIM_KEYWORDS = ('claim', 'sold', 'mine')
_WHITESPACE_RE = re.compile(r'\s+')
_BID_RE = re.compile(r'^\s*(?:bid|offer)?\s*[$sSgGdD]*\s*(\d+(?:\.\d{1,2})?)\s*(?:sgd)?\s*$', re.IGNORECASE)



def _requires_start_dm(exc: Exception) -> bool:
    if isinstance(exc, Forbidden):
        return True
    lowered = str(exc).lower()
    return ("bot can\'t initiate conversation" in lowered or "forbidden" in lowered or "user is deactivated" in lowered)


async def _reply_start_bot_notice(*, message: Message, claim_status: str) -> None:
    bot_username = get_config().telegram_bot_username
    status_text = 'claim details' if claim_status == 'confirmed' else 'queue updates'
    await message.reply_text(
        (
            '⚠️ I recorded this action, but I could not DM you yet.\n\n'
            f'Please open <code>{bot_username}</code> and press <b>Start</b> first so I can send you {status_text}.'
        ),
        parse_mode='HTML',
    )

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



def _parse_bid_amount(text: str) -> float | None:
    match = _BID_RE.fullmatch(text.strip())
    if match is None:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    if value <= 0:
        return None
    return value



def _claim_message_event_key(message: Message) -> str:
    chat_id = getattr(getattr(message, 'chat', None), 'id', 'unknown')
    return f'claim-comment:{chat_id}:{message.message_id}'



def _auction_message_event_key(message: Message) -> str:
    chat_id = getattr(getattr(message, 'chat', None), 'id', 'unknown')
    return f'auction-comment:{chat_id}:{message.message_id}'



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



def _seller_is_on_vacation(seller: dict[str, Any] | None) -> bool:
    if not seller or not seller.get('vacation_mode'):
        return False
    vacation_until = seller.get('vacation_until')
    if not vacation_until:
        return True
    try:
        normalized = str(vacation_until).replace('Z', '+00:00')
        return datetime.fromisoformat(normalized) > datetime.now(timezone.utc)
    except ValueError:
        return True



def _non_claimable_message(listing_status: str | None) -> str:
    if listing_status == 'sold':
        return 'This listing is already sold.'
    if listing_status == 'auction_closed':
        return 'This auction has already ended.'
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
    return '⏳ Your claim has been queued for this listing. ' f'Current queue position: <code>{queue_position}</code>.'



async def claims_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message is None:
        return
    await update.effective_message.reply_text(
        'Claim monitoring is live for replies/comments on bot-posted listings. Auction bids are also monitored on bot-posted auction listings.',
        parse_mode='HTML',
    )


async def _resolve_listing_from_reply(reply: Message) -> tuple[dict[str, Any] | None, str]:
    listing = None
    resolved_via = 'unresolved'
    resolution_attempts = _candidate_listing_keys(reply)
    for channel_id, message_id, reason in resolution_attempts:
        candidate = await asyncio.to_thread(
            get_listing_by_posted_message,
            posted_message_id=message_id,
            posted_channel_id=channel_id,
        )
        if candidate is not None:
            listing = candidate
            resolved_via = reason
            break
    return listing, resolved_via


async def _handle_auction_bid_comment(
    *,
    message: Message,
    user,
    context: ContextTypes.DEFAULT_TYPE,
    listing: dict[str, Any],
    seller: dict[str, Any] | None,
    seller_config: dict[str, Any] | None,
    resolved_via: str,
) -> None:
    bid_amount = _parse_bid_amount(message.text or '')
    if bid_amount is None:
        return

    auction_event_key = _auction_message_event_key(message)
    if _seller_is_on_vacation(seller):
        first_seen = await asyncio.to_thread(
            register_processed_event,
            source='auction_bid_comment',
            event_key=auction_event_key,
            metadata={'listing_id': str(listing['id']), 'reason': 'seller_vacation'},
        )
        if not first_seen:
            return
        await message.reply_text(
            'This seller is currently on vacation, so new bids are temporarily disabled for this auction.',
            parse_mode='HTML',
        )
        return

    blacklist_entry = await asyncio.to_thread(
        get_blacklist_entry,
        seller_id=str(listing['seller_id']),
        blocked_telegram_id=user.id,
    )
    if blacklist_entry is not None:
        first_seen = await asyncio.to_thread(
            register_processed_event,
            source='auction_bid_comment',
            event_key=auction_event_key,
            metadata={'listing_id': str(listing['id']), 'reason': 'blacklisted'},
        )
        if not first_seen:
            return
        await message.reply_text('Your bid was not accepted automatically for this auction.', parse_mode='HTML')
        return

    try:
        result = await record_auction_bid_atomic(
            listing_id=str(listing['id']),
            buyer_telegram_id=user.id,
            buyer_username=user.username,
            buyer_display_name=user.full_name,
            bid_amount_sgd=bid_amount,
        )
    except Exception as exc:
        logger.exception('Auction bid RPC failed for listing %s by %s: %s', listing.get('id'), user.id, exc)
        first_seen = await asyncio.to_thread(
            register_processed_event,
            source='auction_bid_comment',
            event_key=auction_event_key,
            metadata={'listing_id': str(listing['id']), 'reason': 'bid_rpc_failed'},
        )
        if not first_seen:
            return
        await message.reply_text('I could not record that bid just now. Please try again.', parse_mode='HTML')
        return

    action = str(result.get('action') or 'rejected')
    latest_listing = result.get('listing') or listing
    if action != 'accepted':
        reason = str(result.get('reason') or 'rejected')
        first_seen = await asyncio.to_thread(
            register_processed_event,
            source='auction_bid_comment',
            event_key=auction_event_key,
            metadata={'listing_id': str(listing['id']), 'reason': reason},
        )
        if not first_seen:
            return
        if reason == 'bid_too_low':
            minimum_bid = float(result.get('minimum_bid') or 0)
            await message.reply_text(
                f'Your bid is too low. The next valid bid is <code>SGD {minimum_bid:.2f}</code> or higher.',
                parse_mode='HTML',
            )
            return
        await message.reply_text(_non_claimable_message(str(latest_listing.get('status') or 'auction_closed')), parse_mode='HTML')
        return

    winning_bid_claim = result.get('winning_bid_claim') or {}
    previous_high_claim = result.get('previous_high_claim') or None
    anti_snipe_applied = bool(result.get('anti_snipe_applied'))
    first_seen = await asyncio.to_thread(
        register_processed_event,
        source='auction_bid_comment',
        event_key=auction_event_key,
        metadata={
            'listing_id': str(listing['id']),
            'claim_id': str(winning_bid_claim.get('id')),
            'bid_amount_sgd': bid_amount,
            'anti_snipe_applied': anti_snipe_applied,
        },
    )
    if not first_seen:
        return

    text = format_auction_listing(
        card_name=str(latest_listing.get('card_name') or 'Card'),
        game=str(latest_listing.get('game') or 'pokemon'),
        starting_bid_sgd=float(latest_listing.get('starting_bid_sgd') or 0),
        current_bid_sgd=float(latest_listing.get('current_bid_sgd') or bid_amount),
        bid_increment_sgd=(
            float(latest_listing.get('bid_increment_sgd')) if latest_listing.get('bid_increment_sgd') is not None else None
        ),
        anti_snipe_minutes=(
            int(latest_listing.get('anti_snipe_minutes')) if latest_listing.get('anti_snipe_minutes') is not None else None
        ),
        reserve_price_sgd=(
            float(latest_listing.get('reserve_price_sgd')) if latest_listing.get('reserve_price_sgd') is not None else None
        ),
        payment_deadline_hours=resolve_listing_payment_deadline_hours(
            listing=latest_listing,
            seller_config=seller_config,
            default_hours=get_config().default_payment_deadline_hours,
        ),
        condition_notes=str(latest_listing.get('condition_notes') or ''),
        custom_description=str(latest_listing.get('custom_description') or ''),
        seller_display_name=(seller_config or {}).get('seller_display_name') or 'Seller',
        auction_end_time=latest_listing.get('auction_end_time'),
        status='auction_active',
    )
    await edit_listing_messages(application=context.application, listing=latest_listing, text=text)

    public_message = f'🔨 New high bid: <b>SGD {bid_amount:.2f}</b> by <b>{user.full_name}</b>.'
    if anti_snipe_applied:
        public_message += ' Anti-snipe extended the auction timer.'
    await message.reply_text(public_message, parse_mode='HTML')

    if previous_high_claim and previous_high_claim.get('buyer_telegram_id') and int(previous_high_claim['buyer_telegram_id']) != user.id:
        try:
            await context.bot.send_message(
                chat_id=int(previous_high_claim['buyer_telegram_id']),
                text=(
                    '<b>You have been outbid.</b>\n\n'
                    f'Item: <code>{latest_listing.get("card_name")}</code>\n'
                    f'Current bid: <code>SGD {float(latest_listing.get("current_bid_sgd") or bid_amount):.2f}</code>'
                ),
                parse_mode='HTML',
            )
        except Exception as exc:
            logger.info('Could not DM outbid buyer %s: %s', previous_high_claim.get('buyer_telegram_id'), exc)

    if seller is not None:
        try:
            seller_message = (
                '<b>New auction bid received.</b>\n\n'
                f'Item: <code>{latest_listing.get("card_name")}</code>\n'
                f'Bidder: <code>{user.full_name}</code>\n'
                f'Bid: <code>SGD {bid_amount:.2f}</code>'
            )
            if anti_snipe_applied:
                seller_message += '\nAnti-snipe extended the auction timer.'
            await context.bot.send_message(
                chat_id=int(seller['telegram_id']),
                text=seller_message,
                parse_mode='HTML',
            )
        except Exception as exc:
            logger.info('Could not DM seller %s after auction bid: %s', seller.get('telegram_id'), exc)

    logger.info(
        'Auction bid accepted for listing %s by buyer %s amount=%s resolved_via=%s.',
        listing.get('id'),
        user.id,
        bid_amount,
        resolved_via,
    )


async def _handle_fixed_claim_comment(
    *,
    message: Message,
    user,
    context: ContextTypes.DEFAULT_TYPE,
    listing: dict[str, Any],
    seller: dict[str, Any] | None,
    seller_config: dict[str, Any] | None,
    resolved_via: str,
) -> None:
    claim_keywords = _effective_claim_keywords(seller_config)
    if not _is_claim_text(message.text or '', claim_keywords):
        logger.debug(
            'Ignoring non-claim reply for listing %s. text=%r keywords=%s',
            listing.get('id'),
            message.text,
            claim_keywords,
        )
        return

    claim_event_key = _claim_message_event_key(message)
    if _seller_is_on_vacation(seller):
        first_seen = await asyncio.to_thread(
            register_processed_event,
            source='claim_comment',
            event_key=claim_event_key,
            metadata={'listing_id': str(listing['id']), 'reason': 'seller_vacation'},
        )
        if not first_seen:
            logger.info('Skipping duplicate claim event %s during seller vacation.', claim_event_key)
            return
        await message.reply_text(
            'This seller is currently on vacation, so new claims are temporarily disabled for this listing.',
            parse_mode='HTML',
        )
        return

    blacklist_entry = await asyncio.to_thread(
        get_blacklist_entry,
        seller_id=str(listing['seller_id']),
        blocked_telegram_id=user.id,
    )
    if blacklist_entry is not None:
        first_seen = await asyncio.to_thread(
            register_processed_event,
            source='claim_comment',
            event_key=claim_event_key,
            metadata={'listing_id': str(listing['id']), 'reason': 'blacklisted'},
        )
        if not first_seen:
            logger.info('Skipping duplicate blacklisted claim event %s.', claim_event_key)
            return
        await message.reply_text('Your claim was not accepted automatically for this listing.', parse_mode='HTML')
        return

    listing_status = str(listing.get('status') or '')
    if listing_status not in {'active', 'claim_pending'}:
        first_seen = await asyncio.to_thread(
            register_processed_event,
            source='claim_comment',
            event_key=claim_event_key,
            metadata={'listing_id': str(listing['id']), 'reason': 'not_claimable', 'listing_status': listing_status},
        )
        if not first_seen:
            logger.info('Skipping duplicate non-claimable event %s.', claim_event_key)
            return
        await message.reply_text(_non_claimable_message(listing_status), parse_mode='HTML')
        return

    existing_claim = await asyncio.to_thread(
        get_open_claim_for_buyer,
        listing_id=str(listing['id']),
        buyer_telegram_id=user.id,
    )
    if existing_claim is not None:
        first_seen = await asyncio.to_thread(
            register_processed_event,
            source='claim_comment',
            event_key=claim_event_key,
            metadata={'listing_id': str(listing['id']), 'reason': 'existing_claim', 'claim_id': str(existing_claim.get('id'))},
        )
        if not first_seen:
            logger.info('Skipping duplicate existing-claim event %s.', claim_event_key)
            return
        await message.reply_text(_existing_claim_message(existing_claim), parse_mode='HTML')
        return

    config = get_config()
    deadline_hours = resolve_listing_payment_deadline_hours(
        listing=listing,
        seller_config=seller_config,
        default_hours=config.default_payment_deadline_hours,
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
        first_seen = await asyncio.to_thread(
            register_processed_event,
            source='claim_comment',
            event_key=claim_event_key,
            metadata={'listing_id': str(listing['id']), 'reason': 'claim_rpc_failed', 'listing_status': refreshed_status},
        )
        if not first_seen:
            logger.info('Skipping duplicate failed-claim event %s.', claim_event_key)
            return
        await message.reply_text(_non_claimable_message(refreshed_status), parse_mode='HTML')
        return

    claim_status = str(claim.get('status') or '')
    queue_position = int(claim.get('queue_position') or 1)

    if claim_status == 'queued':
        first_seen = await asyncio.to_thread(
            register_processed_event,
            source='claim_comment',
            event_key=claim_event_key,
            metadata={'listing_id': str(listing['id']), 'claim_id': str(claim.get('id')), 'claim_status': 'queued'},
        )
        if not first_seen:
            logger.info('Skipping duplicate queued claim event %s.', claim_event_key)
            return
        await message.reply_text(_queued_claim_public_message(queue_position), parse_mode='HTML')
        try:
            await context.bot.send_message(
                chat_id=user.id,
                text=(
                    '<b>Your claim is queued.</b>\n\n'
                    f'Item: <code>{listing.get("card_name")}</code>\n'
                    f'Queue position: <code>{queue_position}</code>\n\n'
                    'If you no longer want this queue spot, run <code>/unclaim</code> in the bot chat.'
                ),
                parse_mode='HTML',
            )
        except Exception as exc:
            logger.info('Could not DM queued buyer %s: %s', user.id, exc)
            if _requires_start_dm(exc):
                await _reply_start_bot_notice(message=message, claim_status='queued')
        if seller is not None:
            try:
                await context.bot.send_message(
                    chat_id=int(seller['telegram_id']),
                    text=build_seller_claim_notice(
                        listing=listing,
                        claim=None,
                        buyer_display_name=user.full_name,
                        buyer_username=user.username,
                        deadline_hours=deadline_hours,
                        queue_position=queue_position,
                    ),
                    parse_mode='HTML',
                )
            except Exception as exc:
                logger.info('Could not DM seller %s after queued claim: %s', seller.get('telegram_id'), exc)
        return

    first_seen = await asyncio.to_thread(
        register_processed_event,
        source='claim_comment',
        event_key=claim_event_key,
        metadata={'listing_id': str(listing['id']), 'claim_id': str(claim.get('id')), 'claim_status': claim_status or 'confirmed'},
    )
    if not first_seen:
        logger.info('Skipping duplicate confirmed claim event %s.', claim_event_key)
        return

    await message.reply_text(
        f'✅ Claim recorded for <b>{user.full_name}</b>. Payment window: <code>{deadline_hours}h</code>.',
        parse_mode='HTML',
    )

    claim = await asyncio.to_thread(ensure_payment_request_for_claim, claim=claim)
    dm_text = build_buyer_payment_message(
        listing=listing,
        claim=claim,
        seller_config=seller_config,
        deadline_hours=deadline_hours,
        intro='You successfully claimed a listing.',
    )
    try:
        dm_message = await context.bot.send_message(chat_id=user.id, text=dm_text, parse_mode='HTML')
        await asyncio.to_thread(mark_payment_prompt_sent, claim_id=str(claim['id']), message_id=dm_message.message_id)
    except Exception as exc:
        logger.info('Could not DM buyer %s after claim: %s', user.id, exc)
        if _requires_start_dm(exc):
            await _reply_start_bot_notice(message=message, claim_status='confirmed')

    if seller is not None:
        try:
            await context.bot.send_message(
                chat_id=int(seller['telegram_id']),
                text=build_seller_claim_notice(
                    listing=listing,
                    claim=claim,
                    buyer_display_name=user.full_name,
                    buyer_username=user.username,
                    deadline_hours=deadline_hours,
                ),
                parse_mode='HTML',
            )
        except Exception as exc:
            logger.info('Could not DM seller %s after claim: %s', seller.get('telegram_id'), exc)


async def handle_claim_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or message.text is None:
        return

    reply = message.reply_to_message
    if reply is None:
        return

    listing, resolved_via = await _resolve_listing_from_reply(reply)
    if listing is None:
        logger.debug(
            'Could not resolve listing for reply comment chat=%s message=%s candidates=%s payload=%s',
            getattr(getattr(message, 'chat', None), 'id', None),
            message.message_id,
            _candidate_listing_keys(reply),
            {
                key: value
                for key, value in (reply.to_dict() or {}).items()
                if key in {'message_id', 'is_automatic_forward', 'sender_chat', 'forward_origin', 'external_reply'}
            },
        )
        return

    seller_config = await asyncio.to_thread(get_seller_config_by_seller_id, str(listing['seller_id']))
    seller = await asyncio.to_thread(get_seller_by_id, str(listing['seller_id']))
    listing_type = str(listing.get('listing_type') or 'fixed')

    if listing_type == 'auction':
        await _handle_auction_bid_comment(
            message=message,
            user=user,
            context=context,
            listing=listing,
            seller=seller,
            seller_config=seller_config,
            resolved_via=resolved_via,
        )
        return

    await _handle_fixed_claim_comment(
        message=message,
        user=user,
        context=context,
        listing=listing,
        seller=seller,
        seller_config=seller_config,
        resolved_via=resolved_via,
    )



def register_claim_handlers(application: Application) -> None:
    application.add_handler(CommandHandler('claims', claims_placeholder))
    application.add_handler(
        MessageHandler(
            (filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP) & filters.TEXT & ~filters.COMMAND,
            handle_claim_comment,
        )
    )
