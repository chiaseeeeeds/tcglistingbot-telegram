"""Supabase client singleton for TCG Listing Bot."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Iterable

from supabase import Client, create_client

from config import get_config


class DatabaseError(RuntimeError):
    """Raised when a Supabase request fails or returns unexpected data."""


@lru_cache(maxsize=1)
def get_client() -> Client:
    """Create and cache the shared Supabase client instance."""

    config = get_config()
    return create_client(config.supabase_url, config.supabase_service_key)


def extract_single(response: Any) -> dict[str, Any] | None:
    """Return the first row from a Supabase response or `None` if no rows were returned."""

    data = getattr(response, 'data', None)
    if not data:
        return None
    return data[0]


def extract_many(response: Any) -> list[dict[str, Any]]:
    """Return rows from a Supabase response as a list."""

    data = getattr(response, 'data', None)
    return list(data or [])


def require_data(response: Any, *, context: str) -> Iterable[Any]:
    """Ensure a Supabase response contains data or raise a useful database error."""

    if getattr(response, 'data', None) is None:
        raise DatabaseError(f'Supabase request failed during {context}.')
    return response.data
