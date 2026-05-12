from __future__ import annotations

import unittest
from unittest.mock import patch

from services.card_identifier import identify_card_from_text
from services.ocr_signals import OCRSignal, OCRStructuredResult


class CardIdentifierJapaneseTests(unittest.TestCase):
    def test_exact_japanese_name_signal_matches_catalog(self) -> None:
        catalog = [
            {
                'id': 'jp-1',
                'game': 'pokemon',
                'card_name_en': 'Charizard',
                'card_name_jp': 'リザードン',
                'set_name': 'ポケモンカード151',
                'set_code': 'SV2A',
                'card_number': '006',
                'variant': '',
            },
            {
                'id': 'jp-2',
                'game': 'pokemon',
                'card_name_en': 'Blastoise',
                'card_name_jp': 'カメックス',
                'set_name': 'ポケモンカード151',
                'set_code': 'SV2A',
                'card_number': '009',
                'variant': '',
            },
        ]
        structured = OCRStructuredResult(
            layout_family='pokemon_card_generic',
            selected_source='raw_photo',
            signals=[
                OCRSignal(kind='name_jp', value='リザードン', confidence=0.95, source='raw_photo', region='name'),
            ],
        )
        with patch('services.card_identifier.list_cards_for_game', return_value=catalog), \
             patch('services.card_identifier.list_cards_by_identifier', return_value=[]):
            result = identify_card_from_text(raw_text='NAME_JP: リザードン', game='pokemon', structured=structured)
        self.assertTrue(result.matched)
        self.assertEqual(result.card_id, 'jp-1')
        self.assertIn('Charizard', result.display_name)
        self.assertTrue(any('Exact Japanese name matched: リザードン' in reason for reason in result.match_reasons))


class CardIdentifierExactIdentifierGuardTests(unittest.TestCase):
    def test_mismatched_print_total_does_not_auto_match_exact_identifier(self) -> None:
        catalog = [
            {
                'id': 'tr-3',
                'game': 'pokemon',
                'card_name_en': 'Dark Blastoise',
                'card_name_jp': '',
                'set_name': 'Team Rocket',
                'set_code': 'TR',
                'card_number': '3',
                'variant': 'Holo',
            },
        ]
        structured = OCRStructuredResult(
            layout_family='pokemon_card_generic',
            selected_source='raw_photo',
            signals=[
                OCRSignal(kind='set_code_text', value='TR', confidence=0.95, source='raw_photo', region='full'),
                OCRSignal(kind='printed_ratio', value='3/182', confidence=0.95, source='raw_photo', region='full'),
                OCRSignal(kind='name_en', value='Nidoking', confidence=0.92, source='raw_photo', region='full'),
            ],
        )
        with patch('services.card_identifier.list_cards_for_game', return_value=catalog), \
             patch('services.card_identifier.list_cards_by_identifier', return_value=catalog), \
             patch('services.card_identifier._pokemon_set_card_counts', return_value={'TR': '82'}):
            result = identify_card_from_text(raw_text='TR 3/182 Nidoking', game='pokemon', structured=structured)
        self.assertFalse(result.matched)
        self.assertEqual(result.display_name, 'Unknown card')
        self.assertNotEqual(result.metadata.get('resolver'), 'exact_identifier')



