from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from services.card_identifier import CardIdentificationResult
from services.game_detection import GameDetectionResult
from services.listing_image_classifier import classify_listing_images
from services.ocr import OCRResult
from services.ocr_signals import OCRSignal, OCRStructuredResult
from utils.photo_quality import PhotoQualityAssessment


class ListingImageClassifierTests(unittest.TestCase):
    def _image_file(self) -> str:
        handle = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        handle.close()
        Image.new('RGB', (120, 180), color='white').save(handle.name)
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return handle.name

    def _ocr_result(self, provider: str) -> OCRResult:
        structured = OCRStructuredResult(
            layout_family='pokemon_card_generic',
            selected_source='detected_test',
            signals=[
                OCRSignal(kind='identifier', value='PAF 234/091', confidence=0.9, source='detected_test', region='identifier'),
                OCRSignal(kind='name_en', value='Charizard ex', confidence=0.8, source='detected_test', region='name'),
            ],
        )
        return OCRResult(
            text='IDENTIFIER: PAF 234/091 | NAME_EN: Charizard ex',
            provider=provider,
            model='gpt-4o-mini' if provider == 'openai_gpt4o_mini' else provider,
            requested_provider=provider,
            used_fallback=False,
            latency_ms=1200,
            warnings=[],
            structured=structured,
        )

    def _identification(self) -> CardIdentificationResult:
        return CardIdentificationResult(
            matched=True,
            confidence=0.88,
            display_name='Charizard ex',
            card_id='1',
            raw_text='IDENTIFIER: PAF 234/091 | NAME_EN: Charizard ex',
            match_reasons=['identifier and name matched'],
            metadata={},
            candidate_options=[],
        )

    def _photo_quality(self) -> PhotoQualityAssessment:
        return PhotoQualityAssessment(
            width=1200,
            height=1800,
            sharpness=120.0,
            brightness=150.0,
            contrast=40.0,
            glare_ratio=0.01,
            dark_ratio=0.01,
            score=0.9,
            acceptable=True,
            warnings=[],
        )

    def test_classifier_completes_when_openai_succeeds(self) -> None:
        image_path = self._image_file()
        with patch('services.listing_image_classifier.assess_photo_quality', return_value=self._photo_quality()), \
             patch('services.listing_image_classifier.detect_game_from_image', return_value=GameDetectionResult(game='pokemon', confidence=0.9, reason='ok', tokens_seen=[])), \
             patch('services.listing_image_classifier.extract_text_from_image', return_value=self._ocr_result('openai_gpt4o_mini')), \
             patch('services.listing_image_classifier.identify_card_from_text', return_value=self._identification()):
            result = classify_listing_images([image_path])
        self.assertEqual(len(result.analyses), 1)
        self.assertEqual(result.analyses[0].ocr_result.provider, 'openai_gpt4o_mini')

    def test_classifier_completes_when_openai_falls_back_to_tesseract(self) -> None:
        image_path = self._image_file()
        with patch('services.listing_image_classifier.assess_photo_quality', return_value=self._photo_quality()), \
             patch('services.listing_image_classifier.detect_game_from_image', return_value=GameDetectionResult(game='pokemon', confidence=0.4, reason='fallback', tokens_seen=[])), \
             patch('services.listing_image_classifier.extract_text_from_image', return_value=self._ocr_result('tesseract')), \
             patch('services.listing_image_classifier.identify_card_from_text', return_value=self._identification()):
            result = classify_listing_images([image_path])
        self.assertEqual(len(result.analyses), 1)
        self.assertEqual(result.analyses[0].ocr_result.provider, 'tesseract')


if __name__ == '__main__':
    unittest.main()
