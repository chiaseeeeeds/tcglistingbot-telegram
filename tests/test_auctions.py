from __future__ import annotations

import unittest
from unittest.mock import patch

from handlers.auctions import (
    _parse_auction_end_input,
    _parse_optional_auction_payment_deadline_input,
    _parse_optional_auction_reserve_input,
)
from utils.auction_settings import resolve_listing_payment_deadline_hours
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

    def test_parse_optional_reserve_price(self) -> None:
        self.assertEqual(_parse_optional_auction_reserve_input('15', starting_bid_sgd=10.0), 15.0)
        self.assertIsNone(_parse_optional_auction_reserve_input('skip', starting_bid_sgd=10.0))
        with self.assertRaises(ValueError):
            _parse_optional_auction_reserve_input('9', starting_bid_sgd=10.0)

    def test_parse_optional_payment_deadline(self) -> None:
        self.assertEqual(_parse_optional_auction_payment_deadline_input('48'), 48)
        self.assertIsNone(_parse_optional_auction_payment_deadline_input('skip'))
        with self.assertRaises(ValueError):
            _parse_optional_auction_payment_deadline_input('0')

    def test_payment_deadline_override_beats_seller_default(self) -> None:
        hours = resolve_listing_payment_deadline_hours(
            listing={'listing_type': 'auction', 'auction_payment_deadline_hours': 12},
            seller_config={'payment_deadline_hours': 24},
            default_hours=36,
        )
        self.assertEqual(hours, 12)

    def test_auction_post_renders_reserve_deadline_and_rules(self) -> None:
        text = format_auction_listing(
            card_name='Nidoking',
            game='pokemon',
            starting_bid_sgd=10.0,
            current_bid_sgd=12.0,
            bid_increment_sgd=1.0,
            anti_snipe_minutes=5,
            reserve_price_sgd=20.0,
            payment_deadline_hours=24,
            condition_notes='NM',
            custom_description='Anti-snipe 5m; payment in 24h',
            seller_display_name='Seller',
            auction_end_time='2026-05-13T13:00:00+00:00',
            status='auction_active',
        )
        self.assertIn('🗓️ Ends:', text)
        self.assertIn('🛡️ Anti-snipe:', text)
        self.assertIn('🎯 Reserve:', text)
        self.assertIn('⏰ Payment window:', text)
        self.assertIn('📜 Rules:', text)
        self.assertIn('Anti-snipe 5m; payment in 24h', text)

    def test_auction_reserve_not_met_status_renders(self) -> None:
        text = format_auction_listing(
            card_name='Nidoking',
            game='pokemon',
            starting_bid_sgd=10.0,
            current_bid_sgd=12.0,
            bid_increment_sgd=1.0,
            anti_snipe_minutes=5,
            reserve_price_sgd=20.0,
            payment_deadline_hours=24,
            condition_notes='NM',
            custom_description='',
            seller_display_name='Seller',
            auction_end_time='2026-05-13T13:00:00+00:00',
            status='auction_reserve_not_met',
        )
        self.assertIn('Reserve was not met', text)


if __name__ == '__main__':
    unittest.main()
