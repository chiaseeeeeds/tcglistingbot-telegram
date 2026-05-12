"""OCR services for TCG Listing Bot."""

from __future__ import annotations

import io
import logging
import re
from collections import Counter
from functools import lru_cache
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import gettempdir
from time import perf_counter

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from config import get_config
from db.cards import list_cards_for_game
from services.card_detection import CardImageCandidate, extract_card_candidates
from services.openai_ocr import (
    OpenAIOCRBatchResult,
    OpenAIOCRError,
    OpenAIOCRRequestError,
    OpenAIOCRSchemaError,
    OpenAIOCRRegion,
    extract_card_text_from_regions,
)
from services.ocr_signals import OCRSignal, OCRStructuredResult, render_legacy_ocr_text

logger = logging.getLogger(__name__)

_IDENTIFIER_PATTERN = re.compile(r'\b[A-Z]{2,5}\s*(?:EN|JP)?\s*\d{1,3}/\d{1,3}\b|\b\d{1,3}/\d{1,3}\b')
_STRICT_IDENTIFIER_PATTERN = re.compile(r'^(?:[A-Z]{2,5}\s*(?:EN|JP)?\s*)?\d{1,3}/\d{1,3}$')
_SET_CODE_RATIO_PATTERN = re.compile(r'\b([A-Z0-9]{2,5})\s*(?:EN|JP)?\s*(\d{1,3}/\d{1,3})\b')
_RATIO_PATTERN = re.compile(r'\b(\d{1,3}/\d{1,3})\b')
_COMPACT_RATIO_PATTERN = re.compile(r'(?<!\d)(\d{6})(?!\d)')
_NOISY_COMPACT_RATIO_PATTERN = re.compile(r'(?<!\d)(\d{7})(?!\d)')
_LEGACY_SHORT_COMPACT_RATIO_PATTERN = re.compile(r'(?<!\d)(\d{4})(?!\d)')
_SET_CODE_TOKEN_PATTERN = re.compile(r'[A-Z0-9]{2,5}')
_SET_CODE_STOPWORDS = {
    'NAME', 'EN', 'JP', 'HP', 'EX', 'GX', 'VMAX', 'VSTAR', 'TAG', 'TEAM', 'ROCKET', 'ROCKETS',
    'ILLUS', 'WEAK', 'WEAKNESS', 'RESIST', 'RESISTANCE', 'BASIC', 'STAGE', 'ABILITY', 'TRAINER',
    'POKEMON', 'CARD', 'ATTACK', 'DAMAGE', 'ENERGY', 'RAR', 'RARE', 'HOLO', 'SPECIAL', 'ULTRA',
}

_POKEMON_IDENTIFIER_WINDOWS: list[tuple[float, float, float, float]] = [
    (0.01, 0.88, 0.30, 0.985),
    (0.00, 0.86, 0.33, 0.99),
    (0.03, 0.90, 0.26, 0.99),
    (0.02, 0.91, 0.23, 0.985),
    (0.00, 0.93, 0.20, 1.00),
    (0.66, 0.92, 0.99, 0.995),
    (0.58, 0.90, 0.99, 1.00),
    (0.48, 0.92, 0.99, 1.00),
    (0.35, 0.90, 0.99, 0.995),
]
_POKEMON_NAME_WINDOWS: list[tuple[float, float, float, float]] = [
    (0.10, 0.02, 0.72, 0.12),
    (0.08, 0.03, 0.74, 0.13),
    (0.12, 0.03, 0.64, 0.12),
    (0.14, 0.01, 0.72, 0.10),
]
_GENERIC_IDENTIFIER_WINDOWS: list[tuple[float, float, float, float]] = [
    (0.00, 0.84, 0.35, 0.99),
    (0.01, 0.88, 0.28, 0.985),
]
_POKEMON_LEGACY_RATIO_WINDOWS: list[tuple[float, float, float, float]] = [
    (0.77, 0.945, 0.89, 0.995),
    (0.74, 0.94, 0.90, 1.00),
    (0.78, 0.945, 0.90, 0.995),
]
_DEBUG_DIR = Path(gettempdir()) / 'tcg-listing-bot-ocr-debug'


class OCRNotConfiguredError(RuntimeError):
    """Raised when the selected OCR provider is unavailable or not configured."""


@dataclass(frozen=True)
class OCRResult:
    text: str
    provider: str
    model: str
    source: str
    requested_provider: str
    used_fallback: bool
    latency_ms: int
    warnings: list[str]
    structured: OCRStructuredResult
    debug_error: str = ''


@dataclass(frozen=True)
class _CandidateOCR:
    source: str
    provider: str
    model: str
    confidence: float
    text: str
    score: int
    identifier_chunks: list[str]
    name_chunks: list[str]
    card_image: Image.Image
    roi_images: list[Image.Image]
    roi_labels: list[str]
    identifier_layout_family: str
    warnings: list[str]
    debug_error: str = ''


@dataclass(frozen=True)
class _PreparedCandidateBatch:
    candidate_image: Image.Image
    roi_images: list[Image.Image]
    roi_labels: list[str]
    identifier_regions: list[tuple[str, Image.Image]]
    name_regions: list[tuple[str, Image.Image]]


def get_ocr_provider_name() -> str:
    return get_config().ocr_provider


