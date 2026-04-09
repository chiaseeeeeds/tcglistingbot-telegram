"""Telegram bot entrypoint for TCG Listing Bot."""

from __future__ import annotations

import logging
from typing import Iterable

from telegram.ext import Application, ApplicationBuilder

from config import get_config
from handlers.admin import register_admin_handlers
from handlers.auctions import register_auction_handlers
from handlers.claims import register_claim_handlers
from handlers.listing import register_listing_handlers
from handlers.seller_tools import register_seller_tool_handlers
from handlers.setup import register_setup_handlers
from handlers.start import register_start_handlers
from handlers.transactions import register_transaction_handlers


def configure_logging() -> None:
    """Configure process-wide logging for the bot runtime."""

    config = get_config()
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def register_handlers(application: Application) -> None:
    """Register all currently scaffolded Telegram handlers."""

    registrars: Iterable = (
        register_start_handlers,
        register_setup_handlers,
        register_listing_handlers,
        register_claim_handlers,
        register_auction_handlers,
        register_transaction_handlers,
        register_seller_tool_handlers,
        register_admin_handlers,
    )
    for registrar in registrars:
        registrar(application)


def build_application() -> Application:
    """Build the Telegram application and attach handlers."""

    config = get_config()
    application = ApplicationBuilder().token(config.telegram_bot_token).build()
    register_handlers(application)
    return application


def main() -> None:
    """Run the bot using webhook mode when configured, otherwise polling."""

    config = get_config()
    application = build_application()

    if config.telegram_webhook_url:
        application.run_webhook(
            listen="0.0.0.0",
            port=8443,
            webhook_url=config.telegram_webhook_url,
            allowed_updates=None,
        )
        return

    application.run_polling(allowed_updates=None)


if __name__ == "__main__":
    configure_logging()
    main()
