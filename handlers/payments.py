"""Buyer payment submission and seller proof-review handlers."""

from __future__ import annotations

import asyncio
import html
import logging
import re
import tempfile
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from db.claims import (
    get_claim_by_id,
    get_claim_by_payment_reference,
    list_open_payment_claims_for_buyer,
)
from db.listings import get_listing_by_id
from db.payment_proofs import create_payment_proof, get_payment_proof_by_id, review_payment_proof
from db.seller_configs import get_seller_config_by_seller_id
from db.sellers import get_seller_by_id, get_seller_by_telegram_id
from handlers.transactions import complete_sale_for_listing
from services.image_storage import upload_payment_proof_photo
from services.payment_requests import build_buyer_payment_message, ensure_payment_request_for_claim

logger = logging.getLogger(__name__)
_PAYMENT_REFERENCE_RE = re.compile(r'(TCG-[A-Z0-9]{8})', re.IGNORECASE)
_PAYMENT_SELECTION_KEY = 'selected_payment_claim_id'


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


def _selection_keyboard(claim_contexts: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    rows = []
    for item in claim_contexts[:10]:
        claim = item['claim']
        listing = item['listing']
        label = f'{claim.get("payment_reference") or "Select"} · {listing.get("card_name")}'
        rows.append([InlineKeyboardButton(label[:64], callback_data=f'payment:select:{claim["id"]}')])
    return InlineKeyboardMarkup(rows)


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


async def pay_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show pending buyer payments and let the buyer pick the proof target claim."""

    if update.effective_message is None or update.effective_user is None:
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
                deadline_hours=int((seller_config or {}).get('payment_deadline_hours') or 24),
                intro='Payment selected.',
            ),
            parse_mode='HTML',
        )
        return

    await update.effective_message.reply_text(
        _format_claim_pick_list(claim_contexts),
        parse_mode='HTML',
        reply_markup=_selection_keyboard(claim_contexts),
    )


async def payment_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Persist the buyer's selected pending claim for screenshot upload."""

    query = update.callback_query
    if query is None or update.effective_user is None:
        return
    await query.answer()

    seller_claim_id = query.data.rsplit(':', 1)[-1] if query.data else ''
    claim = await asyncio.to_thread(get_claim_by_id, seller_claim_id)
    if claim is None or int(claim.get('buyer_telegram_id') or 0) != update.effective_user.id:
        await query.edit_message_text('That payment request is no longer available.')
        return

    listing = await asyncio.to_thread(get_listing_by_id, str(claim['listing_id']))
    seller_config = await asyncio.to_thread(get_seller_config_by_seller_id, str(listing['seller_id'])) if listing else None
    context.user_data[_PAYMENT_SELECTION_KEY] = str(claim['id'])

    if listing is None:
        await query.edit_message_text('That listing could not be loaded anymore.')
        return

    await query.edit_message_text(
        build_buyer_payment_message(
            listing=listing,
            claim=claim,
            seller_config=seller_config,
            deadline_hours=int((seller_config or {}).get('payment_deadline_hours') or 24),
            intro='Payment selected.',
        ),
        parse_mode='HTML',
    )


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
                reply_markup=_selection_keyboard(claim_contexts),
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

    listing = await asyncio.to_thread(get_listing_by_id, str(proof['listing_id']))
    claim = await asyncio.to_thread(get_claim_by_id, str(proof['claim_id']))
    if listing is None or claim is None:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text('The linked listing or claim could not be loaded.', parse_mode='HTML')
        return

    if action == 'reject':
        reviewed = await asyncio.to_thread(
            review_payment_proof,
            proof_id=proof_id,
            seller_id=str(seller['id']),
            reviewed_by_telegram_id=update.effective_user.id,
            status='rejected',
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

    reviewed = await asyncio.to_thread(
        review_payment_proof,
        proof_id=proof_id,
        seller_id=str(seller['id']),
        reviewed_by_telegram_id=update.effective_user.id,
        status='approved',
    )
    if reviewed is None:
        logger.info('Payment proof %s approval review was already processed.', proof_id)

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
    """Register buyer payment and seller proof-review handlers."""

    application.add_handler(CommandHandler('pay', pay_command))
    application.add_handler(CallbackQueryHandler(payment_select_callback, pattern=r'^payment:select:'))
    application.add_handler(CallbackQueryHandler(payment_proof_review_callback, pattern=r'^paymentproof:(?:approve|reject):'))
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & (filters.PHOTO | filters.Document.IMAGE) & ~filters.COMMAND,
            handle_payment_proof_upload,
        )
    )
