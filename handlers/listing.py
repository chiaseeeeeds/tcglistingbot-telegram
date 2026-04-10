"""Listing handler registrations for TCG Listing Bot."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4

from telegram import ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from db.listings import create_listing
from db.seller_configs import get_seller_config_by_seller_id
from db.sellers import get_seller_by_telegram_id
from services.card_identifier import identify_card_from_text, parse_manual_identifier
from services.image_storage import upload_listing_photo
from services.ocr import OCRNotConfiguredError, extract_text_from_image
from services.price_lookup import PriceReference, lookup_price_references
from utils.formatters import format_fixed_price_listing

logger = logging.getLogger(__name__)

PHOTO, GAME, TITLE, PRICE, NOTES, CONFIRM = range(6)
SUPPORTED_GAMES = {'pokemon', 'onepiece'}
TEMP_PHOTO_DIR = Path(gettempdir()) / 'tcg-listing-bot'


def _ensure_temp_photo_dir() -> Path:
    TEMP_PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    return TEMP_PHOTO_DIR


def _clear_listing_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in [
        'listing_seller_id',
        'listing_seller_config',
        'listing_photo_path',
        'listing_storage_path',
        'listing_ocr_text',
        'listing_game',
        'listing_title',
        'listing_suggested_title',
        'listing_card_id',
        'listing_detection_mode',
        'listing_price_sgd',
        'listing_notes',
        'listing_price_refs',
    ]:
        context.user_data.pop(key, None)


def _listing_preview(*, game: str, title: str, price_sgd: float, notes: str, price_refs: list[PriceReference]) -> str:
    """Build a compact listing preview for seller confirmation."""

    notes_text = notes if notes else 'No extra notes'
    price_lines = []
    if price_refs:
        for reference in price_refs:
            price_lines.append(f"- {reference.source}: SGD {reference.amount_sgd:.2f} ({reference.note})")
    else:
        price_lines.append('- No live price references available yet.')

    return (
        '<b>Listing Preview</b>\n\n'
        f'Game: <code>{game}</code>\n'
        f'Title: <code>{title}</code>\n'
        f'Price: <code>SGD {price_sgd:.2f}</code>\n'
        f'Notes: <code>{notes_text}</code>\n'
        'Price refs:\n'
        + '\n'.join(price_lines)
        + '\n\nReply with <code>post</code> to publish or <code>cancel</code> to stop.'
    )


def _format_price_reference_block(price_refs: list[PriceReference]) -> str:
    if not price_refs:
        return (
            '<b>Price references</b>\n'
            'No live website references are connected yet, so no automatic market pull was available.\n'
            'You can still set your own price below.'
        )
    lines = ['<b>Price references</b>']
    for reference in price_refs:
        lines.append(
            f"• <b>{reference.source}</b>: <code>SGD {reference.amount_sgd:.2f}</code> — {reference.note}"
        )
    return '\n'.join(lines)


async def _load_seller_context(update: Update, context: ContextTypes.DEFAULT_TYPE) -> tuple[dict, dict] | None:
    if update.effective_message is None or update.effective_user is None:
        return None

    seller = await asyncio.to_thread(get_seller_by_telegram_id, update.effective_user.id)
    if seller is None:
        await update.effective_message.reply_text(
            'Please use /start first so I can create your seller account.',
            parse_mode='HTML',
        )
        return None

    seller_config = await asyncio.to_thread(get_seller_config_by_seller_id, seller['id'])
    if seller_config is None or not seller_config.get('setup_complete'):
        await update.effective_message.reply_text(
            'Please complete /setup before posting a listing.',
            parse_mode='HTML',
        )
        return None

    channel_name = seller_config.get('primary_channel_name')
    if not channel_name:
        await update.effective_message.reply_text(
            'No primary channel is configured yet. Run /setup again first.',
            parse_mode='HTML',
        )
        return None

    context.user_data['listing_seller_id'] = seller['id']
    context.user_data['listing_seller_config'] = seller_config
    return seller, seller_config


async def list_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the photo-first listing flow."""

    loaded = await _load_seller_context(update, context)
    if loaded is None or update.effective_message is None:
        return ConversationHandler.END

    _clear_listing_state(context)
    seller, seller_config = loaded
    context.user_data['listing_seller_id'] = seller['id']
    context.user_data['listing_seller_config'] = seller_config
    await update.effective_message.reply_text(
        'Send a clear front photo of the card to begin.\n\n'
        'For now, v1 works best with one front image per listing.',
        parse_mode='HTML',
        reply_markup=ReplyKeyboardRemove(),
    )
    return PHOTO


