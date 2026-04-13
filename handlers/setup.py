"""Setup handler registrations for TCG Listing Bot."""

from __future__ import annotations

import asyncio
import logging

from telegram import ChatMemberAdministrator, ChatMemberOwner, ReplyKeyboardRemove, Update
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
from db.sellers import upsert_seller
from utils.validators import is_digits_only, is_letters_and_spaces

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

    primary_channel_name = get_config().primary_channel_username or '@yourchannel'
    try:
        channel = await context.bot.get_chat(primary_channel_name)
        bot_user = await context.bot.get_me()
        bot_member = await context.bot.get_chat_member(channel.id, bot_user.id)
    except Exception as exc:
        logger.exception('Failed to verify channel access during setup: %s', exc)
        await update.effective_message.reply_text(
            'I could not verify channel access. Please confirm the bot is admin in the channel and try again.',
            parse_mode='HTML',
        )
        return ConversationHandler.END

    if not isinstance(bot_member, (ChatMemberAdministrator, ChatMemberOwner)):
        await update.effective_message.reply_text(
            'The bot is not an admin in the configured channel yet. Please fix that and try /setup again.',
            parse_mode='HTML',
        )
        return ConversationHandler.END

    if get_config().comments_via_discussion_group:
        linked_chat_id = getattr(channel, 'linked_chat_id', None)
        if linked_chat_id is None:
            await update.effective_message.reply_text(
                'This channel does not expose a linked discussion chat to the bot yet. Please confirm comments are enabled and try again.',
                parse_mode='HTML',
            )
            return ConversationHandler.END
        try:
            linked_chat = await context.bot.get_chat(linked_chat_id)
            linked_member = await context.bot.get_chat_member(linked_chat.id, bot_user.id)
        except Exception as exc:
            logger.exception('Failed to verify linked discussion access during setup: %s', exc)
            await update.effective_message.reply_text(
                'I found the linked discussion chat, but I could not verify bot access there. Please add the bot to the discussion group and try again.',
                parse_mode='HTML',
            )
            return ConversationHandler.END

        if getattr(linked_member, 'status', '') in {'left', 'kicked'}:
            await update.effective_message.reply_text(
                'The bot is not present in the linked discussion group yet. Please add it there and try /setup again.',
                parse_mode='HTML',
            )
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
        primary_channel_name=primary_channel_name,
        primary_channel_id=channel.id,
    )

    context.user_data['setup_seller_id'] = seller['id']
    context.user_data['setup_primary_channel_name'] = primary_channel_name
    context.user_data['setup_primary_channel_id'] = channel.id

    await update.effective_message.reply_text(
        'Channel access verified.\n\nLet\'s set up your seller profile. What display name should appear on your listings?',
        parse_mode='HTML',
        reply_markup=ReplyKeyboardRemove(),
    )
    return DISPLAY_NAME


async def capture_display_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the seller display name and ask for PayNow details."""

    if update.effective_message is None or update.effective_message.text is None:
        return DISPLAY_NAME

    display_name = update.effective_message.text.strip()
    if not is_letters_and_spaces(display_name):
        await update.effective_message.reply_text(
            'Display name must contain only letters and spaces.',
            parse_mode='HTML',
        )
        return DISPLAY_NAME

    context.user_data['setup_display_name'] = display_name
    await update.effective_message.reply_text(
        'Enter your PayNow identifier. Digits only.',
        parse_mode='HTML',
    )
    return PAYNOW_IDENTIFIER


async def capture_paynow_identifier(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the PayNow identifier and ask for confirmation."""

    if update.effective_message is None or update.effective_message.text is None:
        return PAYNOW_IDENTIFIER

    paynow_identifier = update.effective_message.text.strip()
    if not is_digits_only(paynow_identifier):
        await update.effective_message.reply_text(
            'PayNow identifier must contain only numbers.',
            parse_mode='HTML',
        )
        return PAYNOW_IDENTIFIER

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
        primary_channel_id=context.user_data['setup_primary_channel_id'],
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
        allow_reentry=True,
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
