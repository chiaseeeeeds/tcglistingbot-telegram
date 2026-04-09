"""Database RPC wrappers for atomic TCG Listing Bot state transitions."""

from __future__ import annotations

from typing import Any, Dict

from db.client import get_client


async def call_rpc(function_name: str, params: Dict[str, Any]) -> Any:
    """Invoke a Supabase RPC function and return its data or raise on error."""

    response = get_client().rpc(function_name, params).execute()
    if getattr(response, "data", None) is None and getattr(response, "error", None):
        raise RuntimeError(f"RPC '{function_name}' failed: {response.error}")
    return response.data
