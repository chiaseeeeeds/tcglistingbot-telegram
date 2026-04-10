"""OCR services for TCG Listing Bot."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from tempfile import gettempdir

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from config import get_config
from services.card_detection import detect_and_rectify_card

logger = logging.getLogger(__name__)

_IDENTIFIER_PATTERN = re.compile(r'\b[A-Z]{2,5}\s*(?:EN|JP)?\s*\d{1,3}/\d{1,3}\b|\b\d{1,3}/\d{1,3}\b')
_STRICT_IDENTIFIER_PATTERN = re.compile(r'^(?:[A-Z]{2,5}\s*(?:EN|JP)?\s*)?\d{1,3}/\d{1,3}$')

_POKEMON_IDENTIFIER_WINDOWS: list[tuple[float, float, float, float]] = [
    (0.01, 0.88, 0.30, 0.985),
    (0.00, 0.86, 0.33, 0.99),
    (0.03, 0.90, 0.26, 0.99),
    (0.02, 0.91, 0.23, 0.985),
]
_GENERIC_IDENTIFIER_WINDOWS: list[tuple[float, float, float, float]] = [
    (0.00, 0.84, 0.35, 0.99),
    (0.01, 0.88, 0.28, 0.985),
]
_DEBUG_DIR = Path(gettempdir()) / 'tcg-listing-bot-ocr-debug'


class OCRNotConfiguredError(RuntimeError):
    """Raised when the selected OCR provider is unavailable or not configured."""


@dataclass(frozen=True)
class OCRResult:
    """Best-effort OCR output extracted from a seller photo."""

    text: str
    provider: str
    warnings: list[str]


def get_ocr_provider_name() -> str:
    """Return the configured OCR provider name for runtime selection logic."""

    return get_config().ocr_provider


def _prepare_roi(image: Image.Image) -> Image.Image:
    grayscale = ImageOps.grayscale(image)
    contrast = ImageEnhance.Contrast(grayscale).enhance(3.5)
    sharpened = contrast.filter(ImageFilter.SHARPEN)
    enlarged = sharpened.resize((max(sharpened.width * 6, 1), max(sharpened.height * 6, 1)))
    return ImageOps.autocontrast(enlarged)


def _crop_relative(image: Image.Image, window: tuple[float, float, float, float]) -> Image.Image:
    width, height = image.size
    left, top, right, bottom = window
    return image.crop(
        (
            int(width * left),
            int(height * top),
            int(width * right),
            int(height * bottom),
        )
    )


def _identifier_windows_for_game(game: str | None) -> list[tuple[float, float, float, float]]:
    if game == 'pokemon':
        return _POKEMON_IDENTIFIER_WINDOWS
    return _GENERIC_IDENTIFIER_WINDOWS


def _normalize_text(text: str) -> str:
    return ' '.join(text.split())


def _ocr_identifier_passes(image: Image.Image) -> list[str]:
    configs = [
        '--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/ ',
        '--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/ ',
        '--psm 11 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/ ',
    ]
    variants = [
        image,
        ImageOps.invert(image),
        image.point(lambda pixel: 255 if pixel > 150 else 0),
    ]
    outputs: list[str] = []
    for variant in variants:
        for config in configs:
            try:
                text = pytesseract.image_to_string(variant, lang='eng', config=config)
            except pytesseract.TesseractError:
                continue
            normalized = _normalize_text(text).upper()
            if normalized:
                outputs.append(normalized)
    return outputs


def _select_best_identifier(chunks: list[str]) -> str:
    best_chunk = ''
    best_score = -1
    for chunk in chunks:
        match = _IDENTIFIER_PATTERN.search(chunk)
        strict_match = bool(match and _STRICT_IDENTIFIER_PATTERN.match(match.group(0).strip()))
        score = 0
        if strict_match and match:
            score += 120 + len(match.group(0))
        elif match:
            score += 30 + len(match.group(0))
        score += sum(char.isdigit() for char in chunk) * 2
        score -= max(sum(char.isalpha() for char in chunk) - 6, 0)
        if score > best_score:
            best_score = score
            best_chunk = match.group(0) if match else chunk
    selected = best_chunk.strip()
    if selected and not _IDENTIFIER_PATTERN.search(selected):
        return ''
    return selected


def _write_debug_artifacts(
    *,
    source_path: Path,
    card_image: Image.Image,
    rois: list[Image.Image],
    outputs: list[str],
) -> None:
    debug_root = _DEBUG_DIR / source_path.stem
    debug_root.mkdir(parents=True, exist_ok=True)
    card_image.save(debug_root / 'rectified_card.png')
    for index, roi in enumerate(rois, start=1):
        roi.save(debug_root / f'roi_{index}.png')
    (debug_root / 'ocr_outputs.txt').write_text('\n'.join(outputs))


def _dedupe_text_chunks(chunks: list[str]) -> str:
    seen: set[str] = set()
    unique_chunks: list[str] = []
    for chunk in chunks:
        normalized = chunk.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_chunks.append(normalized)
    return ' | '.join(unique_chunks)


def extract_text_from_image(image_path: str | Path, *, game: str | None = None) -> OCRResult:
    """Run OCR against a local image using game-specific card-relative ROIs."""

    provider = get_ocr_provider_name()
    if provider != 'tesseract':
        raise OCRNotConfiguredError(
            f"OCR provider '{provider}' is not implemented yet in this environment."
        )

    warnings: list[str] = []
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f'OCR image not found: {path}')

    try:
        detection = detect_and_rectify_card(path)
        if not detection.detected:
            warnings.append(
                'I could not isolate the card cleanly from the photo, so OCR may be weaker than expected.'
            )
        else:
            logger.info(
                'Card detection succeeded for %s via %s (confidence=%s).',
                path.name,
                detection.method,
                detection.confidence,
            )
        card_image = detection.image
        windows = _identifier_windows_for_game(game)

        identifier_chunks: list[str] = []
        debug_rois: list[Image.Image] = []
        for window in windows:
            roi = _prepare_roi(_crop_relative(card_image, window))
            debug_rois.append(roi)
            identifier_chunks.extend(_ocr_identifier_passes(roi))
        _write_debug_artifacts(
            source_path=path,
            card_image=card_image,
            rois=debug_rois,
            outputs=identifier_chunks,
        )
        best_identifier = _select_best_identifier(identifier_chunks)

        text_chunks: list[str] = []
        if best_identifier:
            text_chunks.append(f'IDENTIFIER: {best_identifier}')
        normalized = _dedupe_text_chunks(text_chunks)
    except pytesseract.TesseractNotFoundError as exc:
        raise OCRNotConfiguredError('Tesseract is not installed on the runtime host.') from exc
    except Exception as exc:
        logger.exception('OCR failed for image %s: %s', path, exc)
        raise RuntimeError(f'OCR failed for image {path.name}.') from exc

    if len(normalized) < 4:
        warnings.append('OCR returned very little text. A clearer photo may help.')
    if not best_identifier:
        warnings.append('Printed identifier was not detected. Try a tighter crop with the bottom-left corner visible.')

    return OCRResult(text=normalized, provider=provider, warnings=warnings)
