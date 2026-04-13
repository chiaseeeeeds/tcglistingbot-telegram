"""Batch listing image classification helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from services.card_identifier import CardIdentificationResult, identify_card_from_text
from services.game_detection import GameDetectionResult, detect_game_from_image
from services.ocr import OCRNotConfiguredError, OCRResult, extract_text_from_image
from services.ocr_signals import OCRStructuredResult
from utils.photo_quality import PhotoQualityAssessment, assess_photo_quality

logger = logging.getLogger(__name__)
SUPPORTED_GAMES = {'pokemon', 'onepiece'}


@dataclass(frozen=True)
class ListingImageAnalysis:
    index: int
    image_path: str
    game: str
    game_detection: GameDetectionResult
    ocr_result: OCRResult
    identification: CardIdentificationResult
    photo_quality: PhotoQualityAssessment
    front_score: float
    back_score: float
    blue_ratio: float
    yellow_ratio: float


@dataclass(frozen=True)
class ListingImageClassification:
    analyses: list[ListingImageAnalysis]
    front_index: int | None
    back_index: int | None
    ordered_indices: list[int]



def _empty_ocr_result(*, warning: str) -> OCRResult:
    return OCRResult(
        text='',
        provider='none',
        warnings=[warning],
        structured=OCRStructuredResult(layout_family='unknown', selected_source='none', signals=[]),
    )



def _color_ratios(image_path: str | Path) -> tuple[float, float]:
    with Image.open(image_path).convert('RGB') as image:
        resized = image.resize((96, 96))
        pixels = list(resized.getdata())
    total = max(len(pixels), 1)
    blue_pixels = sum(1 for red, green, blue in pixels if blue > 70 and blue > red * 1.15 and blue > green * 1.05)
    yellow_pixels = sum(1 for red, green, blue in pixels if red > 150 and green > 130 and blue < 150)
    return blue_pixels / total, yellow_pixels / total



def _score_front_back(
    *,
    ocr_result: OCRResult,
    identification: CardIdentificationResult,
    game_detection: GameDetectionResult,
    photo_quality: PhotoQualityAssessment,
    blue_ratio: float,
    yellow_ratio: float,
) -> tuple[float, float]:
    ocr_text = str(ocr_result.text or '').strip()
    structured = ocr_result.structured
    identifier_value = structured.top_value('identifier') or structured.top_value('printed_ratio')
    name_value = structured.top_value('name_en') or structured.top_value('name_jp')

    front_score = 0.0
    front_score += min(len(ocr_text) / 140.0, 0.35)
    front_score += identification.confidence
    if identification.matched:
        front_score += 0.35
    if identifier_value:
        front_score += 0.45
    if name_value:
        front_score += 0.25
    if game_detection.confidence >= 0.6:
        front_score += 0.10
    front_score += photo_quality.score * 0.30
    if not photo_quality.acceptable:
        front_score -= 0.18
    if blue_ratio >= 0.34 and yellow_ratio >= 0.03:
        front_score -= 0.10

    back_score = 0.0
    if not identifier_value:
        back_score += 0.28
    if not name_value:
        back_score += 0.24
    if len(ocr_text) < 18:
        back_score += 0.32
    elif len(ocr_text) < 32:
        back_score += 0.15
    if not identification.matched or identification.confidence < 0.25:
        back_score += 0.18
    if blue_ratio >= 0.34:
        back_score += 0.22
    if blue_ratio >= 0.28 and yellow_ratio >= 0.03:
        back_score += 0.12
    if photo_quality.score < 0.35:
        back_score += 0.08
    return front_score, back_score



def classify_listing_images(image_paths: list[str], *, preferred_game: str | None = None) -> ListingImageClassification:
    analyses: list[ListingImageAnalysis] = []
    for index, image_path in enumerate(image_paths):
        photo_quality = assess_photo_quality(image_path)
        game_detection = detect_game_from_image(image_path)
        game = game_detection.game if game_detection.game in SUPPORTED_GAMES else (preferred_game or 'pokemon')
        try:
            ocr_result = extract_text_from_image(image_path, game=game)
        except OCRNotConfiguredError:
            raise
        except Exception as exc:
            logger.warning('OCR failed while classifying listing image %s: %s', image_path, exc)
            ocr_result = _empty_ocr_result(warning='OCR failed during front/back classification.')
        identification = identify_card_from_text(raw_text=str(ocr_result.text or ''), game=game, structured=ocr_result.structured)
        blue_ratio, yellow_ratio = _color_ratios(image_path)
        front_score, back_score = _score_front_back(
            ocr_result=ocr_result,
            identification=identification,
            game_detection=game_detection,
            photo_quality=photo_quality,
            blue_ratio=blue_ratio,
            yellow_ratio=yellow_ratio,
        )
        analyses.append(
            ListingImageAnalysis(
                index=index,
                image_path=str(image_path),
                game=game,
                game_detection=game_detection,
                ocr_result=ocr_result,
                identification=identification,
                photo_quality=photo_quality,
                front_score=front_score,
                back_score=back_score,
                blue_ratio=blue_ratio,
                yellow_ratio=yellow_ratio,
            )
        )

    if not analyses:
        return ListingImageClassification(analyses=[], front_index=None, back_index=None, ordered_indices=[])

    front_index = max(range(len(analyses)), key=lambda idx: analyses[idx].front_score)
    remaining = [idx for idx in range(len(analyses)) if idx != front_index]
    back_index = None
    if remaining:
        back_index = max(remaining, key=lambda idx: analyses[idx].back_score)

    ordered_indices = [front_index]
    if back_index is not None:
        ordered_indices.append(back_index)
    ordered_indices.extend(idx for idx in range(len(analyses)) if idx not in ordered_indices)
    return ListingImageClassification(
        analyses=analyses,
        front_index=front_index,
        back_index=back_index,
        ordered_indices=ordered_indices,
    )
