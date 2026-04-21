from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import config
from config import ConfigurationError


BASE_ENV = {
    'TELEGRAM_BOT_TOKEN': 'token',
    'TELEGRAM_BOT_USERNAME': '@bot',
    'BOT_BRAND_NAME': 'Bot',
    'SUPABASE_URL': 'https://example.supabase.co',
    'SUPABASE_SERVICE_KEY': 'service-key',
    'SUPABASE_PUBLISHABLE_KEY': 'publishable-key',
    'SUPABASE_STORAGE_BUCKET': 'bucket',
    'ENVIRONMENT': 'test',
    'LOG_LEVEL': 'INFO',
    'DEFAULT_TIMEZONE': 'Asia/Singapore',
    'DEFAULT_PAYMENT_DEADLINE_HOURS': '24',
    'DEFAULT_AUTO_BUMP_DAYS': '3',
    'DEFAULT_PRICE_ALERT_THRESHOLD': '0.15',
    'MIN_LISTING_PRICE_SGD': '0.5',
    'MAX_LISTING_PRICE_SGD': '1000',
    'COMMENTS_VIA_DISCUSSION_GROUP': 'false',
}


class ConfigTests(unittest.TestCase):
    def tearDown(self) -> None:
        config.get_config.cache_clear()

    def test_openai_provider_requires_key(self) -> None:
        env = dict(BASE_ENV)
        env['OCR_PROVIDER'] = 'openai_gpt4o_mini'
        with patch.object(config, 'load_dotenv', return_value=None), patch.dict(os.environ, env, clear=True):
            config.get_config.cache_clear()
            with self.assertRaises(ConfigurationError) as ctx:
                config.get_config()
        self.assertIn('OPENAI_API_KEY', str(ctx.exception))

    def test_tesseract_config_still_valid(self) -> None:
        env = dict(BASE_ENV)
        env['OCR_PROVIDER'] = 'tesseract'
        with patch.object(config, 'load_dotenv', return_value=None), patch.dict(os.environ, env, clear=True):
            config.get_config.cache_clear()
            loaded = config.get_config()
        self.assertEqual(loaded.ocr_provider, 'tesseract')

    def test_google_vision_config_still_valid(self) -> None:
        env = dict(BASE_ENV)
        env['OCR_PROVIDER'] = 'google_vision'
        env['GOOGLE_APPLICATION_CREDENTIALS'] = '/tmp/fake-service-account.json'
        with patch.object(config, 'load_dotenv', return_value=None), patch.dict(os.environ, env, clear=True):
            config.get_config.cache_clear()
            loaded = config.get_config()
        self.assertEqual(loaded.ocr_provider, 'google_vision')
        self.assertEqual(loaded.google_application_credentials, '/tmp/fake-service-account.json')


if __name__ == '__main__':
    unittest.main()
