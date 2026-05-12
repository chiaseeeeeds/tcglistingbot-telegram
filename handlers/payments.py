"""Buyer payment submission and claim-withdrawal handlers."""

from __future__ import annotations

import asyncio
import html
import logging
import re
import tempfile
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from config import get_config
from db.claims import (
    WINNING_CLAIM_STATUSES,
    get_claim_by_id,
    get_claim_by_payment_reference,
    get_open_claim_for_buyer,
    list_open_payment_claims_for_buyer,
    list_withdrawable_claims_for_buyer,
    mark_payment_prompt_sent,
    withdraw_claim_atomic,
)
from db.listings import get_listing_by_id
from db.payment_proofs import (
    create_payment_proof,
    get_payment_proof_by_id,
    set_payment_proof_status_by_id,
    set_submitted_payment_proofs_status_for_claim,
)
from db.seller_configs import get_seller_config_by_seller_id
from db.sellers import get_seller_by_id, get_seller_by_telegram_id
from handlers.claims import _resolve_listing_from_reply
from handlers.transactions import complete_sale_for_listing
from services.image_storage import upload_payment_proof_photo
from services.payment_requests import build_buyer_payment_message, ensure_payment_request_for_claim
from utils.auction_settings import resolve_listing_payment_deadline_hours

logger = logging.getLogger(__name__)
_PAYMENT_REFERENCE_RE = re.compile(r'(TCG-[A-Z0-9]{8})', re.IGNORECASE)
_PAYMENT_SELECTION_KEY = 'selected_payment_claim_id'
_WITHDRAW_SELECTION_KEY = 'selected_withdraw_claim_id'


def _private_only_message() -> str:
    return (
        'For privacy, use this command in a private chat with the bot.\n\n'
        'Open <code>@TCGlistingbot</code> and run it there instead.'
    )


async def _require_private_chat(update: Update) -> bool:
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None:
        return False
    if chat.type == ChatType.PRIVATE:
        return True
    await message.reply_text(_private_only_message(), parse_mode='HTML')
    return False


def _is_private_chat(update: Update) -> bool:
    chat = update.effective_chat
    return chat is not None and chat.type == ChatType.PRIVATE


async def _resolve_public_unclaim_claim(update: Update) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or message.reply_to_message is None:
        return None, None

    listing, _ = await _resolve_listing_from_reply(message.reply_to_message)
    if listing is None:
        return None, None

    claim = await asyncio.to_thread(
        get_open_claim_for_buyer,
        listing_id=str(listing['id']),
        buyer_telegram_id=user.id,
    )
    return claim, listing


