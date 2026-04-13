"""Helpers for editing bot-posted listing messages across Telegram channels."""

from __future__ import annotations

import asyncio
import logging

from telegram.ext import Application

from db.listing_channels import get_listing_channels_for_listing

logger = logging.getLogger(__name__)


async def edit_listing_messages(
    *,
    application: Application,
    listing: dict,
    text: str,
) -> None:
    """Edit the primary and cross-posted Telegram messages for a listing."""

    channel_targets: list[tuple[int, int]] = []
    if listing.get('posted_channel_id') and listing.get('posted_message_id'):
        channel_targets.append((int(listing['posted_channel_id']), int(listing['posted_message_id'])))

    listing_channels = await asyncio.to_thread(get_listing_channels_for_listing, str(listing['id']))
    for listing_channel in listing_channels:
        channel_id = listing_channel.get('channel_id')
        message_id = listing_channel.get('message_id')
        if channel_id and message_id:
            target = (int(channel_id), int(message_id))
            if target not in channel_targets:
                channel_targets.append(target)

    for chat_id, message_id in channel_targets:
        try:
            await application.bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=text,
                parse_mode='HTML',
            )
            continue
        except Exception as caption_exc:
            logger.info(
                'Caption edit fallback for listing chat=%s message=%s: %s',
                chat_id,
                message_id,
                caption_exc,
            )
        try:
            await application.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode='HTML',
            )
        except Exception as text_exc:
            logger.warning(
                'Could not edit listing message for chat=%s message=%s: %s',
                chat_id,
                message_id,
                text_exc,
            )