async def photo_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Allow sellers to begin listing creation by sending a photo directly in DM."""

    loaded = await _load_seller_context(update, context)
    if loaded is None:
        return ConversationHandler.END

    _clear_listing_state(context)
    seller, seller_config = loaded
    context.user_data['listing_seller_id'] = seller['id']
    context.user_data['listing_seller_config'] = seller_config
    return await capture_photo(update, context)


async def capture_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store a listing photo locally, run OCR, and continue the flow."""

    if update.effective_message is None or not update.effective_message.photo:
        await update.effective_message.reply_text('Please send a card photo to continue.', parse_mode='HTML')
        return PHOTO

    try:
        photo = update.effective_message.photo[-1]
        telegram_file = await context.bot.get_file(photo.file_id)
        temp_dir = _ensure_temp_photo_dir()
        local_path = temp_dir / f'{uuid4()}.jpg'
        await telegram_file.download_to_drive(custom_path=local_path)
        context.user_data['listing_photo_path'] = str(local_path)

        seller_id = context.user_data.get('listing_seller_id')
        if seller_id:
            storage_path = await asyncio.to_thread(
                upload_listing_photo,
                local_path=str(local_path),
                seller_id=seller_id,
                telegram_file_id=photo.file_unique_id,
            )
            if storage_path:
                context.user_data['listing_storage_path'] = storage_path

        ocr_result = await asyncio.to_thread(extract_text_from_image, str(local_path))
        context.user_data['listing_ocr_text'] = ocr_result.text

        warning_block = ''
        if ocr_result.warnings:
            warning_block = '\n'.join(f'• {warning}' for warning in ocr_result.warnings) + '\n\n'

        await update.effective_message.reply_text(
            'Photo received.\n\n'
            f'{warning_block}'
            'Which game is this card from? Reply with <code>pokemon</code> or <code>onepiece</code>.',
            parse_mode='HTML',
        )
        return GAME
    except OCRNotConfiguredError as exc:
        logger.exception('OCR provider misconfigured during listing flow: %s', exc)
        await update.effective_message.reply_text(
            'OCR is not configured correctly right now. Please try again later or enter the title manually after I restore OCR.',
            parse_mode='HTML',
        )
        _clear_listing_state(context)
        return ConversationHandler.END
    except Exception as exc:
        logger.exception('Failed to capture photo for listing: %s', exc)
        await update.effective_message.reply_text(
            'I could not process that photo. Please send a clear card image and try again.',
            parse_mode='HTML',
        )
        return PHOTO


