"""Auction handler registrations for TCG Listing Bot."""

from __future__ import annotations

import asyncio
import logging
from time import perf_counter
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, ReplyKeyboardRemove, Update
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
from handlers.listing import (
    MAX_LISTING_IMAGES,
    OCR_BUILD_MARKER,
    SUPPORTED_GAMES,
    _admin_debug_line,
    _ensure_temp_photo_dir,
    _format_candidate_options,
    _format_price_reference_block,
    _load_seller_context,
    _photo_collection_prompt,
    _price_ref_button_key,
    _price_reference_keyboard,
)
from services.card_identifier import identify_card_from_text, parse_manual_identifier
from services.image_storage import upload_listing_photo
from services.listing_image_classifier import classify_listing_images
from services.ocr import OCRNotConfiguredError
from services.price_lookup import PriceReference, lookup_price_references
from services.set_symbol_matcher import rerank_candidate_options_by_symbol
from utils.formatters import format_auction_listing
from utils.photo_quality import format_quality_summary

logger = logging.getLogger(__name__)

PHOTO, TITLE, STARTING_BID, BID_INCREMENT, DURATION, NOTES, CONFIRM = range(7)


AUCTION_DURATION_OPTIONS_HOURS = (6, 12, 24, 48)


def _photo_quality_warning_lines(*, label: str, quality) -> list[str]:
    if quality is None:
        return []
    lines = [f'• {label}: {format_quality_summary(quality)}.']
    lines.extend(f'• {warning}' for warning in quality.warnings)
    if not quality.acceptable:
        lines.append('• This image looks weak for OCR. If the match looks wrong, retake the front photo with tighter framing and lower glare.')
    return lines


async def reject_unsupported_auction_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Reject unsupported auction intake media types with a clear message."""

    if update.effective_message is not None:
        await update.effective_message.reply_text(
            'Please send card photos only while building an auction, or reply with <code>done</code> when the batch is complete.',
            parse_mode='HTML',
        )
    return PHOTO


def _clear_auction_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in [
        'auction_seller_id',
        'auction_seller_config',
        'auction_photos',
        'auction_front_photo_index',
        'auction_back_photo_index',
        'auction_photo_path',
        'auction_storage_path',
        'auction_secondary_photo_path',
        'auction_secondary_storage_path',
        'auction_post_image_local_paths',
        'auction_post_image_storage_paths',
        'auction_ocr_text',
        'auction_ocr_structured',
        'auction_game',
        'auction_title',
        'auction_suggested_title',
        'auction_card_id',
        'auction_detection_mode',
        'auction_candidate_options',
        'auction_price_refs',
        'auction_starting_bid_sgd',
        'auction_bid_increment_sgd',
        'auction_duration_hours',
        'auction_end_time',
        'auction_notes',
        'auction_selected_price_source',
    ]:
        context.user_data.pop(key, None)



def _format_duration_options() -> str:
    labels = ', '.join(f'<code>{value}</code>h' for value in AUCTION_DURATION_OPTIONS_HOURS)
    return f'Choose auction duration in hours, for example {labels}, or enter another positive number.'



def _auction_preview(
    *,
    game: str,
    title: str,
    starting_bid_sgd: float,
    bid_increment_sgd: float,
    auction_end_time: str,
    notes: str,
    price_refs: list[PriceReference],
    image_count: int,
    has_back: bool,
) -> str:
    notes_text = notes if notes else 'No extra notes'
    price_lines = []
    if price_refs:
        for reference in price_refs:
            price_lines.append(f"- {reference.source}: SGD {reference.amount_sgd:.2f} ({reference.note})")
    else:
        price_lines.append('- No usable live market references were returned right now.')

    config = get_config()
    try:
        local_end_time = datetime.fromisoformat(str(auction_end_time).replace('Z', '+00:00')).astimezone(
            ZoneInfo(config.default_timezone)
        )
        end_text = local_end_time.strftime('%Y-%m-%d %H:%M %Z')
    except Exception:
        end_text = str(auction_end_time)

    return (
        '<b>Auction Preview</b>\n\n'
        f'Game: <code>{game}</code>\n'
        f'Title: <code>{title}</code>\n'
        f'Starting bid: <code>SGD {starting_bid_sgd:.2f}</code>\n'
        f'Bid increment: <code>SGD {bid_increment_sgd:.2f}</code>\n'
        f'Ends: <code>{end_text}</code>\n'
        f'Photos: <code>{image_count}</code>\n'
        f'Front/back: <code>{"yes" if has_back else "front only"}</code>\n'
        f'Notes: <code>{notes_text}</code>\n'
        'Price refs:\n'
        + '\n'.join(price_lines)
        + '\n\nReply with <code>post</code> to publish or <code>cancel</code> to stop.'
    )


async def auction_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the photo-first auction flow."""

    loaded = await _load_seller_context(update, context)
    if loaded is None or update.effective_message is None:
        return ConversationHandler.END

    _clear_auction_state(context)
    seller, seller_config = loaded
    context.user_data['auction_seller_id'] = seller['id']
    context.user_data['auction_seller_config'] = seller_config
    await update.effective_message.reply_text(
        'Send the auction card photos now — front and back, individually or as an album.\n\n'
        'When you are done uploading photos, reply with <code>done</code>.',
        parse_mode='HTML',
        reply_markup=ReplyKeyboardRemove(),
    )
    return PHOTO


