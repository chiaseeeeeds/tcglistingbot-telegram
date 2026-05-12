"""Background jobs for refreshing and closing auction listing messages."""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import Application

from config import get_config
from db.claims import close_auction_atomic
from db.claims import mark_payment_prompt_sent
from db.idempotency import register_processed_event
from db.listings import get_live_auction_listings
from db.seller_configs import get_seller_config_by_seller_id
from db.sellers import get_seller_by_id
from services.listing_message_editor import edit_listing_messages
from services.payment_requests import (
    build_buyer_payment_message,
    ensure_payment_request_for_claim,
)
from utils.auction_settings import resolve_listing_payment_deadline_hours
from utils.formatters import auction_refresh_marker, format_auction_listing

logger = logging.getLogger(__name__)
AUCTION_REFRESH_JOB_ID = 'auction-refresh-worker'


async def _notify_auction_award(
    *,
    application: Application,
    listing: dict,
    winning_claim: dict,
    seller: dict | None,
    seller_config: dict | None,
    payment_deadline_hours: int,
) -> None:
    winning_claim = await asyncio.to_thread(ensure_payment_request_for_claim, claim=winning_claim)
    buyer_telegram_id = winning_claim.get('buyer_telegram_id')

    if buyer_telegram_id:
        buyer_message = build_buyer_payment_message(
            listing=listing,
            claim=winning_claim,
            seller_config=seller_config,
            deadline_hours=payment_deadline_hours,
            intro='You won the auction.',
        )
        try:
            dm_message = await application.bot.send_message(
                chat_id=int(buyer_telegram_id),
                text=buyer_message,
                parse_mode='HTML',
            )
            await asyncio.to_thread(
                mark_payment_prompt_sent,
                claim_id=str(winning_claim['id']),
                message_id=dm_message.message_id,
            )
        except Exception as exc:
            logger.info('Could not DM auction winner %s: %s', buyer_telegram_id, exc)

    if seller is not None:
        seller_message = (
            '<b>Auction ended with a winner.</b>\n\n'
            f'Item: <code>{listing.get("card_name")}</code>\n'
            f'Winner: <code>{winning_claim.get("buyer_display_name") or winning_claim.get("buyer_telegram_id")}</code>\n'
            f'Winning bid: <code>SGD {float(listing.get("price_sgd") or listing.get("current_bid_sgd") or 0):.2f}</code>\n'
            f'Reference: <code>{winning_claim.get("payment_reference")}</code>\n'
            f'Payment deadline: <code>{payment_deadline_hours}h</code>'
        )
        try:
            await application.bot.send_message(
                chat_id=int(seller['telegram_id']),
                text=seller_message,
                parse_mode='HTML',
            )
        except Exception as exc:
            logger.info('Could not DM seller %s about awarded auction: %s', seller.get('telegram_id'), exc)


async def _notify_auction_closed_without_bids(
    *,
    application: Application,
    listing: dict,
    seller: dict | None,
) -> None:
    if seller is None:
        return
    try:
        await application.bot.send_message(
            chat_id=int(seller['telegram_id']),
            text=(
                '<b>Auction ended with no bids.</b>\n\n'
                f'Item: <code>{listing.get("card_name")}</code>\n'
                'The Telegram post has been updated.'
            ),
            parse_mode='HTML',
        )
    except Exception as exc:
        logger.info('Could not DM seller %s about bidless auction close: %s', seller.get('telegram_id'), exc)


