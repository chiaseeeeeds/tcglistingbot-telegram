"""Listing handler registrations for TCG Listing Bot."""

from __future__ import annotations

import asyncio
import logging
from html import escape
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import get_config
from db.listings import create_listing
from db.seller_configs import get_seller_config_by_seller_id
from db.sellers import get_seller_by_telegram_id
from services.card_identifier import identify_card_from_text, parse_manual_identifier
from services.game_detection import detect_game_from_image
from services.image_storage import upload_listing_photo
from services.set_symbol_matcher import rerank_candidate_options_by_symbol
from services.ocr import OCRNotConfiguredError, extract_text_from_image
from services.price_lookup import PriceReference, lookup_price_references
from utils.formatters import format_fixed_price_listing

logger = logging.getLogger(__name__)

OCR_BUILD_MARKER = 'ocr-build-2026-04-12-structured-signals-v13'

PHOTO, TITLE, PRICE, NOTES, CONFIRM = range(5)
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
        'listing_candidate_options',
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




def _price_ref_button_key(reference: PriceReference) -> str:
    source = reference.source.lower()
    if 'pricecharting' in source:
        return 'pricecharting'
    if 'yuyutei' in source:
        return 'yuyutei'
    if 'tcgplayer' in source:
        return 'tcgplayer'
    if 'cardmarket' in source:
        return 'cardmarket'
    if 'history' in source or 'median' in source:
        return 'history'
    return 'market'