@lru_cache(maxsize=4)
def _known_set_codes(game: str | None) -> set[str]:
    if not game:
        return set()
    return {
        str(row.get('set_code') or '').strip().upper()
        for row in list_cards_for_game(game)
        if str(row.get('set_code') or '').strip()
    }


def _prepare_identifier_roi(image: Image.Image) -> Image.Image:
    grayscale = ImageOps.grayscale(image)
    enlarged = grayscale.resize((max(grayscale.width * 6, 1), max(grayscale.height * 6, 1)))
    contrast = ImageEnhance.Contrast(enlarged).enhance(2.1)
    sharpened = contrast.filter(ImageFilter.SHARPEN)
    return ImageOps.autocontrast(sharpened)


def _prepare_name_roi(image: Image.Image) -> Image.Image:
    grayscale = ImageOps.grayscale(image)
    enlarged = grayscale.resize((max(grayscale.width * 5, 1), max(grayscale.height * 5, 1)))
    contrast = ImageEnhance.Contrast(enlarged).enhance(2.4)
    sharpened = contrast.filter(ImageFilter.SHARPEN)
    return ImageOps.autocontrast(sharpened)


def _crop_relative(image: Image.Image, window: tuple[float, float, float, float]) -> Image.Image:
    width, height = image.size
    left, top, right, bottom = window
    return image.crop((int(width * left), int(height * top), int(width * right), int(height * bottom)))


def _identifier_windows_for_game(game: str | None) -> list[tuple[float, float, float, float]]:
    if game == 'pokemon':
        return _POKEMON_IDENTIFIER_WINDOWS
    return _GENERIC_IDENTIFIER_WINDOWS


def _name_windows_for_game(game: str | None) -> list[tuple[float, float, float, float]]:
    if game == 'pokemon':
        return _POKEMON_NAME_WINDOWS
    return []


def _prepare_legacy_ratio_roi(image: Image.Image) -> Image.Image:
    return ImageOps.autocontrast(ImageOps.grayscale(image))


def _prepare_candidate_batch(*, candidate: CardImageCandidate, game: str | None) -> _PreparedCandidateBatch:
    roi_images: list[Image.Image] = []
    roi_labels: list[str] = []
    identifier_regions: list[tuple[str, Image.Image]] = []
    name_regions: list[tuple[str, Image.Image]] = []

    for index, window in enumerate(_identifier_windows_for_game(game), start=1):
        roi = _prepare_identifier_roi(_crop_relative(candidate.image, window))
        label = f'identifier_window_{index}'
        roi_images.append(roi)
        roi_labels.append(label)
        identifier_regions.append((label, roi))

    if game == 'pokemon':
        for index, legacy_window in enumerate(_POKEMON_LEGACY_RATIO_WINDOWS, start=1):
            roi = _prepare_legacy_ratio_roi(_crop_relative(candidate.image, legacy_window))
            label = f'legacy_ratio_window_{index}'
            roi_images.append(roi)
            roi_labels.append(label)
            identifier_regions.append((label, roi))

    for index, window in enumerate(_name_windows_for_game(game), start=1):
        roi = _prepare_name_roi(_crop_relative(candidate.image, window))
        label = f'name_window_{index}'
        roi_images.append(roi)
        roi_labels.append(label)
        name_regions.append((label, roi))

    return _PreparedCandidateBatch(
        candidate_image=candidate.image,
        roi_images=roi_images,
        roi_labels=roi_labels,
        identifier_regions=identifier_regions,
        name_regions=name_regions,
    )


def _prepare_openai_candidate_batch(*, image: Image.Image) -> _PreparedCandidateBatch:
    return _PreparedCandidateBatch(
        candidate_image=image,
        roi_images=[image],
        roi_labels=['raw_photo'],
        identifier_regions=[('raw_photo', image)],
        name_regions=[],
    )


def _normalize_text(text: str) -> str:
    return ' '.join(text.split())


def _signal_confidence(score: int, *, cap: int) -> float:
    if cap <= 0:
        return 0.0
    return round(min(max(score, 0) / cap, 0.99), 2)


def _split_identifier_text(identifier: str) -> tuple[str, str]:
    normalized = identifier.strip().upper()
    set_match = _SET_CODE_RATIO_PATTERN.search(normalized)
    if set_match:
        return set_match.group(1), set_match.group(2)
    ratio_match = _RATIO_PATTERN.search(normalized)
    if ratio_match:
        return '', ratio_match.group(1)
    return '', ''


def _extract_variant_tokens(name_text: str) -> list[str]:
    variant_terms = ['VMAX', 'VSTAR', 'GX', 'EX', 'V']
    upper_name = name_text.upper()
    return [term.lower() for term in variant_terms if re.search(rf'\b{re.escape(term)}\b', upper_name)]


