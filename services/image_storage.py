"""Supabase Storage helpers for listing images."""

from __future__ import annotations

import logging
from pathlib import Path

from config import get_config
from db.client import get_client

logger = logging.getLogger(__name__)


def upload_listing_photo(*, local_path: str | Path, seller_id: str, telegram_file_id: str) -> str | None:
    """Upload a listing photo to Supabase Storage and return the object path.

    This is best-effort for v1. Listing creation must continue even if storage upload fails.
    """

    path = Path(local_path)
    if not path.exists():
        raise FileNotFoundError(f'Listing photo not found: {path}')

    bucket = get_config().supabase_storage_bucket
    object_path = f'listing-images/{seller_id}/{telegram_file_id}{path.suffix.lower() or ".jpg"}'
    try:
        get_client().storage.from_(bucket).upload(
            object_path,
            path,
            {'content-type': 'image/jpeg'},
        )
        return object_path
    except Exception as exc:
        logger.warning('Failed to upload listing photo %s to storage bucket %s: %s', path, bucket, exc)
        return None