def _price_reference_keyboard(price_refs: list[PriceReference]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, reference in enumerate(price_refs[:4]):
        label = f"Use {reference.source}: SGD {reference.amount_sgd:.2f}"
        rows.append([InlineKeyboardButton(label[:64], callback_data=f'listing_price_ref:{index}')])
    rows.append([InlineKeyboardButton('Enter custom price', callback_data='listing_price_custom')])
    return InlineKeyboardMarkup(rows)

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




def _admin_debug_line(*, update: Update | None, identification, candidate_options: list[dict]) -> str:
    if update is None or update.effective_user is None:
        return ''
    admin_ids = set(get_config().bot_admin_telegram_ids)
    if update.effective_user.id not in admin_ids:
        return ''

    top = str(candidate_options[0]['display_name']) if candidate_options else 'none'
    metadata = identification.metadata or {}
    resolver = str(metadata.get('resolver') or 'unknown')
    service_build = str(metadata.get('service_build') or 'unknown')
    detected_print_number = str(metadata.get('detected_print_number') or 'none')
    detected_set_code = str(metadata.get('detected_set_code') or metadata.get('set_code') or 'none')
    catalog_size = str(metadata.get('catalog_size') or 'unknown')
    number_candidate_count = str(metadata.get('number_candidate_count') or 'unknown')
    number_candidate_preview = str(metadata.get('number_candidate_preview') or 'unknown')
    return (
        '<b>Debug</b>\n'
        f"resolver=<code>{escape(resolver[:60])}</code> "
        f"svc=<code>{escape(service_build[:40])}</code>\n"
        f"matched=<code>{identification.matched}</code> "
        f"conf=<code>{identification.confidence:.2f}</code> "
        f"catalog=<code>{escape(catalog_size[:12])}</code>\n"
        f"detected=<code>{escape(detected_set_code[:16])}</code> "
        f"print=<code>{escape(detected_print_number[:24])}</code> "
        f"candidates=<code>{len(candidate_options)}</code>\n"
        f"left_hits=<code>{escape(number_candidate_count[:12])}</code> "
        f"sets=<code>{escape(number_candidate_preview[:40])}</code>\n"
        f"display=<code>{escape(str(identification.display_name)[:80])}</code>\n"
        f"top=<code>{escape(top[:80])}</code>\n\n"
    )

def _format_candidate_options(options: list[dict]) -> str:
    if not options:
        return ''
    lines = ['<b>Likely matches</b>']
    for index, option in enumerate(options[:3], start=1):
        line = f"{index}. <code>{option['display_name']}</code> — conf <code>{float(option['confidence']):.2f}</code>"
        if option.get('symbol_score'):
            line += f" — symbol <code>{float(option['symbol_score']):.2f}</code>"
        lines.append(line)
    lines.append('\nReply with <code>1</code>, <code>2</code>, or <code>3</code> to use one of these titles.')
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
    """Store a listing photo locally, auto-detect the game, run OCR, and continue the flow."""

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

        detected_game = await asyncio.to_thread(detect_game_from_image, str(local_path))
        game = detected_game.game if detected_game.game in SUPPORTED_GAMES else 'pokemon'
        context.user_data['listing_game'] = game

        ocr_result = await asyncio.to_thread(extract_text_from_image, str(local_path), game=game)
        context.user_data['listing_ocr_text'] = ocr_result.text
        context.user_data['listing_ocr_structured'] = ocr_result.structured.as_dict()
        raw_text = str(ocr_result.text or '')
        identification = await asyncio.to_thread(identify_card_from_text, raw_text=raw_text, game=game)
        candidate_options = list(identification.candidate_options or [])
        detected_print_number = str(identification.metadata.get('detected_print_number') or '')
        detected_set_code = str(identification.metadata.get('detected_set_code') or '')
        detected_left_number = detected_print_number.split('/')[0].lstrip('0') if detected_print_number else ''
        older_style_symbol_mode = (
            game == 'pokemon'
            and len(candidate_options) > 1
            and not detected_set_code
            and (
                (detected_left_number.isdigit() and int(detected_left_number) <= 120)
                or not detected_print_number
            )
        )
        if older_style_symbol_mode:
            candidate_options = await asyncio.to_thread(
                rerank_candidate_options_by_symbol,
                image_path=str(local_path),
                candidate_options=candidate_options,
            )
        context.user_data['listing_candidate_options'] = candidate_options

        warning_lines = [f'• Auto-detected game: {game} ({detected_game.reason}).']
        warning_lines.extend(f'• {warning}' for warning in ocr_result.warnings)
        warning_block = '\n'.join(warning_lines) + f'\n• Build: {OCR_BUILD_MARKER}.\n\n'
        admin_debug = _admin_debug_line(update=update, identification=identification, candidate_options=candidate_options)

        if identification.matched and identification.confidence >= 0.6:
            context.user_data['listing_detection_mode'] = 'matched'
            context.user_data['listing_suggested_title'] = identification.display_name
            context.user_data['listing_card_id'] = identification.card_id
            reasons = '\n'.join(f'• {reason}' for reason in identification.match_reasons) or '• OCR text roughly matched the local catalog.'
            await update.effective_message.reply_text(
                warning_block
                + admin_debug
                + '<b>I found a likely card match</b>\n\n'
                f'Title: <code>{identification.display_name}</code>\n'
                f'Confidence: <code>{identification.confidence:.2f}</code>\n'
                f'Reasons:\n{reasons}\n\n'
                'Reply with <code>yes</code> to use this title, or send the corrected title manually.\n'
                'If OCR got the card wrong, you can also reply with the printed identifier like <code>ABC 123/456</code>.',
                parse_mode='HTML',
            )
            return TITLE

        if identification.matched and identification.confidence >= 0.45:
            context.user_data['listing_detection_mode'] = 'matched'
            context.user_data['listing_suggested_title'] = identification.display_name
            context.user_data['listing_card_id'] = identification.card_id
            reasons = '\n'.join(f'• {reason}' for reason in identification.match_reasons) or '• OCR text roughly matched the local catalog.'
            message = (
                warning_block
                + admin_debug
                + '<b>I found a possible card match, but I am not confident enough to auto-lock it in.</b>\n\n'
                f'Title: <code>{identification.display_name}</code>\n'
                f'Confidence: <code>{identification.confidence:.2f}</code>\n'
                f'Reasons:\n{reasons}\n\n'
            )
            if candidate_options:
                message += _format_candidate_options(candidate_options) + '\n\n'
            message += (
                'Reply with <code>yes</code> to use this title anyway, send <code>1</code>/<code>2</code>/<code>3</code> to choose from the shortlist, '
                'or send the corrected title manually.\n'
                'If you can see the printed identifier, sending it like <code>ABC 123/456</code> is safer.'
            )
            await update.effective_message.reply_text(message, parse_mode='HTML')
            return TITLE

        context.user_data['listing_detection_mode'] = 'needs_identifier'
        message = (
            warning_block
            + admin_debug
            + '<b>I could not confidently identify the card from OCR.</b>\n\n'
            f'OCR text: <code>{raw_text[:220] or "No usable text detected"}</code>\n\n'
        )
        if candidate_options:
            message += _format_candidate_options(candidate_options) + '\n\n'
            message += (
                'Reply with <code>1</code>, <code>2</code>, or <code>3</code> to choose one of these, '
                'or send the printed identifier like <code>ABC 123/456</code>.\n'
                'If you prefer, you can still enter the listing title manually.'
            )
        else:
            message += (
                'Reply with the printed identifier like <code>ABC 123/456</code>.\n'
                'If you prefer, you can still enter the listing title manually.'
            )
        await update.effective_message.reply_text(message, parse_mode='HTML')
        return TITLE
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
    """Legacy fallback state; prompt the seller to send the photo again."""

    if update.effective_message is not None:
        await update.effective_message.reply_text(
            'Game selection is now automatic. Please send the card photo again.',
            parse_mode='HTML',
        )
    return PHOTO

async def capture_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Capture a confirmed title or resolve a manual identifier before pricing."""

    if update.effective_message is None or update.effective_message.text is None:
        return TITLE

    raw_text = update.effective_message.text.strip()
    if raw_text.lower() == 'yes' and context.user_data.get('listing_suggested_title'):
        title = str(context.user_data['listing_suggested_title'])
    elif raw_text in {'1', '2', '3'} and context.user_data.get('listing_candidate_options'):
        index = int(raw_text) - 1
        options = list(context.user_data.get('listing_candidate_options') or [])
        if index < 0 or index >= len(options):
            await update.effective_message.reply_text('That shortlist option is not available. Reply with <code>1</code>, <code>2</code>, or <code>3</code>.', parse_mode='HTML')
            return TITLE
        selected = options[index]
        title = str(selected['display_name'])
        context.user_data['listing_detection_mode'] = 'matched'
        context.user_data['listing_suggested_title'] = title
        context.user_data['listing_card_id'] = selected.get('card_id')
        await update.effective_message.reply_text(
            '<b>Shortlist option selected.</b>\n\n'
            f'Title: <code>{title}</code>\n'
            f'Confidence: <code>{float(selected.get("confidence") or 0):.2f}</code>',
            parse_mode='HTML',
        )
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
                    '<code>ABC 123/456</code> or send the title manually.',
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
        reply_markup=_price_reference_keyboard(price_refs) if price_refs else None,
    )
    return PRICE




async def capture_price_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle inline price selection buttons."""

    query = update.callback_query
    if query is None:
        return PRICE
    await query.answer()

    data = query.data or ''
    price_refs = list(context.user_data.get('listing_price_refs') or [])

    if data == 'listing_price_custom':
        await query.message.reply_text(
            'Enter your final custom price in SGD. Example: <code>25</code> or <code>25.50</code>.',
            parse_mode='HTML',
        )
        return PRICE

    if not data.startswith('listing_price_ref:'):
        return PRICE

    try:
        index = int(data.split(':', 1)[1])
    except ValueError:
        await query.message.reply_text('That price option is invalid. Please choose again or type a custom price.', parse_mode='HTML')
        return PRICE

    if index < 0 or index >= len(price_refs):
        await query.message.reply_text('That price option is no longer available. Please choose again or type a custom price.', parse_mode='HTML')
        return PRICE

    selected_ref = price_refs[index]
    context.user_data['listing_price_sgd'] = float(selected_ref.amount_sgd)
    context.user_data['listing_selected_price_source'] = _price_ref_button_key(selected_ref)

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    await query.message.reply_text(
        (
            '<b>Price selected.</b>\n\n'
            f'Source: <code>{selected_ref.source}</code>\n'
            f'Price: <code>SGD {selected_ref.amount_sgd:.2f}</code>\n\n'
            'Enter any notes or condition details, or reply with <code>skip</code>.'
        ),
        parse_mode='HTML',
    )
    return NOTES

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
    context.user_data['listing_selected_price_source'] = 'custom'
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
        tcgplayer_price_sgd=next((reference.amount_sgd for reference in price_refs if 'tcgplayer' in reference.source.lower()), None),
        pricecharting_price_sgd=next((reference.amount_sgd for reference in price_refs if 'pricecharting' in reference.source.lower()), None),
        yuyutei_price_sgd=next((reference.amount_sgd for reference in price_refs if 'yuyutei' in reference.source.lower()), None),
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
            TITLE: [MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, capture_title)],
            PRICE: [
                CallbackQueryHandler(capture_price_callback, pattern=r'^listing_price_(?:ref:\d+|custom)$'),
                MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, capture_price),
            ],
            NOTES: [MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, capture_notes)],
            CONFIRM: [MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, confirm_listing)],
        },
        fallbacks=[CommandHandler('cancel', cancel_listing)],
        name='manual_listing',
        persistent=False,
    )
    application.add_handler(conversation)