def _build_structured_result(
    *,
    game: str | None,
    candidate: _CandidateOCR,
    best_identifier: str,
    identifier_score: int,
    best_name: str,
    name_score: int,
    all_identifier_chunks: list[str],
    all_name_chunks: list[str],
) -> OCRStructuredResult:
    layout_family = candidate.identifier_layout_family or ('pokemon_card_generic' if game == 'pokemon' else 'generic_card')
    signals: list[OCRSignal] = []
    identifier_conf = _signal_confidence(identifier_score, cap=220)
    name_conf = _signal_confidence(name_score, cap=80)

    if best_identifier:
        signals.append(OCRSignal(kind='identifier', value=best_identifier, confidence=identifier_conf, source=candidate.source, region='identifier'))
        set_code_text, printed_ratio = _split_identifier_text(best_identifier)
        if set_code_text:
            signals.append(OCRSignal(kind='set_code_text', value=set_code_text, confidence=identifier_conf, source=candidate.source, region='identifier'))
        if printed_ratio:
            signals.append(OCRSignal(kind='printed_ratio', value=printed_ratio, confidence=identifier_conf, source=candidate.source, region='identifier'))

    best_name_en, best_name_en_score = _select_best_name_for_prefix(all_name_chunks, prefix='NAME_EN')
    best_name_jp, best_name_jp_score = _select_best_name_for_prefix(all_name_chunks, prefix='NAME_JP')
    selected_name_values: list[tuple[str, str, int]] = []
    if best_name_en:
        selected_name_values.append(('name_en', best_name_en, best_name_en_score))
    if best_name_jp:
        selected_name_values.append(('name_jp', best_name_jp, best_name_jp_score))
    elif best_name:
        prefix, _, body = best_name.partition(':')
        kind = 'name_jp' if prefix.strip().upper() == 'NAME_JP' else 'name_en'
        body_text = body.strip() if body else best_name.strip()
        selected_name_values.append((kind, body_text, name_score))

    for kind, body_text, score_value in selected_name_values:
        body_text = body_text.strip()
        if not body_text:
            continue
        signal_confidence = _signal_confidence(score_value, cap=80)
        signals.append(
            OCRSignal(
                kind=kind,
                value=body_text,
                confidence=signal_confidence or name_conf,
                source=candidate.source,
                region='name',
            )
        )
        for token in _extract_variant_tokens(body_text):
            signals.append(
                OCRSignal(
                    kind='variant_token',
                    value=token,
                    confidence=signal_confidence or name_conf,
                    source=candidate.source,
                    region='name',
                )
            )

    raw_regions = [
        {'source': candidate.source, 'label': label}
        for label in candidate.roi_labels
    ]
    raw_chunks = {'identifier': list(all_identifier_chunks), 'name': list(all_name_chunks)}
    return OCRStructuredResult(
        layout_family=layout_family,
        selected_source=candidate.source,
        signals=signals,
        raw_regions=raw_regions,
        raw_chunks=raw_chunks,
    )


def _ocr_identifier_passes_tesseract(image: Image.Image) -> list[str]:
    line_config = '--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/ '
    block_config = '--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/ '
    sparse_config = '--psm 11 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/ '
    open_config = '--psm 6'
    primary_variants = [
        image,
        ImageOps.autocontrast(image),
        ImageEnhance.Contrast(image).enhance(1.8),
        image.point(lambda pixel: 255 if pixel > 168 else 0),
        image.point(lambda pixel: 255 if pixel > 148 else 0),
        ImageOps.invert(image),
    ]
    outputs: list[str] = []
    strict_hits = 0

    for variant in primary_variants:
        for config in (line_config, block_config, sparse_config, open_config):
            try:
                text = pytesseract.image_to_string(variant, lang='eng', config=config)
            except pytesseract.TesseractError:
                continue
            normalized = _normalize_text(text).upper()
            if not normalized:
                continue
            outputs.append(normalized)
            if _STRICT_IDENTIFIER_PATTERN.match(normalized):
                strict_hits += 1
                if strict_hits >= 1:
                    return outputs
            if _RATIO_PATTERN.search(normalized) or _COMPACT_RATIO_PATTERN.search(normalized.replace(' ', '')) or _NOISY_COMPACT_RATIO_PATTERN.search(normalized.replace(' ', '')):
                return outputs
    return outputs


def _useful_english_name(text: str) -> bool:
    tokens = re.findall(r'[A-Za-z]{3,}', text)
    if not tokens:
        return False
    return any(len(token) >= 5 for token in tokens)


def _ocr_name_passes_tesseract(image: Image.Image) -> list[str]:
    outputs: list[str] = []
    for config in ['--psm 7', '--psm 6']:
        try:
            text = pytesseract.image_to_string(image, lang='eng', config=config)
        except pytesseract.TesseractError:
            continue
        normalized = _normalize_text(text)
        if not normalized:
            continue
        outputs.append(f'NAME_EN: {normalized}')
        if _useful_english_name(normalized):
            return outputs
    try:
        text = pytesseract.image_to_string(image, lang='jpn+jpn_vert', config='--psm 7')
    except pytesseract.TesseractError:
        return outputs
    normalized = _normalize_text(text)
    if normalized:
        outputs.append(f'NAME_JP: {normalized}')
    return outputs


def _google_vision_text(image: Image.Image) -> str:
    try:
        from google.cloud import vision
    except Exception as exc:
        raise OCRNotConfiguredError('google-cloud-vision is not installed.') from exc
    client = vision.ImageAnnotatorClient()
    buf = io.BytesIO()
    image.save(buf, format='PNG')
    request_image = vision.Image(content=buf.getvalue())
    response = client.text_detection(image=request_image)
    if response.error.message:
        raise OCRNotConfiguredError(f'Google Vision OCR failed: {response.error.message}')
    annotations = response.text_annotations or []
    if not annotations:
        return ''
    return _normalize_text(annotations[0].description)


