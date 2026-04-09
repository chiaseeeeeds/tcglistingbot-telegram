"""Supabase client singleton for TCG Listing Bot."""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from config import get_config


@lru_cache(maxsize=1)
def get_client() -> Client:
    """Create and cache the shared Supabase client instance."""

    config = get_config()
    return create_client(config.supabase_url, config.supabase_service_key)