async def capture_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Capture the game, identify the card, and move to title confirmation."""

    if update.effective_message is None or update.effective_message.text is None:
        return GAME

    game = update.effective_message.text.strip().lower()
    if game not in SUPPORTED_GAMES:
        await update.effective_message.reply_text(
            'Please reply with <code>pokemon</code> or <code>onepiece</code>.',
            parse_mode='HTML',
        )
        return GAME

    context.user_data['listing_game'] = game
    raw_text = str(context.user_data.get('listing_ocr_text') or '')
    identification = await asyncio.to_thread(identify_card_from_text, raw_text=raw_text, game=game)

    if identification.matched:
        context.user_data['listing_detection_mode'] = 'matched'
        context.user_data['listing_suggested_title'] = identification.display_name
        context.user_data['listing_card_id'] = identification.card_id
        reasons = '\n'.join(f'• {reason}' for reason in identification.match_reasons) or '• OCR text roughly matched the local catalog.'
        await update.effective_message.reply_text(
            '<b>I found a likely card match</b>\n\n'
            f'Title: <code>{identification.display_name}</code>\n'
            f'Confidence: <code>{identification.confidence:.2f}</code>\n'
            f'Reasons:\n{reasons}\n\n'
            'Reply with <code>yes</code> to use this title, or send the corrected title manually.\n'
            'If OCR got the card wrong, you can also reply with the printed identifier like <code>PAF 234/091</code>.',
            parse_mode='HTML',
        )
        return TITLE

    context.user_data['listing_detection_mode'] = 'needs_identifier'
    await update.effective_message.reply_text(
        '<b>I could not confidently identify the card from OCR.</b>\n\n'
        f'OCR text: <code>{raw_text[:220] or "No usable text detected"}</code>\n\n'
        'Reply with the printed identifier like <code>PAF 234/091</code>.\n'
        'If you prefer, you can still enter the listing title manually.',
        parse_mode='HTML',
    )
    return TITLE


async def capture_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Capture a confirmed title or resolve a manual identifier before pricing."""

    if update.effective_message is None or update.effective_message.text is None:
        return TITLE

    raw_text = update.effective_message.text.strip()
    if raw_text.lower() == 'yes' and context.user_data.get('listing_suggested_title'):
        title = str(context.user_data['listing_suggested_title'])
    else:
        manual_identifier = parse_manual_identifier(raw_text)
        if manual_identifier is not None:
            identifier_text = (
                f"IDENTIFIER: {manual_identifier['detected_set_code']} {manual_identifier['detected_print_number']}"
            )
            identification = await asyncio.to_thread(
                identify_card_from_text,
                raw_text=identifier_text,
                game=str(context.user_data['listing_game']),
            )
            if identification.matched:
                context.user_data['listing_detection_mode'] = 'matched'
                context.user_data['listing_suggested_title'] = identification.display_name
                context.user_data['listing_card_id'] = identification.card_id
                title = identification.display_name
                await update.effective_message.reply_text(
                    '<b>Identifier matched successfully.</b>\n\n'
                    f'Title: <code>{identification.display_name}</code>\n'
                    f'Confidence: <code>{identification.confidence:.2f}</code>',
                    parse_mode='HTML',
                )
            else:
                await update.effective_message.reply_text(
                    'I still could not match that identifier. Reply with another code like '
                    '<code>PAF 234/091</code> or send the title manually.',
                    parse_mode='HTML',
                )
                return TITLE
        else:
            title = raw_text

    context.user_data['listing_title'] = title
    price_refs = await asyncio.to_thread(
        lookup_price_references,
        game=str(context.user_data['listing_game']),
        card_name=title,
        card_id=context.user_data.get('listing_card_id'),
    )
    context.user_data['listing_price_refs'] = price_refs
    await update.effective_message.reply_text(
        _format_price_reference_block(price_refs)
        + '\n\nEnter your final price in SGD. Example: <code>25</code> or <code>25.50</code>.',
        parse_mode='HTML',
    )
    return PRICE


async def capture_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Capture the listing price and continue to optional notes."""

    if update.effective_message is None or update.effective_message.text is None:
        return PRICE

    try:
        price_sgd = float(update.effective_message.text.strip())
    except ValueError:
        await update.effective_message.reply_text(
            'Please enter a valid numeric price, such as <code>25</code> or <code>25.50</code>.',
            parse_mode='HTML',
        )
        return PRICE

    context.user_data['listing_price_sgd'] = price_sgd
    await update.effective_message.reply_text(
        'Enter any notes or condition details, or reply with <code>skip</code>.',
        parse_mode='HTML',
    )
    return NOTES


async def capture_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Capture optional notes and show the seller a final preview."""

    if update.effective_message is None or update.effective_message.text is None:
        return NOTES

    text = update.effective_message.text.strip()
    notes = '' if text.lower() == 'skip' else text
    context.user_data['listing_notes'] = notes
    await update.effective_message.reply_text(
        _listing_preview(
            game=str(context.user_data['listing_game']),
            title=str(context.user_data['listing_title']),
            price_sgd=float(context.user_data['listing_price_sgd']),
            notes=notes,
            price_refs=list(context.user_data.get('listing_price_refs') or []),
        ),
        parse_mode='HTML',
    )
    return CONFIRM