def _normalize_legacy_ratio_text(text: str) -> list[str]:
    normalized = _normalize_text(text).upper()
    if not normalized:
        return []
    candidates: list[str] = [normalized]
    compact = re.sub(r'[^0-9/]', '', normalized)
    if compact and compact != normalized:
        candidates.append(compact)
    recovered: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if _RATIO_PATTERN.search(candidate):
            recovered.append(candidate)
            continue
        short_match = _LEGACY_SHORT_COMPACT_RATIO_PATTERN.search(candidate)
        if short_match:
            digits = short_match.group(1)
            left = int(digits[:1])
            right = int(digits[1:])
            if 1 <= left <= right + 120 and 10 <= right <= 400:
                recovered.append(f'{digits[:1]}/{digits[1:]}')
    return recovered


def _ocr_legacy_ratio_pass(image: Image.Image) -> list[str]:
    outputs: list[str] = []
    base = ImageOps.autocontrast(ImageOps.grayscale(image))
    for scale in (6, 8):
        upscaled = base.resize((max(1, base.width * scale), max(1, base.height * scale)))
        variants = [
            ImageOps.autocontrast(upscaled),
            ImageEnhance.Contrast(upscaled).enhance(2.0).filter(ImageFilter.SHARPEN),
            upscaled.point(lambda p: 255 if p > 170 else 0),
        ]
        for variant in variants:
            for config in [
                '--psm 7 -c tessedit_char_whitelist=0123456789/',
                '--psm 6 -c tessedit_char_whitelist=0123456789/',
                '--psm 8 -c tessedit_char_whitelist=0123456789/',
            ]:
                try:
                    text = pytesseract.image_to_string(variant, lang='eng', config=config)
                except pytesseract.TesseractError:
                    continue
                outputs.extend(_normalize_legacy_ratio_text(text))
    return outputs


def _ocr_identifier_passes(image: Image.Image) -> list[str]:
    provider = get_ocr_provider_name()
    if provider == 'google_vision':
        text = _google_vision_text(image).upper()
        return [text] if text else []
    return _ocr_identifier_passes_tesseract(image)


def _ocr_name_passes(image: Image.Image) -> list[str]:
    provider = get_ocr_provider_name()
    if provider == 'google_vision':
        text = _google_vision_text(image)
        return [f'NAME_EN: {text}'] if text else []
    return _ocr_name_passes_tesseract(image)


def _combine_identifier_parts(*, set_code: str, ratio_text: str) -> str:
    set_code = _normalize_text(set_code).upper()
    ratio_text = _normalize_text(ratio_text).upper()
    if set_code and ratio_text:
        return f'{set_code} {ratio_text}'
    return set_code or ratio_text


def _best_guess_label(result: OpenAIOCRBatchResult) -> str:
    return result.best_guess.label.strip().lower()


def _layout_family_from_openai(*, game: str | None, result: OpenAIOCRBatchResult) -> str:
    if game != 'pokemon':
        return 'generic_identifier_zone'
    label = _best_guess_label(result)
    if label.startswith('legacy_ratio_window_'):
        return 'pokemon_legacy_bottom_right'
    if label.startswith('identifier_window_'):
        return 'pokemon_modern_identifier_zone'
    return 'pokemon_card_generic'


def _region_identifier_candidates(region: OpenAIOCRRegion) -> list[str]:
    candidates: list[str] = []
    identifier_text = _normalize_text(region.identifier_text).upper()
    combined_identifier = _combine_identifier_parts(
        set_code=region.set_code,
        ratio_text=region.ratio_text,
    )
    ratio_text = _normalize_text(region.ratio_text).upper()
    raw_text = _normalize_text(region.raw_text).upper()
    for value in (identifier_text, combined_identifier, ratio_text, raw_text):
        if value:
            candidates.append(value)
    return candidates


def _region_name_candidates(region: OpenAIOCRRegion) -> list[str]:
    candidates: list[str] = []
    name_en = _normalize_text(region.name_en)
    name_jp = _normalize_text(region.name_jp)
    if name_en:
        candidates.append(f'NAME_EN: {name_en}')
    if name_jp:
        candidates.append(f'NAME_JP: {name_jp}')
    return candidates


def _chunks_from_openai_result(result: OpenAIOCRBatchResult) -> tuple[list[str], list[str]]:
    identifier_chunks: list[str] = []
    name_chunks: list[str] = []

    for region in result.regions:
        identifier_chunks.extend(_region_identifier_candidates(region))
        name_chunks.extend(_region_name_candidates(region))

    identifier_chunks.extend(_region_identifier_candidates(result.best_guess))
    name_chunks.extend(_region_name_candidates(result.best_guess))
    return identifier_chunks, name_chunks


def _has_usable_openai_signals(identifier_chunks: list[str], name_chunks: list[str], *, game: str | None) -> bool:
    best_identifier, _ = _select_best_identifier(identifier_chunks, game=game)
    best_name, _ = _select_best_name(name_chunks)
    return bool(best_identifier or best_name)


