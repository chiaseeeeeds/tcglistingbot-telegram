from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from services.card_detection import CardImageCandidate
from services.openai_ocr import OpenAIOCRBatchResult, OpenAIOCRRegion, OpenAIOCRRequestError, OpenAIOCRSchemaError
from services.ocr import extract_text_from_image


class OCRPipelineTests(unittest.TestCase):
    def _image_file(self) -> str:
        handle = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        handle.close()
        Image.new('RGB', (120, 180), color='white').save(handle.name)
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return handle.name

    def _candidate(self) -> CardImageCandidate:
        return CardImageCandidate(
            image=Image.new('RGB', (744, 1039), color='white'),
            source='detected_test',
            confidence=0.91,
        )

    def test_openai_success_populates_provider_text_and_structured(self) -> None:
        image_path = self._image_file()
        openai_result = OpenAIOCRBatchResult(
            regions=[
                OpenAIOCRRegion(
                    label='identifier_window_1',
                    identifier_text='PAF 234/091',
                    ratio_text='234/091',
                    set_code='PAF',
                    name_en='',
                    name_jp='',
                    raw_text='PAF 234/091',
                ),
                OpenAIOCRRegion(
                    label='name_window_1',
                    identifier_text='',
                    ratio_text='',
                    set_code='',
                    name_en='Charizard ex',
                    name_jp='リザードンex',
                    raw_text='Charizard ex',
                ),
            ],
            best_guess=OpenAIOCRRegion(
                label='identifier_window_1',
                identifier_text='PAF 234/091',
                ratio_text='234/091',
                set_code='PAF',
                name_en='Charizard ex',
                name_jp='リザードンex',
                raw_text='PAF 234/091 Charizard ex',
            ),
            warnings=[],
        )
        with patch('services.ocr.get_ocr_provider_name', return_value='openai_gpt4o_mini'), \
             patch('services.ocr.extract_card_candidates', return_value=[self._candidate()]), \
             patch('services.ocr.extract_card_text_from_regions', return_value=openai_result), \
             patch('services.ocr._known_set_codes', return_value={'PAF'}), \
             patch('services.ocr._write_debug_artifacts', return_value=None):
            result = extract_text_from_image(image_path, game='pokemon')

        self.assertEqual(result.provider, 'openai_gpt4o_mini')
        self.assertIn('IDENTIFIER: PAF 234/091', result.text)
        self.assertIn('NAME_EN: Charizard ex', result.text)
        self.assertEqual(result.structured.top_value('identifier'), 'PAF 234/091')
        self.assertEqual(result.structured.top_value('name_en'), 'Charizard ex')
        self.assertEqual(result.structured.top_value('name_jp'), 'リザードンex')

    def test_openai_invalid_schema_returns_openai_warning(self) -> None:
        image_path = self._image_file()
        with patch('services.ocr.get_ocr_provider_name', return_value='openai_gpt4o_mini'), \
             patch('services.ocr.extract_card_text_from_regions', side_effect=OpenAIOCRSchemaError('bad schema')), \
             patch('services.ocr._known_set_codes', return_value={'PAF'}), \
             patch('services.ocr._write_debug_artifacts', return_value=None):
            result = extract_text_from_image(image_path, game='pokemon')

        self.assertEqual(result.provider, 'openai_gpt4o_mini')
        self.assertEqual(result.text, '')
        self.assertTrue(any('Hosted OCR failed before text could be extracted' in warning for warning in result.warnings))

    def test_openai_timeout_returns_openai_warning(self) -> None:
        image_path = self._image_file()
        with patch('services.ocr.get_ocr_provider_name', return_value='openai_gpt4o_mini'), \
             patch('services.ocr.extract_card_text_from_regions', side_effect=OpenAIOCRRequestError('timeout')), \
             patch('services.ocr._known_set_codes', return_value={'PAF'}), \
             patch('services.ocr._write_debug_artifacts', return_value=None):
            result = extract_text_from_image(image_path, game='pokemon')

        self.assertEqual(result.provider, 'openai_gpt4o_mini')
        self.assertEqual(result.source, 'raw_photo')
        self.assertEqual(result.text, '')
        self.assertTrue(any('Hosted OCR failed before text could be extracted' in warning for warning in result.warnings))


if __name__ == '__main__':
    unittest.main()