async def _execute_claim_withdrawal(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    buyer_telegram_id: int,
    claim: dict[str, Any],
    listing: dict[str, Any],
    response_target: Any,
    edit: bool,
    public_scope: bool = False,
) -> None:
    seller = await asyncio.to_thread(get_seller_by_id, str(listing['seller_id']))
    seller_config = await asyncio.to_thread(get_seller_config_by_seller_id, str(listing['seller_id']))
    payment_deadline_hours = resolve_listing_payment_deadline_hours(
        listing=listing,
        seller_config=seller_config,
        default_hours=get_config().default_payment_deadline_hours,
    )

    try:
        result = await withdraw_claim_atomic(
            claim_id=str(claim['id']),
            buyer_telegram_id=buyer_telegram_id,
            payment_deadline_hours=payment_deadline_hours,
        )
    except Exception as exc:
        logger.exception('Failed to withdraw claim %s: %s', claim.get('id'), exc)
        reply_text = 'I could not withdraw that claim just now. Please try again.'
        if edit:
            await response_target.edit_message_text(reply_text)
        else:
            await response_target.reply_text(reply_text, parse_mode='HTML')
        return

    action = str(result.get('action') or 'noop')
    if action == 'noop':
        reply_text = 'That claim is no longer withdrawable.'
        if edit:
            await response_target.edit_message_text(reply_text)
        else:
            await response_target.reply_text(reply_text, parse_mode='HTML')
        return

    withdrawn_claim = result.get('withdrawn_claim') or claim
    latest_listing = result.get('listing') or listing
    promoted_claim = result.get('promoted_claim') or None

    await asyncio.to_thread(
        set_submitted_payment_proofs_status_for_claim,
        claim_id=str(withdrawn_claim['id']),
        status='withdrawn',
    )

    if edit:
        buyer_message = (
            '<b>Claim withdrawn.</b>\n\n'
            f'Item: <code>{latest_listing.get("card_name")}</code>\n'
            f'Previous status: <code>{claim.get("status")}</code>'
        )
        if action == 'promoted':
            buyer_message += '\nThe next buyer has been promoted.'
        elif action == 'auction_closed':
            buyer_message += '\nThe auction is now closed because no other eligible bidder remained.'
        elif action == 'reactivated':
            buyer_message += '\nThe listing is no longer reserved and is active again.'
        await response_target.edit_message_text(buyer_message, parse_mode='HTML')
    else:
        buyer_message = '✅ Your claim for this listing has been withdrawn.'
        if not public_scope:
            buyer_message = (
                '<b>Claim withdrawn.</b>\n\n'
                f'Item: <code>{latest_listing.get("card_name")}</code>\n'
                f'Previous status: <code>{claim.get("status")}</code>'
            )
            if action == 'promoted':
                buyer_message += '\nThe next buyer has been promoted.'
            elif action == 'auction_closed':
                buyer_message += '\nThe auction is now closed because no other eligible bidder remained.'
            elif action == 'reactivated':
                buyer_message += '\nThe listing is no longer reserved and is active again.'
        await response_target.reply_text(buyer_message, parse_mode='HTML')


    if seller is not None:
        seller_lines = [
            '<b>Buyer withdrew their claim.</b>',
            '',
            f'Item: <code>{latest_listing.get("card_name")}</code>',
            f'Buyer: <code>{withdrawn_claim.get("buyer_display_name") or withdrawn_claim.get("buyer_telegram_id")}</code>',
        ]
        if promoted_claim is not None:
            seller_lines.append(
                f'Promoted buyer: <code>{promoted_claim.get("buyer_display_name") or promoted_claim.get("buyer_telegram_id")}</code>'
            )
        elif action == 'auction_closed':
            seller_lines.append('No eligible bidder remained, so the auction is now closed.')
        elif action == 'reactivated':
            seller_lines.append('No replacement buyer remained, so the listing is open again.')
        else:
            seller_lines.append('The active winning claim is unchanged. Only the queue was updated.')
        try:
            await context.bot.send_message(
                chat_id=int(seller['telegram_id']),
                text='\n'.join(seller_lines),
                parse_mode='HTML',
            )
        except Exception as exc:
            logger.info('Could not DM seller %s after withdrawal: %s', seller.get('telegram_id'), exc)

    if promoted_claim is not None:
        await _notify_promoted_buyer(
            application=context.application,
            listing=latest_listing,
            promoted_claim=promoted_claim,
            seller_config=seller_config,
            payment_deadline_hours=payment_deadline_hours,
        )


def _normalize_reference(value: str) -> str:
    return value.strip().upper()


async def _load_open_claim_contexts(*, buyer_telegram_id: int) -> list[dict[str, Any]]:
    claims = await asyncio.to_thread(list_open_payment_claims_for_buyer, buyer_telegram_id=buyer_telegram_id)
    contexts: list[dict[str, Any]] = []
    for claim in claims:
        claim = await asyncio.to_thread(ensure_payment_request_for_claim, claim=claim)
        listing = await asyncio.to_thread(get_listing_by_id, str(claim['listing_id']))
        if listing is None:
            continue
        seller_config = await asyncio.to_thread(get_seller_config_by_seller_id, str(listing['seller_id']))
        contexts.append({'claim': claim, 'listing': listing, 'seller_config': seller_config})
    return contexts


async def _load_withdrawable_claim_contexts(*, buyer_telegram_id: int) -> list[dict[str, Any]]:
    claims = await asyncio.to_thread(list_withdrawable_claims_for_buyer, buyer_telegram_id=buyer_telegram_id)
    contexts: list[dict[str, Any]] = []
    for claim in claims:
        claim_status = str(claim.get('status') or '')
        if claim_status in WINNING_CLAIM_STATUSES:
            claim = await asyncio.to_thread(ensure_payment_request_for_claim, claim=claim)
        listing = await asyncio.to_thread(get_listing_by_id, str(claim['listing_id']))
        if listing is None:
            continue
        seller_config = await asyncio.to_thread(get_seller_config_by_seller_id, str(listing['seller_id']))
        contexts.append({'claim': claim, 'listing': listing, 'seller_config': seller_config})
    return contexts