class CardIdentifierModernTeamRocketCollisionTests(unittest.TestCase):
    def test_modern_team_rocket_name_does_not_infer_legacy_tr_set_code(self) -> None:
        catalog = [
            {
                'id': 'legacy-tr-3',
                'game': 'pokemon',
                'card_name_en': 'Dark Blastoise',
                'card_name_jp': '',
                'set_name': 'Team Rocket',
                'set_code': 'TR',
                'card_number': '3',
                'variant': 'Holo',
            },
            {
                'id': 'modern-233',
                'game': 'pokemon',
                'card_name_en': "Team Rocket's Nidoking ex",
                'card_name_jp': '',
                'set_name': 'The Glory of Team Rocket',
                'set_code': 'SV10',
                'card_number': '233',
                'variant': '',
            },
        ]
        structured = OCRStructuredResult(
            layout_family='pokemon_card_generic',
            selected_source='raw_photo',
            signals=[
                OCRSignal(kind='printed_ratio', value='233/182', confidence=0.95, source='raw_photo', region='full'),
                OCRSignal(kind='name_en', value="Team Rocket Nidoking EX", confidence=0.94, source='raw_photo', region='full'),
            ],
        )
        with patch('services.card_identifier.list_cards_for_game', return_value=catalog), \
             patch('services.card_identifier.list_cards_by_identifier', return_value=[]), \
             patch('services.card_identifier._pokemon_set_card_counts', return_value={'TR': '82', 'SV10': '182'}):
            result = identify_card_from_text(
                raw_text="IDENTIFIER: 233/182 NAME_EN: Team Rocket Nidoking EX",
                game='pokemon',
                structured=structured,
            )
        self.assertTrue(result.matched)
        self.assertEqual(result.card_id, 'modern-233')
        self.assertNotEqual(result.metadata.get('detected_set_code'), 'TR')


    def test_modern_team_aqua_name_does_not_infer_legacy_aq_set_code(self) -> None:
        catalog = [
            {
                'id': 'legacy-aq-3',
                'game': 'pokemon',
                'card_name_en': "Team Aqua's Kyogre",
                'card_name_jp': '',
                'set_name': 'Team Magma vs Team Aqua',
                'set_code': 'AQ',
                'card_number': '3',
                'variant': 'Holo',
            },
            {
                'id': 'modern-149',
                'game': 'pokemon',
                'card_name_en': "Team Aqua's Kyogre ex",
                'card_name_jp': '',
                'set_name': 'Double Blaze',
                'set_code': 'SVX',
                'card_number': '149',
                'variant': '',
            },
        ]
        structured = OCRStructuredResult(
            layout_family='pokemon_card_generic',
            selected_source='raw_photo',
            signals=[
                OCRSignal(kind='printed_ratio', value='149/182', confidence=0.95, source='raw_photo', region='full'),
                OCRSignal(kind='name_en', value="Team Aqua Kyogre EX", confidence=0.94, source='raw_photo', region='full'),
            ],
        )
        with patch('services.card_identifier.list_cards_for_game', return_value=catalog), \
             patch('services.card_identifier.list_cards_by_identifier', return_value=[]), \
             patch('services.card_identifier._pokemon_set_card_counts', return_value={'AQ': '95', 'SVX': '182'}):
            result = identify_card_from_text(
                raw_text="IDENTIFIER: 149/182 NAME_EN: Team Aqua Kyogre EX",
                game='pokemon',
                structured=structured,
            )
        self.assertTrue(result.matched)
        self.assertEqual(result.card_id, 'modern-149')
        self.assertNotEqual(result.metadata.get('detected_set_code'), 'AQ')

    def test_modern_ratio_does_not_infer_legacy_set_from_raw_text_fallback(self) -> None:
        catalog = [
            {
                'id': 'legacy-tr-3',
                'game': 'pokemon',
                'card_name_en': 'Dark Blastoise',
                'card_name_jp': '',
                'set_name': 'Team Rocket',
                'set_code': 'TR',
                'card_number': '3',
                'variant': 'Holo',
            },
            {
                'id': 'modern-233',
                'game': 'pokemon',
                'card_name_en': "Team Rocket's Nidoking ex",
                'card_name_jp': '',
                'set_name': 'The Glory of Team Rocket',
                'set_code': 'SV10',
                'card_number': '233',
                'variant': '',
            },
        ]
        with patch('services.card_identifier.list_cards_for_game', return_value=catalog), \
             patch('services.card_identifier.list_cards_by_identifier', return_value=[]), \
             patch('services.card_identifier._pokemon_set_card_counts', return_value={'TR': '82', 'SV10': '182'}):
            result = identify_card_from_text(
                raw_text="233/182 Team Rocket Nidoking EX",
                game='pokemon',
                structured=None,
            )
        self.assertTrue(result.matched)
        self.assertEqual(result.card_id, 'modern-233')
        self.assertNotEqual(result.metadata.get('detected_set_code'), 'TR')

    def test_raw_identifier_ratio_overrides_truncated_structured_ratio(self) -> None:
        catalog = [
            {
                'id': 'legacy-tr-3',
                'game': 'pokemon',
                'card_name_en': 'Dark Blastoise',
                'card_name_jp': '',
                'set_name': 'Team Rocket',
                'set_code': 'TR',
                'card_number': '3',
                'variant': 'Holo',
            },
            {
                'id': 'modern-233',
                'game': 'pokemon',
                'card_name_en': "Team Rocket's Nidoking ex",
                'card_name_jp': '',
                'set_name': 'Destined Rivals',
                'set_code': 'DRI',
                'card_number': '233',
                'variant': '',
            },
        ]
        structured = OCRStructuredResult(
            layout_family='pokemon_card_generic',
            selected_source='raw_photo',
            signals=[
                OCRSignal(kind='printed_ratio', value='3/182', confidence=0.95, source='raw_photo', region='full'),
                OCRSignal(kind='name_en', value='Team Rocket Nidoking EX', confidence=0.94, source='raw_photo', region='full'),
                OCRSignal(kind='identifier', value='233/182', confidence=0.93, source='raw_photo', region='full'),
            ],
        )
        with patch('services.card_identifier.list_cards_for_game', return_value=catalog), \
             patch('services.card_identifier.list_cards_by_identifier', return_value=[]), \
             patch('services.card_identifier._pokemon_set_card_counts', return_value={'TR': '82', 'DRI': '182'}):
            result = identify_card_from_text(
                raw_text='IDENTIFIER: 233/182 | NAME_EN: Team Rocket Nidoking EX',
                game='pokemon',
                structured=structured,
            )
        self.assertTrue(result.matched)
        self.assertEqual(result.card_id, 'modern-233')
        self.assertEqual(result.metadata.get('detected_print_number'), '233/182')
        self.assertNotEqual(result.metadata.get('resolver'), 'nearby_ratio_name_shortlist')



if __name__ == '__main__':
    unittest.main()
