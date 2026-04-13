"""Application configuration loading and validation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import List

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    """Typed application configuration loaded from environment variables."""

    telegram_bot_token: str
    telegram_bot_username: str
    bot_brand_name: str
    telegram_webhook_url: str
    supabase_url: str
    supabase_service_key: str
    supabase_publishable_key: str
    database_url: str
    supabase_storage_bucket: str
    ocr_provider: str
    google_application_credentials: str
    primary_channel_username: str
    comments_via_discussion_group: bool
    tcgplayer_public_key: str
    tcgplayer_private_key: str
    pricecharting_api_token: str
    pricecharting_scrape_fallback_enabled: bool
    environment: str
    log_level: str
    default_timezone: str
    default_payment_deadline_hours: int
    default_auto_bump_days: int
    default_price_alert_threshold: float
    min_listing_price_sgd: float
    max_listing_price_sgd: float
    bot_admin_telegram_ids: List[int]


class ConfigurationError(RuntimeError):
    """Raised when required application configuration is missing or invalid."""


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Load environment variables once and return an immutable configuration object."""

    load_dotenv()

    def require(name: str, *, default: str | None = None) -> str:
        value = os.getenv(name, default)
        if value is None or value == "":
            raise ConfigurationError(f"Required environment variable '{name}' is not set.")
        return value

    def optional(name: str, *, default: str = "") -> str:
        return os.getenv(name, default)

    def parse_int(name: str, *, default: str | None = None) -> int:
        raw_value = require(name, default=default)
        try:
            return int(raw_value)
        except ValueError as exc:
            raise ConfigurationError(f"Environment variable '{name}' must be an integer.") from exc

    def parse_float(name: str, *, default: str | None = None) -> float:
        raw_value = require(name, default=default)
        try:
            return float(raw_value)
        except ValueError as exc:
            raise ConfigurationError(f"Environment variable '{name}' must be a float.") from exc

    def parse_bool(name: str, *, default: str = "false") -> bool:
        raw_value = optional(name, default=default).strip().lower()
        if raw_value in {"1", "true", "yes", "on"}:
            return True
        if raw_value in {"0", "false", "no", "off"}:
            return False
        raise ConfigurationError(f"Environment variable '{name}' must be a boolean.")

    def parse_admin_ids(raw_value: str) -> List[int]:
        if not raw_value.strip():
            return []
        parsed_values: List[int] = []
        for chunk in raw_value.split(","):
            value = chunk.strip()
            if not value:
                continue
            try:
                parsed_values.append(int(value))
            except ValueError as exc:
                raise ConfigurationError(
                    "BOT_ADMIN_TELEGRAM_IDS must contain only comma-separated integers."
                ) from exc
        return parsed_values

    supabase_service_key = optional("SUPABASE_SERVICE_KEY")
    supabase_publishable_key = optional("SUPABASE_PUBLISHABLE_KEY")
    if not supabase_service_key:
        raise ConfigurationError(
            "SUPABASE_SERVICE_KEY is required for the current backend design. "
            "A publishable/anon key is not enough for server-side bot operations."
        )

    ocr_provider = optional("OCR_PROVIDER", default="tesseract").strip().lower()
    if ocr_provider not in {"tesseract", "google_vision"}:
        raise ConfigurationError(
            "OCR_PROVIDER must be one of: 'tesseract', 'google_vision'."
        )

    google_application_credentials = optional("GOOGLE_APPLICATION_CREDENTIALS")
    if ocr_provider == "google_vision" and not google_application_credentials:
        raise ConfigurationError(
            "GOOGLE_APPLICATION_CREDENTIALS is required when OCR_PROVIDER=google_vision."
        )

    return Config(
        telegram_bot_token=require("TELEGRAM_BOT_TOKEN"),
        telegram_bot_username=require("TELEGRAM_BOT_USERNAME", default="@TCGlistingbot"),
        bot_brand_name=require("BOT_BRAND_NAME", default="TCG Listing Bot"),
        telegram_webhook_url=optional("TELEGRAM_WEBHOOK_URL"),
        supabase_url=require("SUPABASE_URL"),
        supabase_service_key=supabase_service_key,
        supabase_publishable_key=supabase_publishable_key,
        database_url=optional("DATABASE_URL"),
        supabase_storage_bucket=require(
            "SUPABASE_STORAGE_BUCKET", default="tcg-listing-bot-images"
        ),
        ocr_provider=ocr_provider,
        google_application_credentials=google_application_credentials,
        primary_channel_username=optional("PRIMARY_CHANNEL_USERNAME"),
        comments_via_discussion_group=parse_bool(
            "COMMENTS_VIA_DISCUSSION_GROUP", default="false"
        ),
        tcgplayer_public_key=optional("TCGPLAYER_PUBLIC_KEY"),
        tcgplayer_private_key=optional("TCGPLAYER_PRIVATE_KEY"),
        pricecharting_api_token=optional("PRICECHARTING_API_TOKEN"),
        pricecharting_scrape_fallback_enabled=parse_bool("PRICECHARTING_SCRAPE_FALLBACK_ENABLED", default="false"),
        environment=require("ENVIRONMENT", default="development"),
        log_level=require("LOG_LEVEL", default="INFO"),
        default_timezone=require("DEFAULT_TIMEZONE", default="Asia/Singapore"),
        default_payment_deadline_hours=parse_int(
            "DEFAULT_PAYMENT_DEADLINE_HOURS", default="24"
        ),
        default_auto_bump_days=parse_int("DEFAULT_AUTO_BUMP_DAYS", default="3"),
        default_price_alert_threshold=parse_float(
            "DEFAULT_PRICE_ALERT_THRESHOLD", default="0.15"
        ),
        min_listing_price_sgd=parse_float("MIN_LISTING_PRICE_SGD", default="0.50"),
        max_listing_price_sgd=parse_float("MAX_LISTING_PRICE_SGD", default="10000"),
        bot_admin_telegram_ids=parse_admin_ids(optional("BOT_ADMIN_TELEGRAM_IDS")),
    )
