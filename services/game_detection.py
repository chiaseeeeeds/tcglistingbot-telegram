"""Best-effort game detection from a card photo."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from config import get_config
from services.card_detection import extract_card_candidates
from services.openai_ocr import OpenAIOCRError, detect_game_from_regions

logger = logging.getLogger(__name__)
_POKEMON_TOKENS = ['HP', 'STAGE', 'EVOLVES', 'WEAKNESS', 'RESISTANCE']
_ONEPIECE_TOKENS = ['DON', 'COUNTER', 'CHARACTER', 'LEADER', 'TRIGGER']


@dataclass(frozen=True)
class GameDetectionResult:
    game: str
    confidence: float
    reason: str
    tokens_seen: list[str] = field(default_factory=list)


def _prepare_roi(image: Image.Image) -> Image.Image:
    grayscale = ImageOps.grayscale(image)
    contrast = ImageEnhance.Contrast(grayscale).enhance(2.6)
    sharpened = contrast.filter(ImageFilter.SHARPEN)
    enlarged = sharpened.resize((max(sharpened.width * 3, 1), max(sharpened.height * 3, 1)))
    return ImageOps.autocontrast(enlarged)


def _crop_relative(image: Image.Image, window: tuple[float, float, float, float]) -> Image.Image:
    width, height = image.size
    left, top, right, bottom = window
    return image.crop((int(width * left), int(height * top), int(width * right), int(height * bottom)))


def _prepare_regions(image_path: str | Path) -> list[tuple[str, Image.Image]]:
    candidates = extract_card_candidates(image_path)
    card = candidates[0].image if candidates else Image.open(image_path).convert('RGB')
    rois = [
        ('header_window', _prepare_roi(_crop_relative(card, (0.08, 0.0, 0.92, 0.16)))),
        ('bottom_window', _prepare_roi(_crop_relative(card, (0.0, 0.82, 1.0, 1.0)))),
    ]
    return rois


def _tesseract_probe(regions: list[tuple[str, Image.Image]]) -> tuple[str, list[str]]:
    text_parts: list[str] = []
    tokens_seen: list[str] = []
    for _, roi in regions:
        try:
            text = pytesseract.image_to_string(roi, lang='eng', config='--psm 6')
        except pytesseract.TesseractNotFoundError:
            logger.warning('Tesseract binary is unavailable during game detection; defaulting to tokenless heuristic mode.')
            return '', []
        except pytesseract.TesseractError:
            continue
        normalized = ' '.join(text.split()).upper()
        if not normalized:
            continue
        text_parts.append(normalized)
        for token in _POKEMON_TOKENS + _ONEPIECE_TOKENS:
            if token in normalized and token not in tokens_seen:
                tokens_seen.append(token)
    return ' | '.join(text_parts), tokens_seen


def _heuristic_game_detection(regions: list[tuple[str, Image.Image]]) -> GameDetectionResult:
    probe_text, tokens_seen = _tesseract_probe(regions)
    pokemon_hits = sum(token in probe_text for token in _POKEMON_TOKENS)
    onepiece_hits = sum(token in probe_text for token in _ONEPIECE_TOKENS)

    if pokemon_hits >= max(onepiece_hits, 1):
        return GameDetectionResult(
            game='pokemon',
            confidence=0.8,
            reason='header and rules text look Pokémon-like',
            tokens_seen=tokens_seen,
        )
    if onepiece_hits >= 2 and pokemon_hits == 0:
        return GameDetectionResult(
            game='onepiece',
            confidence=0.7,
            reason='card text looks One Piece-like',
            tokens_seen=tokens_seen,
        )
    return GameDetectionResult(
        game='pokemon',
        confidence=0.35,
        reason='defaulted to Pokémon because no stronger game signal was found',
        tokens_seen=tokens_seen,
    )


def detect_game_from_image(image_path: str | Path) -> GameDetectionResult:
    """Detect the likely game without asking the seller up front."""

    regions = _prepare_regions(image_path)
    provider = get_config().ocr_provider
    if provider == 'openai_gpt4o_mini':
        logger.info('Skipping hosted game detection for %s and using heuristic-only mode for lower latency.', Path(image_path).name)
    return _heuristic_game_detection(regions)