def _payment_selection_keyboard(claim_contexts: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows = []
    for item in claim_contexts[:10]:
        claim = item['claim']
        listing = item['listing']
        label = f'{claim.get("payment_reference") or "Select"} · {listing.get("card_name")}'
        rows.append([InlineKeyboardButton(label[:64], callback_data=f'payment:select:{claim["id"]}')])
    return InlineKeyboardMarkup(rows)



def _withdrawal_selection_keyboard(claim_contexts: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows = []
    for item in claim_contexts[:10]:
        claim = item['claim']
        listing = item['listing']
        status = str(claim.get('status') or 'queued')
        reference = str(claim.get('payment_reference') or status.upper())
        label = f'{reference} · {listing.get("card_name")}'
        rows.append([InlineKeyboardButton(label[:64], callback_data=f'claimwithdraw:select:{claim["id"]}')])
    return InlineKeyboardMarkup(rows)



def _withdraw_confirm_keyboard(claim_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton('✅ Confirm Withdraw', callback_data=f'claimwithdraw:confirm:{claim_id}')],
            [InlineKeyboardButton('Keep Claim', callback_data=f'claimwithdraw:cancel:{claim_id}')],
        ]
    )



def _format_claim_pick_list(claim_contexts: list[dict[str, Any]]) -> str:
    lines = ['<b>Select which payment you are submitting.</b>', '']
    for item in claim_contexts:
        claim = item['claim']
        listing = item['listing']
        lines.append(
            f'• <code>{claim.get("payment_reference")}</code> — '
            f'<code>{listing.get("card_name")}</code> — '
            f'<code>SGD {float(listing.get("price_sgd") or 0):.2f}</code>'
        )
    lines.append('')
    lines.append('Then send the payment screenshot here.')
    return '\n'.join(lines)



def _format_withdrawable_claims(claim_contexts: list[dict[str, Any]]) -> str:
    lines = ['<b>Select which claim to withdraw.</b>', '']
    for item in claim_contexts:
        claim = item['claim']
        listing = item['listing']
        claim_status = str(claim.get('status') or 'queued')
        reference = str(claim.get('payment_reference') or claim_status.upper())
        lines.append(
            f'• <code>{reference}</code> — '
            f'<code>{listing.get("card_name")}</code> — '
            f'<code>{claim_status}</code>'
        )
    lines.append('')
    lines.append('Withdrawing a winning claim will immediately free or promote the listing.')
    return '\n'.join(lines)


async def _resolve_claim_for_message(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    buyer_telegram_id: int,
    message_text: str | None,
) -> dict[str, Any] | None:
    claim_contexts = await _load_open_claim_contexts(buyer_telegram_id=buyer_telegram_id)
    if not claim_contexts:
        return None

    by_claim_id = {str(item['claim']['id']): item['claim'] for item in claim_contexts}
    if message_text:
        match = _PAYMENT_REFERENCE_RE.search(message_text.upper())
        if match is not None:
            selected_reference = _normalize_reference(match.group(1))
            claim = await asyncio.to_thread(get_claim_by_payment_reference, payment_reference=selected_reference)
            if claim is not None and int(claim.get('buyer_telegram_id') or 0) == buyer_telegram_id:
                return claim

    selected_claim_id = str(context.user_data.get(_PAYMENT_SELECTION_KEY) or '')
    if selected_claim_id and selected_claim_id in by_claim_id:
        return by_claim_id[selected_claim_id]

    if len(claim_contexts) == 1:
        only_claim = claim_contexts[0]['claim']
        context.user_data[_PAYMENT_SELECTION_KEY] = str(only_claim['id'])
        return only_claim

    return None


