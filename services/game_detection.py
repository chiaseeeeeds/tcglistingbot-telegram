"""Best-effort game detection from a card photo."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from services.card_detection import extract_card_candidates


@dataclass(frozen=True)
class GameDetectionResult:
    game: str
    confidence: float
    reason: str


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


def detect_game_from_image(image_path: str | Path) -> GameDetectionResult:
    """Detect the likely game without asking the seller up front."""

    candidates = extract_card_candidates(image_path)
    card = candidates[0].image if candidates else Image.open(image_path).convert('RGB')
    rois = [
        _crop_relative(card, (0.08, 0.0, 0.92, 0.16)),
        _crop_relative(card, (0.0, 0.82, 1.0, 1.0)),
    ]

    text_parts: list[str] = []
    for roi in rois:
        prepared = _prepare_roi(roi)
        try:
            text = pytesseract.image_to_string(prepared, lang='eng', config='--psm 6')
        except pytesseract.TesseractError:
            continue
        normalized = ' '.join(text.split()).upper()
        if normalized:
            text_parts.append(normalized)
    probe_text = ' | '.join(text_parts)

    pokemon_hits = sum(token in probe_text for token in ['HP', 'STAGE', 'EVOLVES', 'WEAKNESS', 'RESISTANCE'])
    onepiece_hits = sum(token in probe_text for token in ['DON', 'COUNTER', 'CHARACTER', 'LEADER', 'TRIGGER'])

    if pokemon_hits >= max(onepiece_hits, 1):
        return GameDetectionResult(game='pokemon', confidence=0.8, reason='header and rules text look Pokémon-like')
    if onepiece_hits >= 2 and pokemon_hits == 0:
        return GameDetectionResult(game='onepiece', confidence=0.7, reason='card text looks One Piece-like')
    return GameDetectionResult(game='pokemon', confidence=0.35, reason='defaulted to Pokémon because no stronger game signal was found')
