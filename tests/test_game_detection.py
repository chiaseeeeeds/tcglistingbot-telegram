from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from services.game_detection import GameDetectionResult, detect_game_from_image
from services.openai_ocr import OpenAIGameDetectionResult, OpenAIOCRRequestError


class GameDetectionTests(unittest.TestCase):
    def _image_file(self) -> str:
        handle = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        handle.close()
        Image.new('RGB', (120, 180), color='white').save(handle.name)
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return handle.name

    def _regions(self) -> list[tuple[str, Image.Image]]:
        return [
            ('header_window', Image.new('RGB', (100, 40), color='white')),
            ('bottom_window', Image.new('RGB', (100, 40), color='white')),
        ]

    def test_openai_provider_now_uses_heuristic_for_speed(self) -> None:
        image_path = self._image_file()
        heuristic = GameDetectionResult(game='pokemon', confidence=0.8, reason='header and rules text look Pokémon-like', tokens_seen=['HP'])
        with patch('services.game_detection.get_config') as mock_config, \
             patch('services.game_detection._prepare_regions', return_value=self._regions()), \
             patch('services.game_detection._heuristic_game_detection', return_value=heuristic):
            mock_config.return_value.ocr_provider = 'openai_gpt4o_mini'
            result = detect_game_from_image(image_path)
        self.assertEqual(result.game, 'pokemon')
        self.assertGreaterEqual(result.confidence, 0.6)
        self.assertIn('HP', result.tokens_seen)

    def test_weak_openai_result_falls_back_to_heuristic(self) -> None:
        image_path = self._image_file()
        heuristic = GameDetectionResult(game='onepiece', confidence=0.7, reason='heuristic matched', tokens_seen=['LEADER'])
        with patch('services.game_detection.get_config') as mock_config, \
             patch('services.game_detection._prepare_regions', return_value=self._regions()), \
             patch('services.game_detection.detect_game_from_regions', return_value=OpenAIGameDetectionResult(game='unknown', confidence=0.4, reason='weak signal', tokens_seen=[])), \
             patch('services.game_detection._heuristic_game_detection', return_value=heuristic):
            mock_config.return_value.ocr_provider = 'openai_gpt4o_mini'
            result = detect_game_from_image(image_path)
        self.assertEqual(result.game, 'onepiece')
        self.assertEqual(result.reason, 'heuristic matched')

    def test_openai_failure_and_weak_tesseract_defaults_to_pokemon(self) -> None:
        image_path = self._image_file()
        with patch('services.game_detection.get_config') as mock_config, \
             patch('services.game_detection._prepare_regions', return_value=self._regions()), \
             patch('services.game_detection.detect_game_from_regions', side_effect=OpenAIOCRRequestError('timeout')), \
             patch('services.game_detection._tesseract_probe', return_value=('', [])):
            mock_config.return_value.ocr_provider = 'openai_gpt4o_mini'
            result = detect_game_from_image(image_path)
        self.assertEqual(result.game, 'pokemon')
        self.assertAlmostEqual(result.confidence, 0.35)


if __name__ == '__main__':
    unittest.main()
