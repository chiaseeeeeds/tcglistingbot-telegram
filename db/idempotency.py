"""DB-backed idempotency helpers for Telegram-triggered side effects."""

from __future__ import annotations

from typing import Any

from postgrest.exceptions import APIError

from db.client import get_client



def register_processed_event(*, source: str, event_key: str, metadata: dict[str, Any] | None = None) -> bool:
    """Record an event once and return whether this is the first successful registration."""

    payload = {
        'source': source,
        'event_key': event_key,
        'metadata': metadata or {},
    }
    try:
        get_client().table('processed_events').insert(payload).execute()
        return True
    except APIError as exc:
        details = exc.json() if hasattr(exc, 'json') else {}
        if details.get('code') == '23505':
            return False
        raise