def _candidate_set_codes(chunks: list[str], *, game: str | None) -> Counter[str]:
    scores: Counter[str] = Counter()
    known_codes = _known_set_codes(game)
    for chunk in chunks:
        upper_chunk = chunk.upper()
        is_strict = bool(_STRICT_IDENTIFIER_PATTERN.match(upper_chunk.strip()))
        explicit_matches = _SET_CODE_RATIO_PATTERN.findall(upper_chunk)
        for token, _ in explicit_matches:
            if token in _SET_CODE_STOPWORDS:
                continue
            if known_codes and token not in known_codes:
                continue
            if token.isdigit():
                continue
            score = 4
            if is_strict:
                score += 6
            if len(token) in {3, 4}:
                score += 1
            scores[token] += score

        if known_codes and (_RATIO_PATTERN.search(upper_chunk) or _COMPACT_RATIO_PATTERN.search(upper_chunk.replace(' ', ''))):
            compact = re.sub(r'[^A-Z0-9]', '', upper_chunk)
            for token in known_codes:
                if token in _SET_CODE_STOPWORDS:
                    continue
                if token.isdigit() or len(token) < 2:
                    continue
                if token not in compact:
                    continue
                score = 3
                if f'{token}EN' in compact or f'{token}JP' in compact:
                    score += 4
                if compact.endswith(token) or f'{token}EN' in compact[-8:] or f'{token}JP' in compact[-8:]:
                    score += 2
                if len(token) in {3, 4}:
                    score += 1
                scores[token] += score
    return scores


def _ratio_plausibility(ratio: str) -> int:
    if '/' not in ratio:
        return 0
    left_text, right_text = ratio.split('/', 1)
    try:
        left = int(left_text)
        right = int(right_text)
    except ValueError:
        return -120
    bonus = 0
    if right <= 0:
        return -120
    if right > 400:
        bonus -= 120
    elif right <= 250:
        bonus += 28
    if left > 999:
        bonus -= 120
    elif left <= right + 120:
        bonus += 26
    elif left <= right + 200:
        bonus += 4
    else:
        bonus -= 90
    if left <= 400:
        bonus += 10
    return bonus


def _ratio_sort_key(ratio: str) -> tuple[int, int, int, int]:
    left_text, _, right_text = ratio.partition('/')
    try:
        left = int(left_text)
        right = int(right_text)
    except ValueError:
        return (0, 0, 0, 0)
    return (len(left_text.lstrip('0') or '0'), left, -abs(right - left), right)


def _best_ratio(chunks: list[str]) -> tuple[str, int]:
    scores: Counter[str] = Counter()
    for chunk in chunks:
        upper_chunk = chunk.upper()
        match = _RATIO_PATTERN.search(upper_chunk)
        if match:
            ratio = match.group(1)
            scores[ratio] += 140 + _ratio_plausibility(ratio)
            continue
        compact_match = _COMPACT_RATIO_PATTERN.search(upper_chunk.replace(' ', ''))
        if compact_match:
            digits = compact_match.group(1)
            ratio = f'{digits[:3]}/{digits[3:]}'
            scores[ratio] += 80 + _ratio_plausibility(ratio)
        noisy_matches = _NOISY_COMPACT_RATIO_PATTERN.findall(upper_chunk.replace(' ', ''))
        for digits in noisy_matches:
            ratio = f'{digits[:3]}/{digits[-3:]}'
            scores[ratio] += 55 + _ratio_plausibility(ratio)
            for index in range(1, len(digits) - 1):
                repaired = digits[:index] + digits[index + 1:]
                if len(repaired) == 6:
                    repaired_ratio = f'{repaired[:3]}/{repaired[3:]}'
                    scores[repaired_ratio] += 20 + _ratio_plausibility(repaired_ratio)
    if not scores:
        return '', 0
    ratio = max(scores, key=lambda candidate: (scores[candidate], _ratio_sort_key(candidate)))
    score = scores[ratio]
    return ratio, score


def _select_best_identifier(chunks: list[str], *, game: str | None) -> tuple[str, int]:
    best_ratio, ratio_score = _best_ratio(chunks)
    code_scores = _candidate_set_codes(chunks, game=game)
    selected_code = ''
    code_score = 0
    if code_scores:
        candidate_code, candidate_score = code_scores.most_common(1)[0]
        if candidate_score >= 6:
            selected_code = candidate_code
            code_score = candidate_score
    if best_ratio and selected_code:
        return f'{selected_code} {best_ratio}', ratio_score + code_score
    if best_ratio:
        return best_ratio, ratio_score
    return '', 0


def _score_name_window(tokens: list[str], prefix: str) -> tuple[int, str]:
    stopwords = {'from', 'evolves', 'pokemon', 'ability', 'when', 'your', 'bench', 'damage', 'prevent', 'opponent', 'this', 'long', 'as', 'play', 'hand', 'turn', 'attach'}
    best_score = -1
    best_body = ''
    for start in range(len(tokens)):
        for length in range(1, min(4, len(tokens) - start) + 1):
            window_tokens = tokens[start:start + length]
            candidate_body = ' '.join(window_tokens)
            alpha_count = sum(char.isalpha() for char in candidate_body)
            stopword_hits = sum(token.lower() in stopwords for token in window_tokens)
            score = alpha_count * 2 + len(window_tokens) * 12 - stopword_hits * 24
            if 1 <= len(window_tokens) <= 3:
                score += 16
            if any(len(token) >= 6 for token in window_tokens):
                score += 8
            if any(token.upper() in {'EX', 'GX', 'VMAX', 'VSTAR', 'V'} for token in window_tokens):
                score += 18
            if score > best_score:
                best_score = score
                best_body = candidate_body
    return max(best_score, 0), f'{prefix}: {best_body}'.strip() if best_body else ''


