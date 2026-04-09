"""Setup handler registrations for TCG Listing Bot."""

from __future__ import annotations

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


async def setup_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respond with the current scaffold status for seller setup."""

    if update.effective_message is None:
        return
    await update.effective_message.reply_text(
        "Seller setup is scaffolded and ready for the guided Telegram flow implementation.",
        parse_mode="HTML",
    )


def register_setup_handlers(application: Application) -> None:
    """Register setup-related command handlers on the Telegram application."""

    application.add_handler(CommandHandler("setup", setup_placeholder))
