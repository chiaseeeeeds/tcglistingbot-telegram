"""Listing handler registrations for TCG Listing Bot."""

from __future__ import annotations

import asyncio
import logging

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
from utils.formatters import format_fixed_price_listing

logger = logging.getLogger(__name__)

GAME, TITLE, PRICE, NOTES, CONFIRM = range(5)
SUPPORTED_GAMES = {'pokemon', 'onepiece'}


def _listing_preview(*, game: str, title: str, price_sgd: float, notes: str) -> str:
    """Build a compact listing preview for seller confirmation."""

    notes_text = notes if notes else 'No extra notes'
    return (
        '<b>Listing Preview</b>\n\n'
        f'Game: <code>{game}</code>\n'
        f'Title: <code>{title}</code>\n'
        f'Price: <code>SGD {price_sgd:.2f}</code>\n'
        f'Notes: <code>{notes_text}</code>\n\n'
        'Reply with <code>post</code> to publish or <code>cancel</code> to stop.'
    )


async def list_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the manual listing flow for a seller with completed setup."""

    if update.effective_message is None or update.effective_user is None:
        return ConversationHandler.END

    seller = await asyncio.to_thread(get_seller_by_telegram_id, update.effective_user.id)
    if seller is None:
        await update.effective_message.reply_text(
            'Please use /start first so I can create your seller account.',
            parse_mode='HTML',
        )
        return ConversationHandler.END

    seller_config = await asyncio.to_thread(get_seller_config_by_seller_id, seller['id'])
    if seller_config is None or not seller_config.get('setup_complete'):
        await update.effective_message.reply_text(
            'Please complete /setup before posting a listing.',
            parse_mode='HTML',
        )
        return ConversationHandler.END

    channel_name = seller_config.get('primary_channel_name')
    if not channel_name:
        await update.effective_message.reply_text(
            'No primary channel is configured yet. Run /setup again first.',
            parse_mode='HTML',
        )
        return ConversationHandler.END

    context.user_data['listing_seller_id'] = seller['id']
    context.user_data['listing_seller_config'] = seller_config
    await update.effective_message.reply_text(
        'What game is this listing for? Reply with <code>pokemon</code> or <code>onepiece</code>.',
        parse_mode='HTML',
        reply_markup=ReplyKeyboardRemove(),
    )
    return GAME


async def capture_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Capture the game for the listing and continue to the title step."""

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
    await update.effective_message.reply_text(
        'Enter the listing title. Example: <code>Espeon Master Ball PSA 10</code>.',
        parse_mode='HTML',
    )
    return TITLE


async def capture_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Capture the listing title and continue to price collection."""

    if update.effective_message is None or update.effective_message.text is None:
        return TITLE

    context.user_data['listing_title'] = update.effective_message.text.strip()
    await update.effective_message.reply_text(
        'Enter the price in SGD. Example: <code>25</code> or <code>25.50</code>.',
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
            game=context.user_data['listing_game'],
            title=context.user_data['listing_title'],
            price_sgd=context.user_data['listing_price_sgd'],
            notes=notes,
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
        context.user_data.clear()
        return ConversationHandler.END

    if decision != 'post':
        await update.effective_message.reply_text(
            'Reply with <code>post</code> to publish or <code>cancel</code> to stop.',
            parse_mode='HTML',
        )
        return CONFIRM

    seller_config = context.user_data['listing_seller_config']
    listing_text = format_fixed_price_listing(
        card_name=context.user_data['listing_title'],
        game=context.user_data['listing_game'],
        price_sgd=context.user_data['listing_price_sgd'],
        condition_notes=context.user_data['listing_notes'],
        custom_description='',
        seller_display_name=seller_config.get('seller_display_name') or 'Seller',
        payment_methods=seller_config.get('payment_methods') or ['PayNow'],
    )
    sent_message = await context.bot.send_message(
        chat_id=seller_config['primary_channel_name'],
        text=listing_text,
        parse_mode='HTML',
    )
    listing = await asyncio.to_thread(
        create_listing,
        seller_id=context.user_data['listing_seller_id'],
        card_name=context.user_data['listing_title'],
        game=context.user_data['listing_game'],
        price_sgd=context.user_data['listing_price_sgd'],
        condition_notes=context.user_data['listing_notes'],
        custom_description='',
        posted_channel_id=sent_message.chat.id,
        posted_message_id=sent_message.message_id,
    )
    logger.info('Posted listing %s to channel %s.', listing['id'], sent_message.chat.id)
    await update.effective_message.reply_text(
        f'✅ Listing posted to <code>{seller_config["primary_channel_name"]}</code>.\n'
        f'Message ID: <code>{sent_message.message_id}</code>',
        parse_mode='HTML',
        reply_markup=ReplyKeyboardRemove(),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_listing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the listing conversation and clear temporary state."""

    if update.effective_message is not None:
        await update.effective_message.reply_text('Listing cancelled.', reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END


def register_listing_handlers(application: Application) -> None:
    """Register listing-related command handlers on the Telegram application."""

    conversation = ConversationHandler(
        entry_points=[CommandHandler('list', list_entry)],
        states={
            GAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, capture_game)],
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, capture_title)],
            PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, capture_price)],
            NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, capture_notes)],
            CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_listing)],
        },
        fallbacks=[CommandHandler('cancel', cancel_listing)],
        name='manual_listing',
        persistent=False,
    )
    application.add_handler(conversation)
