"""Auction handler registrations for TCG Listing Bot."""

from __future__ import annotations

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


async def auctions_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respond with the current scaffold status for auctions."""

    if update.effective_message is None:
        return
    await update.effective_message.reply_text(
        "Auction flows are scaffolded and ready for bid parsing and closeout logic.",
        parse_mode="HTML",
    )


def register_auction_handlers(application: Application) -> None:
    """Register auction-related command handlers on the Telegram application."""

    application.add_handler(CommandHandler("auction", auctions_placeholder))