async def capture_auction_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Collect one or more auction photos before OCR and matching."""

    if update.effective_message is None or not update.effective_message.photo:
        await update.effective_message.reply_text('Please send card photos to continue.', parse_mode='HTML')
        return PHOTO

    try:
        photo_entries = list(context.user_data.get('auction_photos') or [])
        if len(photo_entries) >= MAX_LISTING_IMAGES:
            await update.effective_message.reply_text(
                f'I already have <code>{MAX_LISTING_IMAGES}</code> photos for this auction. Reply with <code>done</code> to continue.',
                parse_mode='HTML',
            )
            return PHOTO

        photo = update.effective_message.photo[-1]
        if any(str(entry.get('file_unique_id') or '') == photo.file_unique_id for entry in photo_entries):
            await update.effective_message.reply_text(
                'That photo is already in the current batch. Send another image or reply with <code>done</code>.',
                parse_mode='HTML',
            )
            return PHOTO

        telegram_file = await context.bot.get_file(photo.file_id)
        temp_dir = _ensure_temp_photo_dir()
        local_path = temp_dir / f'{uuid4()}.jpg'
        await telegram_file.download_to_drive(custom_path=local_path)

        storage_path = None
        seller_id = context.user_data.get('auction_seller_id')
        if seller_id:
            storage_path = await asyncio.to_thread(
                upload_listing_photo,
                local_path=str(local_path),
                seller_id=seller_id,
                telegram_file_id=photo.file_unique_id,
            )

        photo_entries.append(
            {
                'local_path': str(local_path),
                'storage_path': storage_path,
                'file_unique_id': str(photo.file_unique_id),
            }
        )
        context.user_data['auction_photos'] = photo_entries
        await update.effective_message.reply_text(
            _photo_collection_prompt(count=len(photo_entries)),
            parse_mode='HTML',
        )
        return PHOTO
    except Exception as exc:
        logger.exception('Failed to capture photo for auction: %s', exc)
        await update.effective_message.reply_text(
            'I could not save that photo. Please send it again, or reply with <code>done</code> if the batch is complete.',
            parse_mode='HTML',
        )
        return PHOTO


async def finalize_auction_photo_batch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Classify uploaded auction photos, choose front/back, and continue to OCR + matching."""

    if update.effective_message is None or update.effective_message.text is None:
        return PHOTO

    decision = update.effective_message.text.strip().lower()
    if decision not in {'done', 'finish', 'continue', 'next'}:
        await update.effective_message.reply_text(
            'Send more card photos, or reply with <code>done</code> when the batch is complete.',
            parse_mode='HTML',
        )
        return PHOTO

    photo_entries = list(context.user_data.get('auction_photos') or [])
    if not photo_entries:
        await update.effective_message.reply_text('Please send at least one card photo first.', parse_mode='HTML')
        return PHOTO

    try:
        config = get_config()
        if config.ocr_provider == 'openai_gpt4o_mini':
            progress_text = (
                f'Scanning your auction photo with <code>{escape(config.openai_ocr_model)}</code> now. '
                'This uses the hosted raw-photo OCR path first and may still need manual correction if the image is weak.'
            )
        else:
            progress_text = (
                f'Processing your auction photo batch with <code>{escape(config.ocr_provider)}</code> now. '
                'OCR can take a bit on some images, so please give me a moment.'
            )
        await update.effective_message.reply_text(progress_text, parse_mode='HTML')
        started_at = perf_counter()
        logger.info('Starting auction photo-batch finalization for seller=%s images=%s.', getattr(update.effective_user, 'id', None), len(photo_entries))
        selection = await asyncio.to_thread(
            classify_listing_images,
            [str(entry['local_path']) for entry in photo_entries],
            preferred_game=str(context.user_data.get('auction_game') or '') or None,
        )
        logger.info('Completed auction photo-batch finalization for seller=%s in %.2fs.', getattr(update.effective_user, 'id', None), perf_counter() - started_at)
        front_index = selection.front_index if selection.front_index is not None else 0
        back_index = selection.back_index
        ordered_entries = [photo_entries[index] for index in selection.ordered_indices]
        front_entry = photo_entries[front_index]
        back_entry = photo_entries[back_index] if back_index is not None else None
        front_analysis = selection.analyses[front_index]

        context.user_data['auction_front_photo_index'] = front_index
        context.user_data['auction_back_photo_index'] = back_index
        context.user_data['auction_photo_path'] = str(front_entry['local_path'])
        context.user_data['auction_storage_path'] = front_entry.get('storage_path')
        context.user_data['auction_secondary_photo_path'] = str(back_entry['local_path']) if back_entry else None
        context.user_data['auction_secondary_storage_path'] = back_entry.get('storage_path') if back_entry else None
        context.user_data['auction_post_image_local_paths'] = [str(entry['local_path']) for entry in ordered_entries]
        context.user_data['auction_post_image_storage_paths'] = [str(entry.get('storage_path') or '') for entry in ordered_entries]

        detected_game = front_analysis.game_detection
        game = front_analysis.game if front_analysis.game in SUPPORTED_GAMES else 'pokemon'
        context.user_data['auction_game'] = game

        ocr_result = front_analysis.ocr_result
        identification = front_analysis.identification
        context.user_data['auction_ocr_text'] = ocr_result.text
        context.user_data['auction_ocr_structured'] = ocr_result.structured.as_dict()

        candidate_options = list(identification.candidate_options or [])
        detected_print_number = str(identification.metadata.get('detected_print_number') or '')
        detected_set_code = str(identification.metadata.get('detected_set_code') or '')
        detected_left_number = detected_print_number.split('/')[0].lstrip('0') if detected_print_number else ''
        older_style_symbol_mode = (
            game == 'pokemon'
            and len(candidate_options) > 1
            and not detected_set_code
            and ((detected_left_number.isdigit() and int(detected_left_number) <= 120) or not detected_print_number)
        )
        if older_style_symbol_mode:
            candidate_options = await asyncio.to_thread(
                rerank_candidate_options_by_symbol,
                image_path=str(front_entry['local_path']),
                candidate_options=candidate_options,
            )
        context.user_data['auction_candidate_options'] = candidate_options

        warning_lines = [f'• Received <code>{len(photo_entries)}</code> image(s) for this auction.']
        warning_lines.append(f'• Auto-detected game from the selected front image: {game} ({detected_game.reason}).')
        if back_entry is not None:
            warning_lines.append(
                f'• Selected photo <code>{front_index + 1}</code> as front and photo <code>{back_index + 1}</code> as back.'
            )
        else:
            warning_lines.append('• Only one usable photo was provided, so this auction will post with a single image.')
        extra_count = max(len(ordered_entries) - (2 if back_entry is not None else 1), 0)
        if extra_count:
            warning_lines.append(f'• {extra_count} extra photo(s) will also be attached to the auction post.')
        warning_lines.extend(_photo_quality_warning_lines(label='Selected front photo quality', quality=front_analysis.photo_quality))
        if back_entry is not None and back_index is not None:
            warning_lines.extend(_photo_quality_warning_lines(label='Selected back photo quality', quality=selection.analyses[back_index].photo_quality))
        warning_lines.extend(f'• {warning}' for warning in ocr_result.warnings)
        warning_block = '\n'.join(warning_lines) + f'\n• Build: {OCR_BUILD_MARKER}.\n\n'
        admin_debug = _admin_debug_line(update=update, identification=identification, candidate_options=candidate_options, ocr_result=ocr_result)

        if identification.matched and identification.confidence >= 0.6:
            context.user_data['auction_detection_mode'] = 'matched'
            context.user_data['auction_suggested_title'] = identification.display_name
            context.user_data['auction_card_id'] = identification.card_id
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

        message = warning_block + admin_debug
        if identification.matched and identification.confidence >= 0.45:
            context.user_data['auction_detection_mode'] = 'matched'
            context.user_data['auction_suggested_title'] = identification.display_name
            context.user_data['auction_card_id'] = identification.card_id
            reasons = '\n'.join(f'• {reason}' for reason in identification.match_reasons) or '• OCR text roughly matched the local catalog.'
            message += (
                '<b>I found a possible card match, but I am not confident enough to auto-lock it in.</b>\n\n'
                f'Title: <code>{identification.display_name}</code>\n'
                f'Confidence: <code>{identification.confidence:.2f}</code>\n'
                f'Reasons:\n{reasons}\n\n'
            )
        else:
            message += 'I could not confidently identify the card from OCR.\n\n'
            if context.user_data.get('auction_ocr_text'):
                message += f'OCR text: <code>{escape(str(context.user_data.get("auction_ocr_text") or "")[:500])}</code>\n\n'
        candidate_block = _format_candidate_options(candidate_options)
        if candidate_block:
            message += candidate_block + '\n\n'
        message += (
            'Reply with the printed identifier like <code>ABC 123/456</code>.\n'
            'If you prefer, you can still enter the auction title manually.'
        )
        await update.effective_message.reply_text(message, parse_mode='HTML')
        return TITLE
    except OCRNotConfiguredError as exc:
        logger.exception('OCR provider misconfigured during auction flow: %s', exc)
        await update.effective_message.reply_text(
            'OCR is not configured correctly right now. Please try again later or enter the title manually after I restore OCR.',
            parse_mode='HTML',
        )
        _clear_auction_state(context)
        return ConversationHandler.END
    except Exception as exc:
        logger.exception('Failed to finalize auction photo batch: %s', exc)
        await update.effective_message.reply_text(
            'I could not process that photo batch. Please send the photos again, or try with clearer front/back images.',
            parse_mode='HTML',
        )
        return PHOTO


