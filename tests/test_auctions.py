from __future__ import annotations

import unittest
from unittest.mock import patch

from handlers.auctions import _parse_auction_end_input
from utils.formatters import format_auction_listing


class AuctionCreationFlowTests(unittest.TestCase):
    def test_parse_duration_hours_input(self) -> None:
        parsed = _parse_auction_end_input('24')
        self.assertIsNotNone(parsed)
        end_time, duration_hours = parsed or ('', 0.0)
        self.assertTrue(end_time)
        self.assertGreater(duration_hours, 23.5)

    def test_parse_exact_local_datetime_input(self) -> None:
        with patch('handlers.auctions.get_config') as mock_config:
            mock_config.return_value.default_timezone = 'Asia/Singapore'
            parsed = _parse_auction_end_input('2026-05-13 21:00')
        self.assertIsNotNone(parsed)
        end_time, duration_hours = parsed or ('', 0.0)
        self.assertIn('+00:00', end_time)
        self.assertGreater(duration_hours, 0)

    def test_auction_post_renders_absolute_end_and_rules(self) -> None:
        text = format_auction_listing(
            card_name='Nidoking',
            game='pokemon',
            starting_bid_sgd=10.0,
            current_bid_sgd=12.0,
            bid_increment_sgd=1.0,
            anti_snipe_minutes=5,
            condition_notes='NM',
            custom_description='Anti-snipe 5m; payment in 24h',
            seller_display_name='Seller',
            auction_end_time='2026-05-13T13:00:00+00:00',
            status='auction_active',
        )
        self.assertIn('🗓️ Ends:', text)
        self.assertIn('🛡️ Anti-snipe:', text)
        self.assertIn('📜 Rules:', text)
        self.assertIn('Anti-snipe 5m; payment in 24h', text)


if __name__ == '__main__':
    unittest.main()