async def _resolve_withdrawable_claim(
    *,
    buyer_telegram_id: int,
    reference: str | None,
    selected_claim_id: str | None,
) -> dict[str, Any] | None:
    claim_contexts = await _load_withdrawable_claim_contexts(buyer_telegram_id=buyer_telegram_id)
    by_id = {str(item['claim']['id']): item['claim'] for item in claim_contexts}

    if reference:
        matched_claim = await asyncio.to_thread(get_claim_by_payment_reference, payment_reference=_normalize_reference(reference))
        if matched_claim is not None and int(matched_claim.get('buyer_telegram_id') or 0) == buyer_telegram_id:
            return matched_claim

    if selected_claim_id and selected_claim_id in by_id:
        return by_id[selected_claim_id]

    if len(claim_contexts) == 1:
        return claim_contexts[0]['claim']

    return None


async def pay_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show pending buyer payments and let the buyer pick the proof target claim."""

    if update.effective_message is None or update.effective_user is None:
        return
    if not await _require_private_chat(update):
        return

    claim_contexts = await _load_open_claim_contexts(buyer_telegram_id=update.effective_user.id)
    if not claim_contexts:
        await update.effective_message.reply_text(
            'You do not have any active payment requests right now.',
            parse_mode='HTML',
        )
        return

    selected_claim = None
    if context.args:
        payment_reference = _normalize_reference(' '.join(context.args))
        matched_claim = await asyncio.to_thread(get_claim_by_payment_reference, payment_reference=payment_reference)
        if matched_claim is None or int(matched_claim.get('buyer_telegram_id') or 0) != update.effective_user.id:
            await update.effective_message.reply_text(
                'I could not find that payment reference in your active claims.',
                parse_mode='HTML',
            )
            return
        selected_claim = matched_claim
    elif len(claim_contexts) == 1:
        selected_claim = claim_contexts[0]['claim']

    if selected_claim is not None:
        context.user_data[_PAYMENT_SELECTION_KEY] = str(selected_claim['id'])
        listing = next(item['listing'] for item in claim_contexts if str(item['claim']['id']) == str(selected_claim['id']))
        seller_config = next(item['seller_config'] for item in claim_contexts if str(item['claim']['id']) == str(selected_claim['id']))
        await update.effective_message.reply_text(
            build_buyer_payment_message(
                listing=listing,
                claim=selected_claim,
                seller_config=seller_config,
                deadline_hours=resolve_listing_payment_deadline_hours(
                    listing=listing,
                    seller_config=seller_config,
                    default_hours=get_config().default_payment_deadline_hours,
                ),
                intro='Payment selected.',
            ),
            parse_mode='HTML',
        )
        return

    await update.effective_message.reply_text(
        _format_claim_pick_list(claim_contexts),
        parse_mode='HTML',
        reply_markup=_payment_selection_keyboard(claim_contexts),
    )


async def unclaim_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Let buyers explicitly withdraw queued or active claims."""

    if update.effective_message is None or update.effective_user is None:
        return
    if not await _require_private_chat(update):
        return

    claim_contexts = await _load_withdrawable_claim_contexts(buyer_telegram_id=update.effective_user.id)
    if not claim_contexts:
        await update.effective_message.reply_text(
            'You do not have any queued or active claims to withdraw right now.',
            parse_mode='HTML',
        )
        return

    selected_claim = await _resolve_withdrawable_claim(
        buyer_telegram_id=update.effective_user.id,
        reference=' '.join(context.args).strip() if context.args else None,
        selected_claim_id=str(context.user_data.get(_WITHDRAW_SELECTION_KEY) or ''),
    )
    if selected_claim is not None:
        context.user_data[_WITHDRAW_SELECTION_KEY] = str(selected_claim['id'])
        listing = next(item['listing'] for item in claim_contexts if str(item['claim']['id']) == str(selected_claim['id']))
        await update.effective_message.reply_text(
            (
                '<b>Confirm claim withdrawal</b>\n\n'
                f'Item: <code>{listing.get("card_name")}</code>\n'
                f'Status: <code>{selected_claim.get("status")}</code>\n'
                f'Reference: <code>{selected_claim.get("payment_reference") or "N/A"}</code>\n\n'
                'This cannot be undone. If you are the current winning buyer, the next buyer may be promoted immediately.'
            ),
            parse_mode='HTML',
            reply_markup=_withdraw_confirm_keyboard(str(selected_claim['id'])),
        )
        return

    await update.effective_message.reply_text(
        _format_withdrawable_claims(claim_contexts),
        parse_mode='HTML',
        reply_markup=_withdrawal_selection_keyboard(claim_contexts),
    )


