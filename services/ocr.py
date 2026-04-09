"""OCR services for TCG Listing Bot."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from config import get_config

logger = logging.getLogger(__name__)

_IDENTIFIER_PATTERN = re.compile(r'\b[A-Z]{2,5}\s*(?:EN|JP)?\s*\d{1,3}/\d{1,3}\b|\b\d{1,3}/\d{1,3}\b')


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


def _prepare_image(image_path: str | Path) -> Image.Image:
    """Load and preprocess a card image for general OCR."""

    image = Image.open(image_path).convert('RGB')
    grayscale = ImageOps.grayscale(image)
    contrast = ImageEnhance.Contrast(grayscale).enhance(2.4)
    sharpened = contrast.filter(ImageFilter.SHARPEN)
    enlarged = sharpened.resize((sharpened.width * 2, sharpened.height * 2))
    return ImageOps.autocontrast(enlarged)


def _bottom_left_identifier_crop(image: Image.Image) -> Image.Image:
    """Crop the lower-left region where set code / card number commonly appears."""

    width, height = image.size
    cropped = image.crop((0, int(height * 0.68), int(width * 0.42), height))
    enlarged = cropped.resize((max(cropped.width * 4, 1), max(cropped.height * 4, 1)))
    boosted = ImageEnhance.Contrast(enlarged).enhance(3.0)
    return ImageOps.autocontrast(boosted)


def _bottom_left_identifier_crop_tight(image: Image.Image) -> Image.Image:
    """Crop an even tighter lower-left lane for printed identifier recovery."""

    width, height = image.size
    cropped = image.crop((0, int(height * 0.76), int(width * 0.32), height))
    enlarged = cropped.resize((max(cropped.width * 5, 1), max(cropped.height * 5, 1)))
    boosted = ImageEnhance.Contrast(enlarged).enhance(3.4)
    return ImageOps.autocontrast(boosted)


def _full_text_crop(image: Image.Image) -> Image.Image:
    """Keep a broader view for name and larger text OCR."""

    width, height = image.size
    cropped = image.crop((0, 0, width, int(height * 0.88)))
    enlarged = cropped.resize((max(cropped.width * 2, 1), max(cropped.height * 2, 1)))
    return ImageOps.autocontrast(enlarged)


def _normalize_text(text: str) -> str:
    return ' '.join(text.split())


def _ocr_identifier_passes(image: Image.Image) -> list[str]:
    """Run OCR only for the printed identifier lane.

    This deliberately avoids JP OCR because the identifier lane is primarily alphanumeric.
    """

    configs = [
        '--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/ ',
        '--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/ ',
        '--psm 11 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/ ',
    ]
    outputs: list[str] = []
    for config in configs:
        try:
            text = pytesseract.image_to_string(image, lang='eng', config=config)
        except pytesseract.TesseractError:
            continue
        normalized = _normalize_text(text).upper()
        if normalized:
            outputs.append(normalized)
    return outputs


def _ocr_name_passes(image: Image.Image) -> list[str]:
    """Run broader OCR for names/text, separated by language lane."""

    configs = [
        ('eng', '--psm 6'),
        ('eng', '--psm 11'),
        ('jpn+jpn_vert', '--psm 6'),
        ('jpn+jpn_vert', '--psm 11'),
    ]
    outputs: list[str] = []
    for lang, config in configs:
        try:
            text = pytesseract.image_to_string(image, lang=lang, config=config)
        except pytesseract.TesseractError:
            continue
        normalized = _normalize_text(text)
        if normalized:
            prefix = 'NAME_EN' if lang == 'eng' else 'NAME_JP'
            outputs.append(f'{prefix}: {normalized}')
    return outputs


def _select_best_identifier(chunks: list[str]) -> str:
    """Pick the most useful identifier chunk from OCR outputs."""

    best_chunk = ''
    best_score = -1
    for chunk in chunks:
        match = _IDENTIFIER_PATTERN.search(chunk)
        score = 0
        if match:
            score += 100 + len(match.group(0))
        score += sum(char.isdigit() for char in chunk)
        score += sum(char.isalpha() for char in chunk)
        if score > best_score:
            best_score = score
            best_chunk = match.group(0) if match else chunk
    return best_chunk.strip()


def _dedupe_text_chunks(chunks: list[str]) -> str:
    """Combine OCR snippets while keeping only unique chunks."""

    seen: set[str] = set()
    unique_chunks: list[str] = []
    for chunk in chunks:
        normalized = chunk.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_chunks.append(normalized)
    return ' | '.join(unique_chunks)


def extract_text_from_image(image_path: str | Path) -> OCRResult:
    """Run OCR against a local image using the configured provider."""

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
        processed = _prepare_image(path)
        identifier_crop = _bottom_left_identifier_crop(processed)
        identifier_crop_tight = _bottom_left_identifier_crop_tight(processed)
        full_text_crop = _full_text_crop(processed)

        identifier_chunks = []
        identifier_chunks.extend(_ocr_identifier_passes(identifier_crop))
        identifier_chunks.extend(_ocr_identifier_passes(identifier_crop_tight))
        best_identifier = _select_best_identifier(identifier_chunks)

        name_chunks = _ocr_name_passes(full_text_crop)
        text_chunks = []
        if best_identifier:
            text_chunks.append(f'IDENTIFIER: {best_identifier}')
        text_chunks.extend(name_chunks)
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
