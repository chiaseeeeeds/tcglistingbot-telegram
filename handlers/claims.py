"""Claim handler registrations for TCG Listing Bot."""

from __future__ import annotations

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


async def claims_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respond with the current scaffold status for claim operations."""

    if update.effective_message is None:
        return
    await update.effective_message.reply_text(
        "Claim management is scaffolded and will be driven by Telegram comment monitoring.",
        parse_mode="HTML",
    )


def register_claim_handlers(application: Application) -> None:
    """Register claim-related command handlers on the Telegram application."""

    application.add_handler(CommandHandler("claims", claims_placeholder))