def _select_best_name(chunks: list[str]) -> tuple[str, int]:
    best_chunk = ''
    best_score = -1
    for chunk in chunks:
        body = chunk.split(':', 1)[1].strip() if ':' in chunk else chunk.strip()
        prefix = chunk.split(':', 1)[0].strip() if ':' in chunk else 'NAME_EN'
        if prefix.upper() == 'NAME_JP':
            tokens = [body] if body else []
        else:
            tokens = re.findall(r'[A-Za-z]{2,}', body)
        if not tokens:
            continue
        score, candidate = _score_name_window(tokens, prefix)
        if score > best_score:
            best_score = score
            best_chunk = candidate
    return best_chunk.strip(), max(best_score, 0)


def _select_best_name_for_prefix(chunks: list[str], *, prefix: str) -> tuple[str, int]:
    filtered_chunks = [chunk for chunk in chunks if chunk.split(':', 1)[0].strip().upper() == prefix]
    best_chunk, best_score = _select_best_name(filtered_chunks)
    if not best_chunk:
        return '', 0
    _, _, body = best_chunk.partition(':')
    return body.strip() if body else best_chunk.strip(), best_score


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


def _write_debug_artifacts(*, source_path: Path, candidate: _CandidateOCR) -> None:
    debug_root = _DEBUG_DIR / source_path.stem / candidate.source
    debug_root.mkdir(parents=True, exist_ok=True)
    candidate.card_image.save(debug_root / 'card.png')
    for index, roi in enumerate(candidate.roi_images, start=1):
        label = candidate.roi_labels[index - 1] if index - 1 < len(candidate.roi_labels) else f'roi_{index}'
        safe_label = re.sub(r'[^a-zA-Z0-9_\-]+', '_', label)
        roi.save(debug_root / f'roi_{index}_{safe_label}.png')
    (debug_root / 'ocr_outputs.txt').write_text('\n'.join(candidate.identifier_chunks + candidate.name_chunks))
    (debug_root / 'summary.txt').write_text(
        f'source={candidate.source}\nprovider={candidate.provider}\nmodel={candidate.model}\nconfidence={candidate.confidence}\nscore={candidate.score}\ntext={candidate.text}\n'
    )



def _candidate_priority(candidate: CardImageCandidate) -> tuple[int, float]:
    detected_bonus = 1 if candidate.source.startswith('detected_') else 0
    source_bonus_map = {
        'center_medium': 5,
        'center_large': 4,
        'center_left': 3,
        'center_right': 2,
        'center_up': 1,
    }
    return (detected_bonus, candidate.confidence + source_bonus_map.get(candidate.source, 0) / 100)


def _select_finalists(candidates: list[CardImageCandidate]) -> list[CardImageCandidate]:
    unique_by_source: dict[str, CardImageCandidate] = {}
    for candidate in candidates:
        unique_by_source.setdefault(candidate.source, candidate)
    ranked = sorted(unique_by_source.values(), key=_candidate_priority, reverse=True)
    finalists: list[CardImageCandidate] = []
    detected = next((candidate for candidate in ranked if candidate.source.startswith('detected_')), None)
    if detected is not None:
        finalists.append(detected)
    for preferred_source in ['center_medium', 'center_large']:
        candidate = next((item for item in ranked if item.source == preferred_source), None)
        if candidate is not None and candidate not in finalists:
            finalists.append(candidate)
    for candidate in ranked:
        if candidate not in finalists:
            finalists.append(candidate)
        if len(finalists) >= 2:
            break
    return finalists[:2]


def _decisive_candidate(candidate: _CandidateOCR) -> bool:
    has_identifier = 'IDENTIFIER:' in candidate.text
    has_name = 'NAME_EN:' in candidate.text or 'NAME_JP:' in candidate.text
    return has_identifier and has_name and candidate.score >= 180


def _finalize_candidate_ocr(
    *,
    candidate: CardImageCandidate,
    provider: str,
    batch: _PreparedCandidateBatch,
    identifier_chunks: list[str],
    name_chunks: list[str],
    identifier_layout_family: str,
    game: str | None,
    warnings: list[str] | None = None,
    debug_error: str = '',
) -> _CandidateOCR:
    best_identifier, identifier_score = _select_best_identifier(identifier_chunks, game=game)
    best_name, name_score = _select_best_name(name_chunks)
    text = _dedupe_text_chunks([f'IDENTIFIER: {best_identifier}' if best_identifier else '', best_name])
    score = int(identifier_score * 3 + name_score + candidate.confidence * 20)
    if candidate.source.startswith('detected_'):
        score += 10
    if best_identifier and best_name:
        score += 40
    elif best_identifier:
        score += 25
    return _CandidateOCR(
        source=candidate.source,
        provider=provider,
        model=get_config().openai_ocr_model if provider == 'openai_gpt4o_mini' else provider,
        confidence=candidate.confidence,
        text=text,
        score=score,
        identifier_chunks=identifier_chunks,
        name_chunks=name_chunks,
        card_image=batch.candidate_image,
        roi_images=batch.roi_images,
        roi_labels=batch.roi_labels,
        identifier_layout_family=identifier_layout_family,
        warnings=list(warnings or []),
        debug_error=debug_error,
    )