async def confirm_listing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Post the listing to Telegram and persist the created listing row."""

    if update.effective_message is None or update.effective_message.text is None:
        return CONFIRM

    decision = update.effective_message.text.strip().lower()
    if decision == 'cancel':
        await update.effective_message.reply_text('Listing cancelled.', parse_mode='HTML')
        _clear_listing_state(context)
        return ConversationHandler.END

    if decision != 'post':
        await update.effective_message.reply_text(
            'Reply with <code>post</code> to publish or <code>cancel</code> to stop.',
            parse_mode='HTML',
        )
        return CONFIRM

    seller_config = context.user_data['listing_seller_config']
    price_refs = list(context.user_data.get('listing_price_refs') or [])
    listing_text = format_fixed_price_listing(
        card_name=str(context.user_data['listing_title']),
        game=str(context.user_data['listing_game']),
        price_sgd=float(context.user_data['listing_price_sgd']),
        condition_notes=str(context.user_data['listing_notes']),
        custom_description='',
        seller_display_name=seller_config.get('seller_display_name') or 'Seller',
        payment_methods=seller_config.get('payment_methods') or ['PayNow'],
    )

    photo_path = context.user_data.get('listing_photo_path')
    if photo_path:
        with Path(photo_path).open('rb') as photo_file:
            sent_message = await context.bot.send_photo(
                chat_id=seller_config['primary_channel_name'],
                photo=photo_file,
                caption=listing_text,
                parse_mode='HTML',
            )
    else:
        sent_message = await context.bot.send_message(
            chat_id=seller_config['primary_channel_name'],
            text=listing_text,
            parse_mode='HTML',
        )

    listing = await asyncio.to_thread(
        create_listing,
        seller_id=context.user_data['listing_seller_id'],
        card_id=context.user_data.get('listing_card_id'),
        card_name=context.user_data['listing_title'],
        game=context.user_data['listing_game'],
        price_sgd=context.user_data['listing_price_sgd'],
        condition_notes=context.user_data['listing_notes'],
        custom_description='',
        posted_channel_id=sent_message.chat.id,
        posted_message_id=sent_message.message_id,
        primary_image_path=context.user_data.get('listing_storage_path'),
        tcgplayer_price_sgd=price_refs[0].amount_sgd if price_refs else None,
    )
    logger.info('Posted listing %s to channel %s.', listing['id'], sent_message.chat.id)
    await update.effective_message.reply_text(
        f'✅ Listing posted to <code>{seller_config["primary_channel_name"]}</code>.\n'
        f'Message ID: <code>{sent_message.message_id}</code>',
        parse_mode='HTML',
        reply_markup=ReplyKeyboardRemove(),
    )
    _clear_listing_state(context)
    return ConversationHandler.END


async def cancel_listing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the listing conversation and clear temporary state."""

    if update.effective_message is not None:
        await update.effective_message.reply_text('Listing cancelled.', reply_markup=ReplyKeyboardRemove())
    _clear_listing_state(context)
    return ConversationHandler.END


def register_listing_handlers(application: Application) -> None:
    """Register listing-related command handlers on the Telegram application."""

    conversation = ConversationHandler(
        allow_reentry=True,
        entry_points=[
            CommandHandler('list', list_entry),
            MessageHandler(filters.ChatType.PRIVATE & filters.PHOTO, photo_entry),
        ],
        states={
            PHOTO: [MessageHandler(filters.ChatType.PRIVATE & filters.PHOTO, capture_photo)],
            GAME: [MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, capture_game)],
            TITLE: [MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, capture_title)],
            PRICE: [MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, capture_price)],
            NOTES: [MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, capture_notes)],
            CONFIRM: [MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, confirm_listing)],
        },
        fallbacks=[CommandHandler('cancel', cancel_listing)],
        name='manual_listing',
        persistent=False,
    )
    application.add_handler(conversation)
