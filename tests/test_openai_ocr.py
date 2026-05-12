from __future__ import annotations

import unittest
from unittest.mock import patch

from PIL import Image

from services.openai_ocr import OpenAIOCRSchemaError, extract_card_text_from_regions


class OpenAIOCRServiceTests(unittest.TestCase):
    def test_schema_failure_falls_back_to_plain_text_parsing(self) -> None:
        image = Image.new('RGB', (640, 900), color='white')
        with patch('services.openai_ocr._request_structured_output', side_effect=OpenAIOCRSchemaError('bad schema')), \
             patch(
                 'services.openai_ocr._request_plain_text_output',
                 return_value=(
                     'LABEL: raw_photo\n'
                     'IDENTIFIER_TEXT: BS 11/102\n'
                     'RATIO_TEXT: 11/102\n'
                     'SET_CODE: BS\n'
                     'NAME_EN: Nidoking\n'
                     'NAME_JP: \n'
                     'RAW_TEXT: Nidoking 11/102\n'
                 ),
             ):
            result = extract_card_text_from_regions([('raw_photo', image)])

        self.assertEqual(result.best_guess.name_en, 'Nidoking')
        self.assertEqual(result.best_guess.ratio_text, '11/102')
        self.assertEqual(result.best_guess.set_code, 'BS')
        self.assertEqual(len(result.regions), 1)


if __name__ == '__main__':
    unittest.main()
