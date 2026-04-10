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
from services.card_detection import CardImageCandidate, extract_card_candidates

logger = logging.getLogger(__name__)

_IDENTIFIER_PATTERN = re.compile(r'\b[A-Z]{2,5}\s*(?:EN|JP)?\s*\d{1,3}/\d{1,3}\b|\b\d{1,3}/\d{1,3}\b')
_STRICT_IDENTIFIER_PATTERN = re.compile(r'^(?:[A-Z]{2,5}\s*(?:EN|JP)?\s*)?\d{1,3}/\d{1,3}$')

_POKEMON_IDENTIFIER_WINDOWS: list[tuple[float, float, float, float]] = [
    (0.01, 0.88, 0.30, 0.985),
    (0.00, 0.86, 0.33, 0.99),
    (0.03, 0.90, 0.26, 0.99),
    (0.02, 0.91, 0.23, 0.985),
]
_POKEMON_NAME_WINDOWS: list[tuple[float, float, float, float]] = [
    (0.16, 0.01, 0.58, 0.07),
    (0.14, 0.00, 0.62, 0.08),
    (0.14, 0.01, 0.72, 0.10),
    (0.11, 0.00, 0.78, 0.12),
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


@dataclass(frozen=True)
class _CandidateOCR:
    source: str
    confidence: float
    text: str
    score: int
    identifier_chunks: list[str]
    name_chunks: list[str]
    card_image: Image.Image
    roi_images: list[Image.Image]


def get_ocr_provider_name() -> str:
    return get_config().ocr_provider


def _prepare_identifier_roi(image: Image.Image) -> Image.Image:
    grayscale = ImageOps.grayscale(image)
    contrast = ImageEnhance.Contrast(grayscale).enhance(3.5)
    sharpened = contrast.filter(ImageFilter.SHARPEN)
    enlarged = sharpened.resize((max(sharpened.width * 6, 1), max(sharpened.height * 6, 1)))
    return ImageOps.autocontrast(enlarged)


def _prepare_name_roi(image: Image.Image) -> Image.Image:
    grayscale = ImageOps.grayscale(image)
    contrast = ImageEnhance.Contrast(grayscale).enhance(2.8)
    sharpened = contrast.filter(ImageFilter.SHARPEN)
    enlarged = sharpened.resize((max(sharpened.width * 4, 1), max(sharpened.height * 4, 1)))
    return ImageOps.autocontrast(sharpened.resize((max(enlarged.width, 1), max(enlarged.height, 1))))


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


def _name_windows_for_game(game: str | None) -> list[tuple[float, float, float, float]]:
    if game == 'pokemon':
        return _POKEMON_NAME_WINDOWS
    return []


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


def _ocr_name_passes(image: Image.Image) -> list[str]:
    configs = [
        ('eng', '--psm 7'),
        ('eng', '--psm 6'),
        ('jpn+jpn_vert', '--psm 7'),
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


def _select_best_identifier(chunks: list[str]) -> tuple[str, int]:
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
        return '', 0
    return selected, max(best_score, 0)


def _select_best_name(chunks: list[str]) -> tuple[str, int]:
    stopwords = {
        'from', 'evolves', 'pokemon', 'ability', 'when', 'your', 'bench', 'damage',
        'prevent', 'opponent', 'this', 'long', 'as', 'play', 'hand', 'turn', 'attach',
    }
    best_chunk = ''
    best_score = -1
    for chunk in chunks:
        body = chunk.split(':', 1)[1].strip() if ':' in chunk else chunk.strip()
        tokens = re.findall(r'[A-Za-z]{2,}', body)
        if not tokens:
            continue
        candidate_tokens = tokens[:4]
        candidate_body = ' '.join(candidate_tokens)
        alpha_count = sum(char.isalpha() for char in candidate_body)
        token_count = len(candidate_tokens)
        noise_chars = max(len(body) - alpha_count - candidate_body.count(' '), 0)
        stopword_hits = sum(token.lower() in stopwords for token in candidate_tokens)
        score = alpha_count * 2 + token_count * 10 - noise_chars * 3 - max(len(body) - 36, 0) * 4
        if 1 <= token_count <= 3:
            score += 18
        if 'EX' in candidate_body.upper():
            score += 24
        if stopword_hits:
            score -= stopword_hits * 22
        if candidate_tokens and len(candidate_tokens[0]) >= 6:
            score += 8
        if score > best_score:
            prefix = chunk.split(':', 1)[0].strip() if ':' in chunk else 'NAME_EN'
            best_score = score
            best_chunk = f'{prefix}: {candidate_body}'
    return best_chunk.strip(), max(best_score, 0)


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


def _write_debug_artifacts(
    *,
    source_path: Path,
    candidate: _CandidateOCR,
) -> None:
    debug_root = _DEBUG_DIR / source_path.stem / candidate.source
    debug_root.mkdir(parents=True, exist_ok=True)
    candidate.card_image.save(debug_root / 'card.png')
    for index, roi in enumerate(candidate.roi_images, start=1):
        roi.save(debug_root / f'roi_{index}.png')
    (debug_root / 'ocr_outputs.txt').write_text('\n'.join(candidate.identifier_chunks + candidate.name_chunks))
    (debug_root / 'summary.txt').write_text(
        f'source={candidate.source}\nconfidence={candidate.confidence}\nscore={candidate.score}\ntext={candidate.text}\n'
    )


def _quick_rank_candidate(*, candidate: CardImageCandidate, game: str | None) -> int:
    score = int(candidate.confidence * 20)
    windows = _name_windows_for_game(game)[:2]
    if not windows:
        return score
    for window in windows:
        roi = _prepare_name_roi(_crop_relative(candidate.image, window))
        try:
            text = pytesseract.image_to_string(roi, lang='eng', config='--psm 7')
        except pytesseract.TesseractError:
            continue
        normalized = _normalize_text(text)
        if not normalized:
            continue
        tokens = re.findall(r'[A-Za-z]{3,}', normalized)
        score += len(tokens) * 10
        if 'HP' in normalized.upper():
            score += 12
        if 'EX' in normalized.upper():
            score += 12
    if candidate.source.startswith('detected_'):
        score += 8
    return score


def _score_candidate(
    *,
    candidate: CardImageCandidate,
    game: str | None,
) -> _CandidateOCR:
    roi_images: list[Image.Image] = []
    identifier_chunks: list[str] = []
    for window in _identifier_windows_for_game(game):
        roi = _prepare_identifier_roi(_crop_relative(candidate.image, window))
        roi_images.append(roi)
        identifier_chunks.extend(_ocr_identifier_passes(roi))

    name_chunks: list[str] = []
    for window in _name_windows_for_game(game):
        roi = _prepare_name_roi(_crop_relative(candidate.image, window))
        roi_images.append(roi)
        name_chunks.extend(_ocr_name_passes(roi))

    best_identifier, identifier_score = _select_best_identifier(identifier_chunks)
    best_name, name_score = _select_best_name(name_chunks)

    text_chunks: list[str] = []
    if best_identifier:
        text_chunks.append(f'IDENTIFIER: {best_identifier}')
    if best_name:
        text_chunks.append(best_name)
    text = _dedupe_text_chunks(text_chunks)

    score = int(identifier_score * 3 + name_score + candidate.confidence * 20)
    if candidate.source.startswith('detected_'):
        score += 10
    if best_identifier and best_name:
        score += 40
    elif best_identifier:
        score += 25
    return _CandidateOCR(
        source=candidate.source,
        confidence=candidate.confidence,
        text=text,
        score=score,
        identifier_chunks=identifier_chunks,
        name_chunks=name_chunks,
        card_image=candidate.image,
        roi_images=roi_images,
    )


def extract_text_from_image(image_path: str | Path, *, game: str | None = None) -> OCRResult:
    """Run OCR against multiple normalized card candidates and choose the best result."""

    provider = get_ocr_provider_name()
    if provider != 'tesseract':
        raise OCRNotConfiguredError(
            f"OCR provider '{provider}' is not implemented yet in this environment."
        )

    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f'OCR image not found: {path}')

    try:
        candidates = extract_card_candidates(path)
        ranked_candidates = sorted(
            candidates,
            key=lambda candidate: _quick_rank_candidate(candidate=candidate, game=game),
            reverse=True,
        )
        finalists = ranked_candidates[:3]
        detected_finalists = [candidate for candidate in ranked_candidates if candidate.source.startswith('detected_')]
        if detected_finalists and detected_finalists[0] not in finalists:
            finalists = finalists[:2] + [detected_finalists[0]]
        scored_candidates = [_score_candidate(candidate=candidate, game=game) for candidate in finalists]
        best_candidate = max(scored_candidates, key=lambda item: item.score)
        all_identifier_chunks = [chunk for candidate in scored_candidates for chunk in candidate.identifier_chunks]
        all_name_chunks = [chunk for candidate in scored_candidates for chunk in candidate.name_chunks]
        best_identifier, _ = _select_best_identifier(all_identifier_chunks)
        best_name, _ = _select_best_name(all_name_chunks)
        aggregated_text = _dedupe_text_chunks(
            [
                f'IDENTIFIER: {best_identifier}' if best_identifier else '',
                best_name,
            ]
        )
        for candidate in scored_candidates:
            _write_debug_artifacts(source_path=path, candidate=candidate)
        logger.info(
            'OCR selected candidate %s for %s with score=%s text=%s aggregated=%s',
            best_candidate.source,
            path.name,
            best_candidate.score,
            best_candidate.text,
            aggregated_text,
        )
    except pytesseract.TesseractNotFoundError as exc:
        raise OCRNotConfiguredError('Tesseract is not installed on the runtime host.') from exc
    except Exception as exc:
        logger.exception('OCR failed for image %s: %s', path, exc)
        raise RuntimeError(f'OCR failed for image {path.name}.') from exc

    warnings: list[str] = []
    detected_sources = [candidate for candidate in scored_candidates if candidate.source.startswith('detected_')]
    if not detected_sources:
        warnings.append('I could not isolate the card perfectly, so I used fallback card crops as well.')
    elif not best_candidate.source.startswith('detected_'):
        warnings.append('I used a fallback centered card crop because the direct card detection result looked weaker.')

    if len(aggregated_text) < 4:
        warnings.append('OCR returned very little text. A clearer photo may help.')
    if 'IDENTIFIER:' not in aggregated_text:
        warnings.append('Printed identifier was not detected clearly. Manual code input may still help.')

    return OCRResult(text=aggregated_text, provider=provider, warnings=warnings)
