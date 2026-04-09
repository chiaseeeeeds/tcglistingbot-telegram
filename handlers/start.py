"""Start and help handlers for TCG Listing Bot."""

from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import get_config
from db.seller_configs import ensure_seller_config
from db.sellers import upsert_seller

logger = logging.getLogger(__name__)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Create or refresh the seller account and show the correct home message."""

    if update.effective_message is None or update.effective_user is None:
        return

    user = update.effective_user
    seller = await asyncio.to_thread(
        upsert_seller,
        telegram_id=user.id,
        telegram_username=user.username,
        telegram_display_name=user.full_name,
    )
    seller_config = await asyncio.to_thread(
        ensure_seller_config,
        seller_id=seller['id'],
        primary_channel_name=get_config().primary_channel_username or None,
    )

    config = get_config()
    if seller_config.get('setup_complete'):
        message = (
            f"Welcome back to <b>{config.bot_brand_name}</b> ✅\n\n"
            f"Bot: <code>{config.telegram_bot_username}</code>\n"
            f"Primary channel: <code>{seller_config.get('primary_channel_name') or 'Not set'}</code>\n\n"
            "Use <code>/list</code> to start a listing, <code>/stats</code> for seller tools, or <code>/ping</code> for a quick health check."
        )
    else:
        message = (
            f"👋 <b>Welcome to {config.bot_brand_name}</b>\n\n"
            "I help trading card sellers create listings, manage claims, and track transactions on "
            "Telegram.\n\n"
            f"Bot: <code>{config.telegram_bot_username}</code>\n"
            "Your account is ready, but seller setup is not complete yet.\n"
            "Use <code>/setup</code> to finish the first configuration."
        )
    logger.info('Seller %s started the bot.', user.id)
    await update.effective_message.reply_text(message, parse_mode='HTML')


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respond to `/help` with the current command summary."""

    if update.effective_message is None:
        return

    config = get_config()
    message = (
        f"<b>{config.bot_brand_name} Commands</b>\n\n"
        "<code>/start</code> — open the bot\n"
        "<code>/help</code> — show help\n"
        "<code>/setup</code> — configure seller profile\n"
        "<code>/list</code> — start a listing\n"
        "<code>/cancel</code> — cancel the current flow\n"
        "<code>/stats</code> — seller tools\n"
        "<code>/ping</code> — quick health check"
    )
    await update.effective_message.reply_text(message, parse_mode='HTML')


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return a tiny health-check response for live debugging."""

    if update.effective_message is None:
        return

    await update.effective_message.reply_text('🏓 Pong. Bot is online.', parse_mode='HTML')


def register_start_handlers(application: Application) -> None:
    """Register core startup handlers on the Telegram application."""

    application.add_handler(CommandHandler('start', start_command))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('ping', ping_command))