def _empty_openai_candidate(
    *,
    candidate: CardImageCandidate,
    batch: _PreparedCandidateBatch,
    warning: str,
    debug_error: str = '',
) -> _CandidateOCR:
    return _finalize_candidate_ocr(
        candidate=candidate,
        provider='openai_gpt4o_mini',
        batch=batch,
        identifier_chunks=[],
        name_chunks=[],
        identifier_layout_family='generic_identifier_zone',
        game=None,
        warnings=[warning],
        debug_error=debug_error,
    )


def _openai_debug_error(exc: Exception) -> str:
    if isinstance(exc, OCRNotConfiguredError):
        return 'not_configured'
    if isinstance(exc, OpenAIOCRSchemaError):
        return 'schema'
    if isinstance(exc, OpenAIOCRRequestError):
        message = str(exc).lower()
        status_match = re.search(r'status\s+(\d{3})', message)
        if status_match:
            return f'http_{status_match.group(1)}'
        if 'timed out' in message:
            return 'timeout'
        if 'transport' in message:
            return 'transport'
        return 'request'
    return exc.__class__.__name__.lower()


def _score_candidate_with_tesseract(
    *,
    candidate: CardImageCandidate,
    batch: _PreparedCandidateBatch,
    game: str | None,
    warnings: list[str] | None = None,
) -> _CandidateOCR:
    identifier_chunks: list[str] = []
    best_identifier = ''
    identifier_score = 0
    identifier_layout_family = 'generic_identifier_zone'
    best_region_identifier_score = 0

    for label, roi in batch.identifier_regions:
        if label.startswith('legacy_ratio_window_'):
            region_chunks = _ocr_legacy_ratio_pass(roi)
        else:
            region_chunks = _ocr_identifier_passes_tesseract(roi)
        identifier_chunks.extend(region_chunks)
        region_best_identifier, region_identifier_score = _select_best_identifier(region_chunks, game=game)
        if region_best_identifier and region_identifier_score > best_region_identifier_score:
            best_region_identifier_score = region_identifier_score
            if game == 'pokemon' and label.startswith('legacy_ratio_window_'):
                identifier_layout_family = 'pokemon_legacy_bottom_right'
            elif game == 'pokemon':
                identifier_layout_family = 'pokemon_modern_identifier_zone'
        best_identifier, identifier_score = _select_best_identifier(identifier_chunks, game=game)
        if best_identifier and identifier_score >= 120 and not label.startswith('legacy_ratio_window_'):
            break

    name_chunks: list[str] = []
    best_name = ''
    name_score = 0
    for _, roi in batch.name_regions:
        name_chunks.extend(_ocr_name_passes_tesseract(roi))
        best_name, name_score = _select_best_name(name_chunks)
        if best_name and name_score >= 42:
            break

    return _finalize_candidate_ocr(
        candidate=candidate,
        provider='tesseract',
        batch=batch,
        identifier_chunks=identifier_chunks,
        name_chunks=name_chunks,
        identifier_layout_family=identifier_layout_family,
        game=game,
        warnings=warnings,
    )


def _score_candidate_with_current_provider(
    *,
    candidate: CardImageCandidate,
    batch: _PreparedCandidateBatch,
    game: str | None,
) -> _CandidateOCR:
    identifier_chunks: list[str] = []
    best_identifier = ''
    identifier_score = 0
    identifier_layout_family = 'generic_identifier_zone'
    best_region_identifier_score = 0

    for label, roi in batch.identifier_regions:
        if label.startswith('legacy_ratio_window_'):
            region_chunks = _ocr_legacy_ratio_pass(roi)
        else:
            region_chunks = _ocr_identifier_passes(roi)
        identifier_chunks.extend(region_chunks)
        region_best_identifier, region_identifier_score = _select_best_identifier(region_chunks, game=game)
        if region_best_identifier and region_identifier_score > best_region_identifier_score:
            best_region_identifier_score = region_identifier_score
            if game == 'pokemon' and label.startswith('legacy_ratio_window_'):
                identifier_layout_family = 'pokemon_legacy_bottom_right'
            elif game == 'pokemon':
                identifier_layout_family = 'pokemon_modern_identifier_zone'
        best_identifier, identifier_score = _select_best_identifier(identifier_chunks, game=game)
        if best_identifier and identifier_score >= 120 and not label.startswith('legacy_ratio_window_'):
            break

    name_chunks: list[str] = []
    best_name = ''
    name_score = 0
    for _, roi in batch.name_regions:
        name_chunks.extend(_ocr_name_passes(roi))
        best_name, name_score = _select_best_name(name_chunks)
        if best_name and name_score >= 42:
            break

    return _finalize_candidate_ocr(
        candidate=candidate,
        provider=get_ocr_provider_name(),
        batch=batch,
        identifier_chunks=identifier_chunks,
        name_chunks=name_chunks,
        identifier_layout_family=identifier_layout_family,
        game=game,
    )


