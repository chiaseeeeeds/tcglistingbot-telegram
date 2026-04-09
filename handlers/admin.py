"""Admin handler registrations for TCG Listing Bot."""

from __future__ import annotations

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


async def admin_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respond with the current scaffold status for admin-only commands."""

    if update.effective_message is None:
        return
    await update.effective_message.reply_text(
        "Admin tools are scaffolded and can be expanded once operational needs are defined.",
        parse_mode="HTML",
    )


def register_admin_handlers(application: Application) -> None:
    """Register admin-related command handlers on the Telegram application."""

    application.add_handler(CommandHandler("admin", admin_placeholder))
