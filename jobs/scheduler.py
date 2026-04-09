"""Scheduler factory for TCG Listing Bot background jobs."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler


def build_scheduler(timezone: str) -> AsyncIOScheduler:
    """Create and return the shared APScheduler instance for background jobs."""

    return AsyncIOScheduler(timezone=timezone)