async def payment_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Persist the buyer's selected pending claim for screenshot upload."""

    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    await query.answer()

    selected_claim_id = query.data.rsplit(':', 1)[-1] if query.data else ''
    claim = await asyncio.to_thread(get_claim_by_id, selected_claim_id)
    if claim is None or int(claim.get('buyer_telegram_id') or 0) != update.effective_user.id:
        await query.edit_message_text('That payment request is no longer available.')
        return

    listing = await asyncio.to_thread(get_listing_by_id, str(claim['listing_id']))
    seller_config = await asyncio.to_thread(get_seller_config_by_seller_id, str(listing['seller_id'])) if listing else None
    context.user_data[_PAYMENT_SELECTION_KEY] = str(claim['id'])

    if listing is None:
        await query.edit_message_text('That listing could not be loaded anymore.')
        return

    claim = await asyncio.to_thread(ensure_payment_request_for_claim, claim=claim)
    await query.edit_message_text(
        build_buyer_payment_message(
            listing=listing,
            claim=claim,
            seller_config=seller_config,
            deadline_hours=resolve_listing_payment_deadline_hours(
                listing=listing,
                seller_config=seller_config,
                default_hours=get_config().default_payment_deadline_hours,
            ),
            intro='Payment selected.',
        ),
        parse_mode='HTML',
    )