async def capture_auction_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Capture a confirmed title or resolve a manual identifier before auction settings."""

    if update.effective_message is None or update.effective_message.text is None:
        return TITLE

    raw_text = update.effective_message.text.strip()
    if raw_text.lower() == 'yes' and context.user_data.get('auction_suggested_title'):
        title = str(context.user_data['auction_suggested_title'])
    elif raw_text in {'1', '2', '3'} and context.user_data.get('auction_candidate_options'):
        index = int(raw_text) - 1
        options = list(context.user_data.get('auction_candidate_options') or [])
        if index < 0 or index >= len(options):
            await update.effective_message.reply_text(
                'That shortlist option is not available. Reply with <code>1</code>, <code>2</code>, or <code>3</code>.',
                parse_mode='HTML',
            )
            return TITLE
        selected = options[index]
        title = str(selected['display_name'])
        context.user_data['auction_detection_mode'] = 'matched'
        context.user_data['auction_suggested_title'] = title
        context.user_data['auction_card_id'] = selected.get('card_id')
        await update.effective_message.reply_text(
            '<b>Shortlist option selected.</b>\n\n'
            f'Title: <code>{title}</code>\n'
            f'Confidence: <code>{float(selected.get("confidence") or 0):.2f}</code>',
            parse_mode='HTML',
        )
    else:
        manual_identifier = parse_manual_identifier(raw_text)
        if manual_identifier is not None:
            identifier_text = f"IDENTIFIER: {manual_identifier['detected_set_code']} {manual_identifier['detected_print_number']}"
            identification = await asyncio.to_thread(
                identify_card_from_text,
                raw_text=identifier_text,
                game=str(context.user_data['auction_game']),
            )
            if identification.matched:
                context.user_data['auction_detection_mode'] = 'matched'
                context.user_data['auction_suggested_title'] = identification.display_name
                context.user_data['auction_card_id'] = identification.card_id
                title = identification.display_name
                await update.effective_message.reply_text(
                    '<b>Identifier matched successfully.</b>\n\n'
                    f'Title: <code>{identification.display_name}</code>\n'
                    f'Confidence: <code>{identification.confidence:.2f}</code>',
                    parse_mode='HTML',
                )
            else:
                await update.effective_message.reply_text(
                    'I still could not match that identifier. Reply with another code like <code>ABC 123/456</code> or send the title manually.',
                    parse_mode='HTML',
                )
                return TITLE
        else:
            title = raw_text

    context.user_data['auction_title'] = title
    price_refs = await asyncio.to_thread(
        lookup_price_references,
        game=str(context.user_data['auction_game']),
        card_name=title,
        card_id=context.user_data.get('auction_card_id'),
    )
    context.user_data['auction_price_refs'] = price_refs
    await update.effective_message.reply_text(
        _format_price_reference_block(price_refs)
        + '\n\nEnter your auction starting bid in SGD. Example: <code>10</code> or <code>10.50</code>.',
        parse_mode='HTML',
        reply_markup=_price_reference_keyboard(price_refs) if price_refs else None,
    )
    return STARTING_BID


async def capture_starting_bid_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle inline price-selection buttons for auction starting bid."""

    query = update.callback_query
    if query is None:
        return STARTING_BID
    await query.answer()

    data = query.data or ''
    price_refs = list(context.user_data.get('auction_price_refs') or [])

    if data == 'listing_price_custom':
        await query.message.reply_text(
            'Enter your auction starting bid in SGD. Example: <code>10</code> or <code>10.50</code>.',
            parse_mode='HTML',
        )
        return STARTING_BID

    if not data.startswith('listing_price_ref:'):
        return STARTING_BID

    try:
        index = int(data.split(':', 1)[1])
    except ValueError:
        await query.message.reply_text('That price option is invalid. Please choose again or type a custom starting bid.', parse_mode='HTML')
        return STARTING_BID

    if index < 0 or index >= len(price_refs):
        await query.message.reply_text('That price option is no longer available. Please choose again or type a custom starting bid.', parse_mode='HTML')
        return STARTING_BID

    selected_ref = price_refs[index]
    context.user_data['auction_starting_bid_sgd'] = float(selected_ref.amount_sgd)
    context.user_data['auction_selected_price_source'] = _price_ref_button_key(selected_ref)

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    await query.message.reply_text(
        (
            '<b>Starting bid selected.</b>\n\n'
            f'Source: <code>{selected_ref.source}</code>\n'
            f'Starting bid: <code>SGD {selected_ref.amount_sgd:.2f}</code>\n\n'
            'Enter the minimum bid increment in SGD. Example: <code>0.50</code> or <code>1</code>.'
        ),
        parse_mode='HTML',
    )
    return BID_INCREMENT