async def refresh_auction_listing_messages(application: Application) -> None:
    """Refresh visible auction listing messages as time-left buckets change."""

    listings = await asyncio.to_thread(get_live_auction_listings)
    if not listings:
        logger.debug('Auction refresh worker found no live auctions.')
        return

    config = get_config()
    for listing in listings:
        seller_config = await asyncio.to_thread(get_seller_config_by_seller_id, str(listing['seller_id']))
        seller = await asyncio.to_thread(get_seller_by_id, str(listing['seller_id']))
        marker = auction_refresh_marker(listing.get('auction_end_time'))
        if marker == 'closed':
            first_seen = await asyncio.to_thread(
                register_processed_event,
                source='auction_refresh',
                event_key=f'auction-close:{listing["id"]}',
                metadata={'listing_id': str(listing['id'])},
            )
            if not first_seen:
                continue

            deadline_hours = resolve_listing_payment_deadline_hours(
                listing=listing,
                seller_config=seller_config,
                default_hours=config.default_payment_deadline_hours,
            )
            result = await close_auction_atomic(
                listing_id=str(listing['id']),
                payment_deadline_hours=deadline_hours,
            )
            action = str(result.get('action') or 'noop')
            latest_listing = result.get('listing') or listing

            if action == 'awarded':
                winning_claim = result.get('winning_claim') or {}
                text = format_auction_listing(
                    card_name=str(latest_listing.get('card_name') or 'Card'),
                    game=str(latest_listing.get('game') or 'pokemon'),
                    starting_bid_sgd=float(latest_listing.get('starting_bid_sgd') or 0),
                    current_bid_sgd=(
                        float(latest_listing.get('current_bid_sgd')) if latest_listing.get('current_bid_sgd') is not None else None
                    ),
                    bid_increment_sgd=(
                        float(latest_listing.get('bid_increment_sgd')) if latest_listing.get('bid_increment_sgd') is not None else None
                    ),
                    anti_snipe_minutes=(
                        int(latest_listing.get('anti_snipe_minutes')) if latest_listing.get('anti_snipe_minutes') is not None else None
                    ),
                    reserve_price_sgd=(
                        float(latest_listing.get('reserve_price_sgd')) if latest_listing.get('reserve_price_sgd') is not None else None
                    ),
                    payment_deadline_hours=resolve_listing_payment_deadline_hours(
                        listing=latest_listing,
                        seller_config=seller_config,
                        default_hours=config.default_payment_deadline_hours,
                    ),
                    condition_notes=str(latest_listing.get('condition_notes') or ''),
                    custom_description=str(latest_listing.get('custom_description') or ''),
                    seller_display_name=(seller_config or {}).get('seller_display_name') or 'Seller',
                    auction_end_time=latest_listing.get('auction_end_time'),
                    status='auction_closed',
                )
                await edit_listing_messages(application=application, listing=latest_listing, text=text)
                await _notify_auction_award(
                    application=application,
                    listing=latest_listing,
                    winning_claim=winning_claim,
                    seller=seller,
                    seller_config=seller_config,
                    payment_deadline_hours=deadline_hours,
                )
                logger.info('Closed auction listing %s with winner %s.', latest_listing.get('id'), winning_claim.get('id'))
                continue

            if action == 'closed_without_bids':
                text = format_auction_listing(
                    card_name=str(latest_listing.get('card_name') or 'Card'),
                    game=str(latest_listing.get('game') or 'pokemon'),
                    starting_bid_sgd=float(latest_listing.get('starting_bid_sgd') or 0),
                    current_bid_sgd=(
                        float(latest_listing.get('current_bid_sgd')) if latest_listing.get('current_bid_sgd') is not None else None
                    ),
                    bid_increment_sgd=(
                        float(latest_listing.get('bid_increment_sgd')) if latest_listing.get('bid_increment_sgd') is not None else None
                    ),
                    anti_snipe_minutes=(
                        int(latest_listing.get('anti_snipe_minutes')) if latest_listing.get('anti_snipe_minutes') is not None else None
                    ),
                    reserve_price_sgd=(
                        float(latest_listing.get('reserve_price_sgd')) if latest_listing.get('reserve_price_sgd') is not None else None
                    ),
                    payment_deadline_hours=resolve_listing_payment_deadline_hours(
                        listing=latest_listing,
                        seller_config=seller_config,
                        default_hours=config.default_payment_deadline_hours,
                    ),
                    condition_notes=str(latest_listing.get('condition_notes') or ''),
                    custom_description=str(latest_listing.get('custom_description') or ''),
                    seller_display_name=(seller_config or {}).get('seller_display_name') or 'Seller',
                    auction_end_time=latest_listing.get('auction_end_time'),
                    status='auction_closed',
                )
                await edit_listing_messages(application=application, listing=latest_listing, text=text)
                await _notify_auction_closed_without_bids(
                    application=application,
                    listing=latest_listing,
                    seller=seller,
                )
                logger.info('Closed auction listing %s without bids.', latest_listing.get('id'))
                continue

            if action == 'reserve_not_met':
                highest_bid_claim = result.get('highest_bid_claim') or {}
                text = format_auction_listing(
                    card_name=str(latest_listing.get('card_name') or 'Card'),
                    game=str(latest_listing.get('game') or 'pokemon'),
                    starting_bid_sgd=float(latest_listing.get('starting_bid_sgd') or 0),
                    current_bid_sgd=(
                        float(latest_listing.get('current_bid_sgd')) if latest_listing.get('current_bid_sgd') is not None else None
                    ),
                    bid_increment_sgd=(
                        float(latest_listing.get('bid_increment_sgd')) if latest_listing.get('bid_increment_sgd') is not None else None
                    ),
                    anti_snipe_minutes=(
                        int(latest_listing.get('anti_snipe_minutes')) if latest_listing.get('anti_snipe_minutes') is not None else None
                    ),
                    reserve_price_sgd=(
                        float(latest_listing.get('reserve_price_sgd')) if latest_listing.get('reserve_price_sgd') is not None else None
                    ),
                    payment_deadline_hours=resolve_listing_payment_deadline_hours(
                        listing=latest_listing,
                        seller_config=seller_config,
                        default_hours=config.default_payment_deadline_hours,
                    ),
                    condition_notes=str(latest_listing.get('condition_notes') or ''),
                    custom_description=str(latest_listing.get('custom_description') or ''),
                    seller_display_name=(seller_config or {}).get('seller_display_name') or 'Seller',
                    auction_end_time=latest_listing.get('auction_end_time'),
                    status='auction_reserve_not_met',
                )
                await edit_listing_messages(application=application, listing=latest_listing, text=text)
                await _notify_auction_reserve_not_met(
                    application=application,
                    listing=latest_listing,
                    highest_bid_claim=highest_bid_claim,
                    seller=seller,
                )
                logger.info('Closed auction listing %s without winner because reserve was not met.', latest_listing.get('id'))
                continue

            logger.info(
                'Auction close worker saw noop for listing %s: %s',
                listing.get('id'),
                result.get('reason'),
            )
            continue

        first_seen = await asyncio.to_thread(
            register_processed_event,
            source='auction_refresh',
            event_key=f'auction-refresh:{listing["id"]}:{marker}',
            metadata={'listing_id': str(listing['id']), 'marker': marker},
        )
        if not first_seen:
            continue

        text = format_auction_listing(
            card_name=str(listing.get('card_name') or 'Card'),
            game=str(listing.get('game') or 'pokemon'),
            starting_bid_sgd=float(listing.get('starting_bid_sgd') or 0),
            current_bid_sgd=(float(listing.get('current_bid_sgd')) if listing.get('current_bid_sgd') is not None else None),
            bid_increment_sgd=(float(listing.get('bid_increment_sgd')) if listing.get('bid_increment_sgd') is not None else None),
            anti_snipe_minutes=(int(listing.get('anti_snipe_minutes')) if listing.get('anti_snipe_minutes') is not None else None),
            reserve_price_sgd=(float(listing.get('reserve_price_sgd')) if listing.get('reserve_price_sgd') is not None else None),
            payment_deadline_hours=resolve_listing_payment_deadline_hours(
                listing=listing,
                seller_config=seller_config,
                default_hours=config.default_payment_deadline_hours,
            ),
            condition_notes=str(listing.get('condition_notes') or ''),
            custom_description=str(listing.get('custom_description') or ''),
            seller_display_name=(seller_config or {}).get('seller_display_name') or 'Seller',
            auction_end_time=listing.get('auction_end_time'),
            status='auction_active',
        )
        await edit_listing_messages(application=application, listing=listing, text=text)
        logger.info('Refreshed auction listing %s for marker %s.', listing.get('id'), marker)



def register_auction_jobs(application: Application, scheduler: AsyncIOScheduler) -> None:
    """Register recurring auction refresh jobs on the shared scheduler."""

    scheduler.add_job(
        refresh_auction_listing_messages,
        'interval',
        minutes=1,
        id=AUCTION_REFRESH_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        kwargs={'application': application},
    )
