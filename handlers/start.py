"""Start and help handlers for TCG Listing Bot."""

from __future__ import annotations

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import get_config


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respond to `/start` with the primary onboarding message."""

    if update.effective_message is None:
        return

    config = get_config()
    message = (
        f"👋 <b>Welcome to {config.bot_brand_name}</b>\n\n"
        "I help trading card sellers create listings, manage claims, and track transactions on "
        "Telegram.\n\n"
        f"Bot: <code>{config.telegram_bot_username}</code>\n"
        "Use <code>/setup</code> to begin seller configuration."
    )
    await update.effective_message.reply_text(message, parse_mode="HTML")


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
        "<code>/list</code> — start a listing"
    )
    await update.effective_message.reply_text(message, parse_mode="HTML")


def register_start_handlers(application: Application) -> None:
    """Register core startup handlers on the Telegram application."""

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