async def capture_starting_bid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_message is None or update.effective_message.text is None:
        return STARTING_BID

    try:
        starting_bid_sgd = float(update.effective_message.text.strip())
        if starting_bid_sgd <= 0:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text(
            'Please enter a valid numeric starting bid, such as <code>10</code> or <code>10.50</code>.',
            parse_mode='HTML',
        )
        return STARTING_BID

    context.user_data['auction_starting_bid_sgd'] = starting_bid_sgd
    context.user_data['auction_selected_price_source'] = 'custom'
    await update.effective_message.reply_text(
        'Enter the minimum bid increment in SGD. Example: <code>0.50</code> or <code>1</code>.',
        parse_mode='HTML',
    )
    return BID_INCREMENT


async def capture_bid_increment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_message is None or update.effective_message.text is None:
        return BID_INCREMENT

    try:
        bid_increment_sgd = float(update.effective_message.text.strip())
        if bid_increment_sgd <= 0:
            raise ValueError
    except ValueError:
        await update.effective_message.reply_text(
            'Please enter a valid numeric bid increment, such as <code>0.50</code> or <code>1</code>.',
            parse_mode='HTML',
        )
        return BID_INCREMENT

    context.user_data['auction_bid_increment_sgd'] = bid_increment_sgd
    await update.effective_message.reply_text(
        _format_duration_options(),
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(f'{value}h', callback_data=f'auction_duration:{value}')] for value in AUCTION_DURATION_OPTIONS_HOURS]
        ),
    )
    return DURATION