async def claim_withdraw_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show a confirmation prompt before claim withdrawal."""

    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    await query.answer()

    claim_id = query.data.rsplit(':', 1)[-1]
    claim = await asyncio.to_thread(get_claim_by_id, claim_id)
    if claim is None or int(claim.get('buyer_telegram_id') or 0) != update.effective_user.id:
        await query.edit_message_text('That claim is no longer available to withdraw.')
        return

    listing = await asyncio.to_thread(get_listing_by_id, str(claim['listing_id']))
    context.user_data[_WITHDRAW_SELECTION_KEY] = str(claim['id'])
    if listing is None:
        await query.edit_message_text('That listing could not be loaded anymore.')
        return

    await query.edit_message_text(
        (
            '<b>Confirm claim withdrawal</b>\n\n'
            f'Item: <code>{listing.get("card_name")}</code>\n'
            f'Status: <code>{claim.get("status")}</code>\n'
            f'Reference: <code>{claim.get("payment_reference") or "N/A"}</code>\n\n'
            'This cannot be undone. If you are the current winning buyer, the next buyer may be promoted immediately.'
        ),
        parse_mode='HTML',
        reply_markup=_withdraw_confirm_keyboard(str(claim['id'])),
    )


async def _notify_promoted_buyer(
    *,
    application: Application,
    listing: dict[str, Any],
    promoted_claim: dict[str, Any],
    seller_config: dict[str, Any] | None,
    payment_deadline_hours: int,
) -> None:
    promoted_claim = await asyncio.to_thread(ensure_payment_request_for_claim, claim=promoted_claim)
    buyer_telegram_id = promoted_claim.get('buyer_telegram_id')
    if not buyer_telegram_id:
        return
    try:
        dm_message = await application.bot.send_message(
            chat_id=int(buyer_telegram_id),
            text=build_buyer_payment_message(
                listing=listing,
                claim=promoted_claim,
                seller_config=seller_config,
                deadline_hours=payment_deadline_hours,
                intro='You are now first in line for this listing.',
            ),
            parse_mode='HTML',
        )
        await asyncio.to_thread(
            mark_payment_prompt_sent,
            claim_id=str(promoted_claim['id']),
            message_id=dm_message.message_id,
        )
    except Exception as exc:
        logger.info('Could not DM promoted buyer %s after withdrawal: %s', buyer_telegram_id, exc)


async def claim_withdraw_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Withdraw a buyer claim and resolve queue promotion side effects."""

    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    await query.answer()

    claim_id = query.data.rsplit(':', 1)[-1]
    claim = await asyncio.to_thread(get_claim_by_id, claim_id)
    if claim is None or int(claim.get('buyer_telegram_id') or 0) != update.effective_user.id:
        await query.edit_message_text('That claim is no longer available to withdraw.')
        return

    listing = await asyncio.to_thread(get_listing_by_id, str(claim['listing_id']))
    if listing is None:
        await query.edit_message_text('That listing could not be loaded anymore.')
        return

    seller = await asyncio.to_thread(get_seller_by_id, str(listing['seller_id']))
    seller_config = await asyncio.to_thread(get_seller_config_by_seller_id, str(listing['seller_id']))
    payment_deadline_hours = resolve_listing_payment_deadline_hours(
        listing=listing,
        seller_config=seller_config,
        default_hours=get_config().default_payment_deadline_hours,
    )

    try:
        result = await withdraw_claim_atomic(
            claim_id=str(claim['id']),
            buyer_telegram_id=update.effective_user.id,
            payment_deadline_hours=payment_deadline_hours,
        )
    except Exception as exc:
        logger.exception('Failed to withdraw claim %s: %s', claim.get('id'), exc)
        await query.edit_message_text('I could not withdraw that claim just now. Please try again.')
        return

    action = str(result.get('action') or 'noop')
    if action == 'noop':
        await query.edit_message_text('That claim is no longer withdrawable.')
        return

    withdrawn_claim = result.get('withdrawn_claim') or claim
    latest_listing = result.get('listing') or listing
    promoted_claim = result.get('promoted_claim') or None

    await asyncio.to_thread(
        set_submitted_payment_proofs_status_for_claim,
        claim_id=str(withdrawn_claim['id']),
        status='withdrawn',
    )
    context.user_data.pop(_WITHDRAW_SELECTION_KEY, None)
    if str(context.user_data.get(_PAYMENT_SELECTION_KEY) or '') == str(withdrawn_claim['id']):
        context.user_data.pop(_PAYMENT_SELECTION_KEY, None)

    buyer_message = (
        '<b>Claim withdrawn.</b>\n\n'
        f'Item: <code>{latest_listing.get("card_name")}</code>\n'
        f'Previous status: <code>{claim.get("status")}</code>'
    )
    if action == 'promoted':
        buyer_message += '\nThe next buyer has been promoted.'
    elif action == 'auction_closed':
        buyer_message += '\nThe auction is now closed because no other eligible bidder remained.'
    elif action == 'reactivated':
        buyer_message += '\nThe listing is no longer reserved and is active again.'
    await query.edit_message_text(buyer_message, parse_mode='HTML')

    if seller is not None:
        seller_lines = [
            '<b>Buyer withdrew their claim.</b>',
            '',
            f'Item: <code>{latest_listing.get("card_name")}</code>',
            f'Buyer: <code>{withdrawn_claim.get("buyer_display_name") or withdrawn_claim.get("buyer_telegram_id")}</code>',
        ]
        if promoted_claim is not None:
            seller_lines.append(
                f'Promoted buyer: <code>{promoted_claim.get("buyer_display_name") or promoted_claim.get("buyer_telegram_id")}</code>'
            )
        elif action == 'auction_closed':
            seller_lines.append('No eligible bidder remained, so the auction is now closed.')
        elif action == 'reactivated':
            seller_lines.append('No replacement buyer remained, so the listing is open again.')
        else:
            seller_lines.append('The active winning claim is unchanged. Only the queue was updated.')
        try:
            await context.bot.send_message(
                chat_id=int(seller['telegram_id']),
                text='\n'.join(seller_lines),
                parse_mode='HTML',
            )
        except Exception as exc:
            logger.info('Could not DM seller %s after withdrawal: %s', seller.get('telegram_id'), exc)

    if promoted_claim is not None:
        await _notify_promoted_buyer(
            application=context.application,
            listing=latest_listing,
            promoted_claim=promoted_claim,
            seller_config=seller_config,
            payment_deadline_hours=payment_deadline_hours,
        )


