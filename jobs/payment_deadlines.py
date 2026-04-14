"""Background jobs for expired payment deadlines and claim queue advancement."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import Application

from config import get_config
from db.claims import advance_claim_queue, get_due_payment_claims, mark_payment_prompt_sent
from db.listings import get_listing_by_id
from db.seller_configs import get_seller_config_by_seller_id
from db.sellers import get_seller_by_id
from services.payment_requests import (
    build_buyer_payment_message,
    ensure_payment_request_for_claim,
    paynow_text,
)

logger = logging.getLogger(__name__)
PAYMENT_DEADLINE_JOB_ID = 'payment-deadline-worker'

async def _notify_queue_promoted(
    *,
    application: Application,
    listing: dict[str, Any],
    seller: dict[str, Any] | None,
    seller_config: dict[str, Any] | None,
    promoted_claim: dict[str, Any],
    failed_claim: dict[str, Any],
    payment_deadline_hours: int,
) -> None:
    promoted_claim = await asyncio.to_thread(ensure_payment_request_for_claim, claim=promoted_claim)
    buyer_telegram_id = promoted_claim.get('buyer_telegram_id')
    if buyer_telegram_id:
        buyer_message = build_buyer_payment_message(
            listing=listing,
            claim=promoted_claim,
            seller_config=seller_config,
            deadline_hours=payment_deadline_hours,
            intro='You are now first in line for this listing.',
        )
        try:
            dm_message = await application.bot.send_message(
                chat_id=int(buyer_telegram_id),
                text=buyer_message,
                parse_mode='HTML',
            )
            await asyncio.to_thread(
                mark_payment_prompt_sent,
                claim_id=str(promoted_claim['id']),
                message_id=dm_message.message_id,
            )
        except Exception as exc:
            logger.info('Could not DM promoted buyer %s: %s', buyer_telegram_id, exc)

    if seller is not None:
        seller_message = (
            '<b>Payment deadline expired.</b>\n\n'
            f'Item: <code>{listing.get("card_name")}</code>\n'
            f'Expired buyer: <code>{failed_claim.get("buyer_display_name") or failed_claim.get("buyer_telegram_id")}</code>\n'
            f'Promoted buyer: <code>{promoted_claim.get("buyer_display_name") or promoted_claim.get("buyer_telegram_id")}</code>\n'
            f'Reference: <code>{promoted_claim.get("payment_reference")}</code>\n'
            f'{paynow_text(seller_config)}'
            f'New payment deadline: <code>{payment_deadline_hours}h</code>'
        )
        try:
            await application.bot.send_message(
                chat_id=int(seller['telegram_id']),
                text=seller_message,
                parse_mode='HTML',
            )
        except Exception as exc:
            logger.info('Could not DM seller %s about queue advancement: %s', seller.get('telegram_id'), exc)


async def _notify_listing_reactivated(
    *,
    application: Application,
    listing: dict[str, Any],
    seller: dict[str, Any] | None,
    failed_claim: dict[str, Any],
) -> None:
    if seller is None:
        return
    seller_message = (
        '<b>Payment deadline expired.</b>\n\n'
        f'Item: <code>{listing.get("card_name")}</code>\n'
        f'Expired buyer: <code>{failed_claim.get("buyer_display_name") or failed_claim.get("buyer_telegram_id")}</code>\n'
        'No queued buyers remained, so the listing is active again.'
    )
    try:
        await application.bot.send_message(
            chat_id=int(seller['telegram_id']),
            text=seller_message,
            parse_mode='HTML',
        )
    except Exception as exc:
        logger.info('Could not DM seller %s about listing reactivation: %s', seller.get('telegram_id'), exc)


async def run_payment_deadline_cycle(application: Application) -> None:
    """Expire overdue payment claims and promote the next queued buyer when present."""

    due_claims = await asyncio.to_thread(get_due_payment_claims)
    if not due_claims:
        logger.debug('Payment deadline worker found no due claims.')
        return

    logger.info('Payment deadline worker processing %s due claim(s).', len(due_claims))
    config = get_config()
    for due_claim in due_claims:
        listing = await asyncio.to_thread(get_listing_by_id, str(due_claim['listing_id']))
        if listing is None:
            logger.warning('Skipping due claim %s because listing %s was not found.', due_claim.get('id'), due_claim.get('listing_id'))
            continue

        seller = await asyncio.to_thread(get_seller_by_id, str(listing['seller_id']))
        seller_config = await asyncio.to_thread(get_seller_config_by_seller_id, str(listing['seller_id']))
        payment_deadline_hours = int(
            (seller_config or {}).get('payment_deadline_hours') or config.default_payment_deadline_hours
        )

        try:
            result = await advance_claim_queue(
                claim_id=str(due_claim['id']),
                payment_deadline_hours=payment_deadline_hours,
            )
        except Exception as exc:
            logger.exception('Payment deadline worker failed to advance claim %s: %s', due_claim.get('id'), exc)
            continue

        action = str(result.get('action') or 'noop')
        failed_claim = result.get('failed_claim') or due_claim
        if action == 'promoted':
            promoted_claim = result.get('promoted_claim') or {}
            logger.info(
                'Advanced claim queue for listing %s. failed_claim=%s promoted_claim=%s',
                listing.get('id'),
                failed_claim.get('id'),
                promoted_claim.get('id'),
            )
            await _notify_queue_promoted(
                application=application,
                listing=listing,
                seller=seller,
                seller_config=seller_config,
                promoted_claim=promoted_claim,
                failed_claim=failed_claim,
                payment_deadline_hours=payment_deadline_hours,
            )
            continue

        if action == 'reactivated':
            logger.info(
                'Reactivated listing %s after expired claim %s with no queued buyer.',
                listing.get('id'),
                failed_claim.get('id'),
            )
            await _notify_listing_reactivated(
                application=application,
                listing=listing,
                seller=seller,
                failed_claim=failed_claim,
            )
            continue

        logger.info(
            'Payment deadline worker saw noop result for claim %s on listing %s: %s',
            due_claim.get('id'),
            listing.get('id'),
            result,
        )



def register_payment_deadline_jobs(application: Application, scheduler: AsyncIOScheduler) -> None:
    """Register the recurring APScheduler job for payment deadline processing."""

    scheduler.add_job(
        run_payment_deadline_cycle,
        'interval',
        minutes=1,
        id=PAYMENT_DEADLINE_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        kwargs={'application': application},
    )
