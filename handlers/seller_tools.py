"""Seller utility handler registrations for TCG Listing Bot."""

from __future__ import annotations

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


async def seller_tools_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respond with the current scaffold status for seller utility commands."""

    if update.effective_message is None:
        return
    await update.effective_message.reply_text(
        "Seller tools are scaffolded for stats, blacklist, vacation mode, and evidence export.",
        parse_mode="HTML",
    )


def register_seller_tool_handlers(application: Application) -> None:
    """Register seller utility command handlers on the Telegram application."""

    application.add_handler(CommandHandler("stats", seller_tools_placeholder))