async def claim_withdraw_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dismiss the withdraw confirmation prompt."""

    query = update.callback_query
    if query is None:
        return
    await query.answer()
    await query.edit_message_text('Withdrawal cancelled.')


async def handle_payment_proof_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Accept a buyer screenshot in DM, store it, and send it to the seller for review."""

    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return

    claim = await _resolve_claim_for_message(
        context=context,
        buyer_telegram_id=user.id,
        message_text=message.caption or message.text,
    )
    if claim is None:
        claim_contexts = await _load_open_claim_contexts(buyer_telegram_id=user.id)
        if len(claim_contexts) > 1:
            await message.reply_text(
                _format_claim_pick_list(claim_contexts),
                parse_mode='HTML',
                reply_markup=_payment_selection_keyboard(claim_contexts),
            )
            return
        await message.reply_text(
            'I could not match this screenshot to an active payment request. Run <code>/pay</code> first.',
            parse_mode='HTML',
        )
        return

    listing = await asyncio.to_thread(get_listing_by_id, str(claim['listing_id']))
    if listing is None:
        await message.reply_text('That listing is no longer available.', parse_mode='HTML')
        return

    seller = await asyncio.to_thread(get_seller_by_id, str(listing['seller_id']))
    if seller is None:
        await message.reply_text('The seller record could not be loaded right now.', parse_mode='HTML')
        return

    photo = message.photo[-1] if message.photo else None
    document = message.document if photo is None else None
    if photo is None and document is None:
        await message.reply_text('Please send the payment screenshot as an image.', parse_mode='HTML')
        return

    telegram_file_id = photo.file_id if photo is not None else str(document.file_id)
    extension = '.jpg' if photo is not None else (Path(str(document.file_name or 'proof.jpg')).suffix or '.jpg')
    telegram_file = await context.bot.get_file(telegram_file_id)

    with tempfile.TemporaryDirectory(prefix='payment-proof-') as temp_dir:
        local_path = Path(temp_dir) / f'proof{extension}'
        await telegram_file.download_to_drive(custom_path=local_path)
        try:
            storage_path = await asyncio.to_thread(
                upload_payment_proof_photo,
                local_path=str(local_path),
                seller_id=str(seller['id']),
                claim_id=str(claim['id']),
                telegram_file_id=telegram_file_id,
            )
        except Exception as exc:
            logger.exception('Failed to upload payment proof for claim %s: %s', claim.get('id'), exc)
            await message.reply_text(
                'I could not store this payment proof just now. Please try again in a moment.',
                parse_mode='HTML',
            )
            return

    proof = await asyncio.to_thread(
        create_payment_proof,
        claim_id=str(claim['id']),
        listing_id=str(listing['id']),
        seller_id=str(seller['id']),
        buyer_telegram_id=user.id,
        payment_reference=str(claim.get('payment_reference') or ''),
        storage_path=storage_path,
        telegram_file_id=telegram_file_id,
        telegram_message_id=message.message_id,
        buyer_caption=message.caption,
    )

    seller_caption_lines = [
        '<b>Payment proof submitted.</b>',
        '',
        f'Item: <code>{listing.get("card_name")}</code>',
        f'Buyer: <code>{claim.get("buyer_display_name") or user.full_name}</code>',
        f'Reference: <code>{claim.get("payment_reference")}</code>',
        f'Amount: <code>SGD {float(listing.get("price_sgd") or 0):.2f}</code>',
    ]
    if message.caption:
        seller_caption_lines.extend(['', f'Buyer note: {html.escape(message.caption)}'])

    seller_message = await context.bot.send_photo(
        chat_id=int(seller['telegram_id']),
        photo=telegram_file_id,
        caption='\n'.join(seller_caption_lines),
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton('✅ Mark Paid', callback_data=f'paymentproof:approve:{proof["id"]}'),
                    InlineKeyboardButton('❌ Reject', callback_data=f'paymentproof:reject:{proof["id"]}'),
                ]
            ]
        ),
    )

    logger.info(
        'Forwarded payment proof %s for claim %s to seller %s as message %s.',
        proof.get('id'),
        claim.get('id'),
        seller.get('telegram_id'),
        seller_message.message_id,
    )

    await message.reply_text(
        (
            '<b>Payment proof sent to the seller.</b>\n\n'
            f'Reference: <code>{claim.get("payment_reference")}</code>\n'
            'I will update you when the seller reviews it.'
        ),
        parse_mode='HTML',
    )


