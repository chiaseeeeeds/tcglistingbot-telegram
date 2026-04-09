"""OCR provider scaffolding for TCG Listing Bot."""

from __future__ import annotations

from config import get_config


class OCRNotConfiguredError(RuntimeError):
    """Raised when the selected OCR provider is unavailable or not configured."""


def get_ocr_provider_name() -> str:
    """Return the configured OCR provider name for runtime selection logic."""

    return get_config().ocr_provider
