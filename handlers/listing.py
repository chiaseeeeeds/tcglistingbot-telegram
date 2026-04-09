"""Listing handler registrations for TCG Listing Bot."""

from __future__ import annotations

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


async def listing_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respond with the current scaffold status for listing creation."""

    if update.effective_message is None:
        return
    await update.effective_message.reply_text(
        "Listing creation is scaffolded and ready for OCR, pricing, preview, and posting flows.",
        parse_mode="HTML",
    )


def register_listing_handlers(application: Application) -> None:
    """Register listing-related command handlers on the Telegram application."""

    application.add_handler(CommandHandler("list", listing_placeholder))
