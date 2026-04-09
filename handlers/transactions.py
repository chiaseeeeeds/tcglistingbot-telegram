"""Transaction handler registrations for TCG Listing Bot."""

from __future__ import annotations

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


async def transactions_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respond with the current scaffold status for transaction tools."""

    if update.effective_message is None:
        return
    await update.effective_message.reply_text(
        "Transaction history and SOLD lifecycle tools are scaffolded for implementation.",
        parse_mode="HTML",
    )


def register_transaction_handlers(application: Application) -> None:
    """Register transaction-related command handlers on the Telegram application."""

    application.add_handler(CommandHandler("sold", transactions_placeholder))