async def capture_duration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None:
        return DURATION
    await query.answer()

    data = query.data or ''
    if not data.startswith('auction_duration:'):
        return DURATION

    try:
        hours = float(data.split(':', 1)[1])
    except ValueError:
        await query.message.reply_text('That duration option is invalid. Enter the duration in hours instead.', parse_mode='HTML')
        return DURATION

    return await _store_auction_duration(hours=hours, update=update, context=context)


async def capture_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_message is None or update.effective_message.text is None:
        return DURATION

    try:
        hours = float(update.effective_message.text.strip())
    except ValueError:
        await update.effective_message.reply_text(
            'Please enter the auction duration in hours, such as <code>12</code> or <code>24</code>.',
            parse_mode='HTML',
        )
        return DURATION

    return await _store_auction_duration(hours=hours, update=update, context=context)


async def _store_auction_duration(*, hours: float, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_message is None:
        return DURATION
    if hours <= 0:
        await update.effective_message.reply_text(
            'Please enter a positive auction duration in hours.',
            parse_mode='HTML',
        )
        return DURATION

    end_time = datetime.now(timezone.utc) + timedelta(hours=hours)
    context.user_data['auction_duration_hours'] = hours
    context.user_data['auction_end_time'] = end_time.isoformat()
    await update.effective_message.reply_text(
        'Enter any notes or condition details, or reply with <code>skip</code>.',
        parse_mode='HTML',
        reply_markup=None,
    )
    return NOTES


async def capture_auction_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_message is None or update.effective_message.text is None:
        return NOTES

    text = update.effective_message.text.strip()
    notes = '' if text.lower() == 'skip' else text
    context.user_data['auction_notes'] = notes
    await update.effective_message.reply_text(
        _auction_preview(
            game=str(context.user_data['auction_game']),
            title=str(context.user_data['auction_title']),
            starting_bid_sgd=float(context.user_data['auction_starting_bid_sgd']),
            bid_increment_sgd=float(context.user_data['auction_bid_increment_sgd']),
            auction_end_time=str(context.user_data['auction_end_time']),
            notes=notes,
            price_refs=list(context.user_data.get('auction_price_refs') or []),
            image_count=len(context.user_data.get('auction_post_image_local_paths') or ([context.user_data.get('auction_photo_path')] if context.user_data.get('auction_photo_path') else [])),
            has_back=bool(context.user_data.get('auction_secondary_photo_path')),
        ),
        parse_mode='HTML',
    )
    return CONFIRM


async def confirm_auction_listing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_message is None or update.effective_message.text is None:
        return CONFIRM

    decision = update.effective_message.text.strip().lower()
    if decision == 'cancel':
        await update.effective_message.reply_text('Auction cancelled.', parse_mode='HTML')
        _clear_auction_state(context)
        return ConversationHandler.END

    if decision != 'post':
        await update.effective_message.reply_text(
            'Reply with <code>post</code> to publish or <code>cancel</code> to stop.',
            parse_mode='HTML',
        )
        return CONFIRM

    seller_config = context.user_data['auction_seller_config']
    listing_text = format_auction_listing(
        card_name=str(context.user_data['auction_title']),
        game=str(context.user_data['auction_game']),
        starting_bid_sgd=float(context.user_data['auction_starting_bid_sgd']),
        current_bid_sgd=None,
        bid_increment_sgd=float(context.user_data['auction_bid_increment_sgd']),
        condition_notes=str(context.user_data['auction_notes']),
        custom_description='',
        seller_display_name=seller_config.get('seller_display_name') or 'Seller',
        auction_end_time=str(context.user_data['auction_end_time']),
        status='auction_active',
    )

    photo_paths = [path for path in list(context.user_data.get('auction_post_image_local_paths') or []) if path]
    if photo_paths:
        if len(photo_paths) == 1:
            with Path(photo_paths[0]).open('rb') as photo_file:
                sent_message = await context.bot.send_photo(
                    chat_id=seller_config['primary_channel_name'],
                    photo=photo_file,
                    caption=listing_text,
                    parse_mode='HTML',
                )
        else:
            opened_files = []
            try:
                media = []
                for index, photo_path in enumerate(photo_paths[:10]):
                    file_handle = Path(photo_path).open('rb')
                    opened_files.append(file_handle)
                    if index == 0:
                        media.append(InputMediaPhoto(media=file_handle, caption=listing_text, parse_mode='HTML'))
                    else:
                        media.append(InputMediaPhoto(media=file_handle))
                sent_messages = await context.bot.send_media_group(
                    chat_id=seller_config['primary_channel_name'],
                    media=media,
                )
                sent_message = sent_messages[0]
            finally:
                for file_handle in opened_files:
                    file_handle.close()
    else:
        sent_message = await context.bot.send_message(
            chat_id=seller_config['primary_channel_name'],
            text=listing_text,
            parse_mode='HTML',
        )

    listing = await asyncio.to_thread(
        create_listing,
        seller_id=context.user_data['auction_seller_id'],
        card_id=context.user_data.get('auction_card_id'),
        card_name=context.user_data['auction_title'],
        game=context.user_data['auction_game'],
        price_sgd=None,
        condition_notes=context.user_data['auction_notes'],
        custom_description='',
        posted_channel_id=sent_message.chat.id,
        posted_message_id=sent_message.message_id,
        primary_image_path=context.user_data.get('auction_storage_path'),
        secondary_image_path=context.user_data.get('auction_secondary_storage_path'),
        tcgplayer_price_sgd=next((reference.amount_sgd for reference in context.user_data.get('auction_price_refs') or [] if 'tcgplayer' in reference.source.lower()), None),
        pricecharting_price_sgd=next((reference.amount_sgd for reference in context.user_data.get('auction_price_refs') or [] if 'pricecharting' in reference.source.lower()), None),
        yuyutei_price_sgd=next((reference.amount_sgd for reference in context.user_data.get('auction_price_refs') or [] if 'yuyutei' in reference.source.lower()), None),
        listing_type='auction',
        starting_bid_sgd=float(context.user_data['auction_starting_bid_sgd']),
        current_bid_sgd=None,
        bid_increment_sgd=float(context.user_data['auction_bid_increment_sgd']),
        auction_end_time=str(context.user_data['auction_end_time']),
    )
    logger.info('Posted auction listing %s to channel %s.', listing['id'], sent_message.chat.id)
    await update.effective_message.reply_text(
        f'✅ Auction posted to <code>{seller_config["primary_channel_name"]}</code>.\n'
        f'Message ID: <code>{sent_message.message_id}</code>',
        parse_mode='HTML',
        reply_markup=ReplyKeyboardRemove(),
    )
    _clear_auction_state(context)
    return ConversationHandler.END


async def cancel_auction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_message is not None:
        await update.effective_message.reply_text('Auction cancelled.', reply_markup=ReplyKeyboardRemove())
    _clear_auction_state(context)
    return ConversationHandler.END


def register_auction_handlers(application: Application) -> None:
    """Register auction-related command handlers on the Telegram application."""

    conversation = ConversationHandler(
        allow_reentry=True,
        entry_points=[CommandHandler('auction', auction_entry)],
        states={
            PHOTO: [
                MessageHandler(filters.ChatType.PRIVATE & filters.PHOTO, capture_auction_photo),
                MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, finalize_auction_photo_batch),
                MessageHandler(filters.ChatType.PRIVATE & ~filters.TEXT & ~filters.PHOTO, reject_unsupported_auction_media),
            ],
            TITLE: [MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, capture_auction_title)],
            STARTING_BID: [
                CallbackQueryHandler(capture_starting_bid_callback, pattern=r'^listing_price_(?:ref:\d+|custom)$'),
                MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, capture_starting_bid),
            ],
            BID_INCREMENT: [MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, capture_bid_increment)],
            DURATION: [
                CallbackQueryHandler(capture_duration_callback, pattern=r'^auction_duration:'),
                MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, capture_duration),
            ],
            NOTES: [MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, capture_auction_notes)],
            CONFIRM: [MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, confirm_auction_listing)],
        },
        fallbacks=[CommandHandler('cancel', cancel_auction)],
        name='auction_listing',
        persistent=False,
    )
    application.add_handler(conversation)