def _score_candidate_with_openai(
    *,
    candidate: CardImageCandidate,
    batch: _PreparedCandidateBatch,
    game: str | None,
) -> _CandidateOCR:
    openai_result = extract_card_text_from_regions(batch.identifier_regions)
    if not openai_result.regions:
        return _empty_openai_candidate(
            candidate=candidate,
            batch=batch,
            warning='Hosted OCR returned no structured regions.',
        )
    identifier_chunks, name_chunks = _chunks_from_openai_result(openai_result)
    if not _has_usable_openai_signals(identifier_chunks, name_chunks, game=game):
        return _empty_openai_candidate(
            candidate=candidate,
            batch=batch,
            warning='Hosted OCR could not read enough visible card text from the raw photo.',
        )
    return _finalize_candidate_ocr(
        candidate=candidate,
        provider='openai_gpt4o_mini',
        batch=batch,
        identifier_chunks=identifier_chunks,
        name_chunks=name_chunks,
        identifier_layout_family=_layout_family_from_openai(game=game, result=openai_result),
        game=game,
        warnings=openai_result.warnings,
    )


def _score_candidate(*, source_path: Path, candidate: CardImageCandidate, game: str | None) -> _CandidateOCR:
    provider = get_ocr_provider_name()
    if provider == 'openai_gpt4o_mini':
        batch = _prepare_openai_candidate_batch(image=candidate.image)
        try:
            return _score_candidate_with_openai(candidate=candidate, batch=batch, game=game)
        except (OpenAIOCRError, OCRNotConfiguredError) as exc:
            logger.warning(
                'OpenAI OCR failed for image=%s provider=%s candidate=%s reason=%s',
                source_path.name,
                provider,
                candidate.source,
                exc,
            )
            return _empty_openai_candidate(
                candidate=candidate,
                batch=batch,
                warning='Hosted OCR failed before text could be extracted.',
                debug_error=_openai_debug_error(exc),
            )
    batch = _prepare_candidate_batch(candidate=candidate, game=game)
    return _score_candidate_with_current_provider(candidate=candidate, batch=batch, game=game)


def extract_text_from_image(image_path: str | Path, *, game: str | None = None) -> OCRResult:
    started_at = perf_counter()
    provider = get_ocr_provider_name()
    if provider not in {'openai_gpt4o_mini', 'tesseract', 'google_vision'}:
        raise OCRNotConfiguredError(f"OCR provider '{provider}' is not implemented yet in this environment.")
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f'OCR image not found: {path}')
    try:
        if provider == 'openai_gpt4o_mini':
            with Image.open(path).convert('RGB') as source_image:
                raw_candidate = CardImageCandidate(
                    image=source_image.copy(),
                    source='raw_photo',
                    confidence=1.0,
                )
            finalists = [raw_candidate]
        else:
            candidates = extract_card_candidates(path)
            finalists = _select_finalists(candidates)
        scored_candidates: list[_CandidateOCR] = []
        for candidate in finalists:
            scored = _score_candidate(source_path=path, candidate=candidate, game=game)
            scored_candidates.append(scored)
            if _decisive_candidate(scored):
                break
        best_candidate = max(scored_candidates, key=lambda item: item.score)
        all_identifier_chunks = [chunk for candidate in scored_candidates for chunk in candidate.identifier_chunks]
        all_name_chunks = [chunk for candidate in scored_candidates for chunk in candidate.name_chunks]
        best_identifier, identifier_score = _select_best_identifier(all_identifier_chunks, game=game)
        best_name, name_score = _select_best_name(all_name_chunks)
        structured_result = _build_structured_result(
            game=game,
            candidate=best_candidate,
            best_identifier=best_identifier,
            identifier_score=identifier_score,
            best_name=best_name,
            name_score=name_score,
            all_identifier_chunks=all_identifier_chunks,
            all_name_chunks=all_name_chunks,
        )
        aggregated_text = render_legacy_ocr_text(structured_result)
        for candidate in scored_candidates:
            _write_debug_artifacts(source_path=path, candidate=candidate)
        logger.info(
            'OCR selected candidate %s for %s with score=%s provider=%s text=%s aggregated=%s layout=%s',
            best_candidate.source,
            path.name,
            best_candidate.score,
            best_candidate.provider,
            best_candidate.text,
            aggregated_text,
            structured_result.layout_family,
        )
    except pytesseract.TesseractNotFoundError as exc:
        raise OCRNotConfiguredError('Tesseract is not installed on the runtime host.') from exc
    except Exception as exc:
        logger.exception('OCR failed for image %s: %s', path, exc)
        raise RuntimeError(f'OCR failed for image {path.name}.') from exc
    warnings: list[str] = []
    for candidate in scored_candidates:
        warnings.extend(candidate.warnings)
    detected_sources = [candidate for candidate in scored_candidates if candidate.source.startswith('detected_')]
    if provider != 'openai_gpt4o_mini':
        if not detected_sources:
            warnings.append('I could not isolate the card perfectly, so I used fallback card crops as well.')
        elif not best_candidate.source.startswith('detected_'):
            warnings.append('I used a fallback centered card crop because the direct card detection result looked weaker.')
    if len(aggregated_text) < 4:
        warnings.append('OCR returned very little text. A clearer photo may help.')
    if 'IDENTIFIER:' not in aggregated_text:
        warnings.append('Printed identifier was not detected clearly. Manual code input may still help.')
    deduped_warnings = list(dict.fromkeys(warnings))
    latency_ms = int((perf_counter() - started_at) * 1000)
    return OCRResult(
        text=aggregated_text,
        provider=best_candidate.provider,
        model=best_candidate.model,
        source=best_candidate.source,
        requested_provider=provider,
        used_fallback=best_candidate.provider != provider,
        latency_ms=latency_ms,
        warnings=deduped_warnings,
        debug_error=best_candidate.debug_error,
        structured=structured_result,
    )
