"""Telegram bot entrypoint for TCG Listing Bot."""

from __future__ import annotations

import atexit
import fcntl
import logging
from pathlib import Path
from typing import IO, Iterable

from telegram import BotCommand
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

LOCK_HANDLE: IO[str] | None = None
ALLOWED_UPDATES = [
    'message',
    'edited_message',
    'channel_post',
    'edited_channel_post',
    'callback_query',
]


def configure_logging() -> None:
    """Configure process-wide logging for the bot runtime."""

    config = get_config()
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format='%(asctime)s %(levelname)s %(name)s %(message)s',
    )
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    logging.getLogger('telegram.vendor.ptb_urllib3.urllib3').setLevel(logging.WARNING)


def acquire_single_instance_lock() -> None:
    """Prevent multiple polling bot instances from running at the same time."""

    global LOCK_HANDLE
    lock_path = Path('.logs/bot.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = lock_path.open('w')
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise SystemExit(
            'Another TCG Listing Bot process is already running. Stop it before starting a new one.'
        ) from exc

    lock_handle.write(str(Path.cwd()))
    lock_handle.flush()
    LOCK_HANDLE = lock_handle
    atexit.register(release_single_instance_lock)


def release_single_instance_lock() -> None:
    """Release the polling singleton lock when the process exits."""

    global LOCK_HANDLE
    if LOCK_HANDLE is None:
        return
    try:
        fcntl.flock(LOCK_HANDLE.fileno(), fcntl.LOCK_UN)
    finally:
        LOCK_HANDLE.close()
        LOCK_HANDLE = None


async def post_init(application: Application) -> None:
    """Register visible Telegram commands and log startup identity."""

    config = get_config()
    await application.bot.set_my_commands(
        [
            BotCommand('start', 'Open the bot home'),
            BotCommand('help', 'Show available commands'),
            BotCommand('setup', 'Configure seller profile'),
            BotCommand('list', 'Start a new listing'),
            BotCommand('cancel', 'Cancel current flow'),
            BotCommand('stats', 'Open seller tools'),
            BotCommand('ping', 'Quick bot health check'),
        ]
    )
    me = await application.bot.get_me()
    logging.getLogger(__name__).info(
        'Bot ready as @%s (%s) in %s mode.',
        me.username,
        me.id,
        'webhook' if config.telegram_webhook_url else 'polling',
    )


async def error_handler(update: object, context) -> None:
    """Log uncaught Telegram handler exceptions with context."""

    logging.getLogger(__name__).exception(
        'Unhandled bot exception. update=%r error=%s',
        update,
        context.error,
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
    application.add_error_handler(error_handler)


def build_application() -> Application:
    """Build the Telegram application and attach handlers."""

    config = get_config()
    application = ApplicationBuilder().token(config.telegram_bot_token).post_init(post_init).build()
    register_handlers(application)
    return application


def main() -> None:
    """Run the bot using webhook mode when configured, otherwise polling."""

    config = get_config()
    acquire_single_instance_lock()
    application = build_application()

    logging.getLogger(__name__).info('Starting bot process.')
    if config.telegram_webhook_url:
        application.run_webhook(
            listen='0.0.0.0',
            port=8443,
            webhook_url=config.telegram_webhook_url,
            allowed_updates=ALLOWED_UPDATES,
            drop_pending_updates=True,
        )
        return

    application.run_polling(
        allowed_updates=ALLOWED_UPDATES,
        drop_pending_updates=True,
    )


if __name__ == '__main__':
    configure_logging()
    main()
