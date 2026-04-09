"""Setup handler registrations for TCG Listing Bot."""

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

from config import get_config
from db.seller_configs import ensure_seller_config, update_seller_setup
from db.sellers import get_seller_by_telegram_id, upsert_seller

logger = logging.getLogger(__name__)

DISPLAY_NAME, PAYNOW_IDENTIFIER, CONFIRM = range(3)


def _setup_summary(display_name: str, primary_channel: str, paynow_identifier: str) -> str:
    """Build the compact setup confirmation summary."""

    return (
        '<b>Setup Summary</b>\n\n'
        f'Display name: <code>{display_name}</code>\n'
        f'Primary channel: <code>{primary_channel}</code>\n'
        'Payment methods: <code>PayNow</code>\n'
        f'PayNow identifier: <code>{paynow_identifier}</code>\n\n'
        'Reply with <code>confirm</code> to save, or <code>cancel</code> to stop.'
    )


async def setup_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the minimal seller setup flow and ensure seller records exist."""

    if update.effective_message is None or update.effective_user is None:
        return ConversationHandler.END

    user = update.effective_user
    seller = await asyncio.to_thread(
        upsert_seller,
        telegram_id=user.id,
        telegram_username=user.username,
        telegram_display_name=user.full_name,
    )
    await asyncio.to_thread(
        ensure_seller_config,
        seller_id=seller['id'],
        primary_channel_name=get_config().primary_channel_username or None,
    )

    context.user_data['setup_seller_id'] = seller['id']
    context.user_data['setup_primary_channel_name'] = (
        get_config().primary_channel_username or '@yourchannel'
    )

    await update.effective_message.reply_text(
        'Let\'s set up your seller profile.\n\nWhat display name should appear on your listings?',
        parse_mode='HTML',
        reply_markup=ReplyKeyboardRemove(),
    )
    return DISPLAY_NAME


async def capture_display_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the seller display name and ask for PayNow details."""

    if update.effective_message is None or update.effective_message.text is None:
        return DISPLAY_NAME

    context.user_data['setup_display_name'] = update.effective_message.text.strip()
    await update.effective_message.reply_text(
        'Enter your PayNow identifier.\nExamples: phone number, mobile number, or UEN.',
        parse_mode='HTML',
    )
    return PAYNOW_IDENTIFIER


async def capture_paynow_identifier(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the PayNow identifier and ask for confirmation."""

    if update.effective_message is None or update.effective_message.text is None:
        return PAYNOW_IDENTIFIER

    paynow_identifier = update.effective_message.text.strip()
    context.user_data['setup_paynow_identifier'] = paynow_identifier
    await update.effective_message.reply_text(
        _setup_summary(
            context.user_data['setup_display_name'],
            context.user_data['setup_primary_channel_name'],
            paynow_identifier,
        ),
        parse_mode='HTML',
    )
    return CONFIRM


async def confirm_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Persist the setup when the seller confirms the captured details."""

    if update.effective_message is None or update.effective_message.text is None:
        return CONFIRM

    text = update.effective_message.text.strip().lower()
    if text == 'cancel':
        await update.effective_message.reply_text('Setup cancelled.', parse_mode='HTML')
        return ConversationHandler.END

    if text != 'confirm':
        await update.effective_message.reply_text(
            'Reply with <code>confirm</code> to save or <code>cancel</code> to stop.',
            parse_mode='HTML',
        )
        return CONFIRM

    await asyncio.to_thread(
        update_seller_setup,
        seller_id=context.user_data['setup_seller_id'],
        seller_display_name=context.user_data['setup_display_name'],
        primary_channel_name=context.user_data['setup_primary_channel_name'],
        payment_methods=['PayNow'],
        paynow_identifier=context.user_data['setup_paynow_identifier'],
        setup_complete=True,
    )
    logger.info('Seller %s completed setup.', context.user_data['setup_seller_id'])
    await update.effective_message.reply_text(
        '✅ Seller setup saved.\n\nNext: add the bot as admin in your posting channel and linked discussion flow, then we can build listing posting and claim handling on top.',
        parse_mode='HTML',
        reply_markup=ReplyKeyboardRemove(),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the setup conversation cleanly."""

    if update.effective_message is not None:
        await update.effective_message.reply_text('Setup cancelled.', reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END


def register_setup_handlers(application: Application) -> None:
    """Register setup-related command handlers on the Telegram application."""

    conversation = ConversationHandler(
        entry_points=[CommandHandler('setup', setup_entry)],
        states={
            DISPLAY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, capture_display_name)],
            PAYNOW_IDENTIFIER: [MessageHandler(filters.TEXT & ~filters.COMMAND, capture_paynow_identifier)],
            CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_setup)],
        },
        fallbacks=[CommandHandler('cancel', cancel_setup)],
        name='seller_setup',
        persistent=False,
    )
    application.add_handler(conversation)