async def payment_proof_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle seller approval or rejection of a buyer payment proof."""

    query = update.callback_query
    if query is None or update.effective_user is None or query.data is None:
        return
    await query.answer()

    seller = await asyncio.to_thread(get_seller_by_telegram_id, update.effective_user.id)
    if seller is None:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text('Seller profile not found. Run <code>/setup</code> first.', parse_mode='HTML')
        return

    _, action, proof_id = query.data.split(':', 2)
    proof = await asyncio.to_thread(get_payment_proof_by_id, proof_id)
    if proof is None or str(proof.get('seller_id')) != str(seller['id']):
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text('That payment proof is no longer available.', parse_mode='HTML')
        return

    claim = await asyncio.to_thread(get_claim_by_id, str(proof['claim_id']))
    listing = await asyncio.to_thread(get_listing_by_id, str(proof['listing_id']))
    if claim is None or listing is None:
        await asyncio.to_thread(set_payment_proof_status_by_id, proof_id=proof_id, status='stale')
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text('The linked listing or claim no longer exists.', parse_mode='HTML')
        return

    current_claim_status = str(claim.get('status') or '')
    if current_claim_status not in {'confirmed', 'payment_pending'}:
        replacement_status = 'withdrawn' if current_claim_status == 'withdrawn' else 'expired' if current_claim_status == 'failed' else 'stale'
        await asyncio.to_thread(set_payment_proof_status_by_id, proof_id=proof_id, status=replacement_status)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f'This proof can no longer be reviewed because the claim is now <code>{html.escape(current_claim_status or "inactive")}</code>.',
            parse_mode='HTML',
        )
        return

    if str(proof.get('status') or '') != 'submitted':
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f'This proof was already resolved as <code>{html.escape(str(proof.get("status") or "unknown"))}</code>.',
            parse_mode='HTML',
        )
        return

    if action == 'reject':
        reviewed = await asyncio.to_thread(
            set_payment_proof_status_by_id,
            proof_id=proof_id,
            status='rejected',
            reviewed_by_telegram_id=update.effective_user.id,
        )
        if reviewed is None:
            await query.message.reply_text('That proof was already reviewed earlier.', parse_mode='HTML')
            return
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            (
                'Rejected payment proof for '
                f'<code>{listing.get("card_name")}</code>. The buyer has been asked to resubmit.'
            ),
            parse_mode='HTML',
        )
        buyer_telegram_id = claim.get('buyer_telegram_id')
        if buyer_telegram_id:
            try:
                await context.bot.send_message(
                    chat_id=int(buyer_telegram_id),
                    text=(
                        '<b>Your payment proof was rejected.</b>\n\n'
                        f'Item: <code>{listing.get("card_name")}</code>\n'
                        f'Reference: <code>{claim.get("payment_reference")}</code>\n'
                        'Please send a clearer screenshot or the correct payment proof here.'
                    ),
                    parse_mode='HTML',
                )
            except Exception as exc:
                logger.info('Could not DM buyer %s after proof rejection: %s', buyer_telegram_id, exc)
        return

    try:
        result = await complete_sale_for_listing(context=context, seller=seller, listing=listing)
    except Exception as exc:
        logger.exception('Failed to complete sale during proof approval for listing %s: %s', listing.get('id'), exc)
        await query.message.reply_text(
            'I could not complete the sale just now. The proof stays pending; please try again.',
            parse_mode='HTML',
        )
        return

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(
        (
            '✅ Marked paid and completed the sale.\n\n'
            f'Item: <code>{listing.get("card_name")}</code>\n'
            f'Transaction: <code>{(result.get("transaction") or {}).get("id")}</code>'
        ),
        parse_mode='HTML',
    )



def register_payment_handlers(application: Application) -> None:
    """Register buyer payment, claim withdrawal, and seller proof-review handlers."""

    application.add_handler(CommandHandler('pay', pay_command))
    application.add_handler(CommandHandler('unclaim', unclaim_command))
    application.add_handler(CallbackQueryHandler(payment_select_callback, pattern=r'^payment:select:'))
    application.add_handler(CallbackQueryHandler(claim_withdraw_select_callback, pattern=r'^claimwithdraw:select:'))
    application.add_handler(CallbackQueryHandler(claim_withdraw_confirm_callback, pattern=r'^claimwithdraw:confirm:'))
    application.add_handler(CallbackQueryHandler(claim_withdraw_cancel_callback, pattern=r'^claimwithdraw:cancel:'))
    application.add_handler(CallbackQueryHandler(payment_proof_review_callback, pattern=r'^paymentproof:(?:approve|reject):'))
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & (filters.PHOTO | filters.Document.IMAGE) & ~filters.COMMAND,
            handle_payment_proof_upload,
        )
    )
