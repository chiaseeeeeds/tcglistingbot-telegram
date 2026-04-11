"""Set symbol matching helpers for older Pokémon cards."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from tempfile import gettempdir
from typing import Any

import cv2
import httpx
import numpy as np
from PIL import Image

from db.pokemon_sets import get_pokemon_set_by_code, get_pokemon_set_by_name
from services.card_detection import extract_card_candidates

logger = logging.getLogger(__name__)

_SYMBOL_CACHE_DIR = Path(gettempdir()) / 'tcg-listing-bot-set-symbols'
_CLASSIC_SET_SYMBOL_WINDOWS: list[tuple[float, float, float, float]] = [
    (0.68, 0.14, 0.92, 0.34),
    (0.68, 0.18, 0.92, 0.38),
    (0.64, 0.20, 0.88, 0.42),
    (0.70, 0.22, 0.94, 0.44),
]
_FALLBACK_SET_SYMBOL_WINDOWS: list[tuple[float, float, float, float]] = [
    (0.58, 0.18, 0.84, 0.40),
    (0.62, 0.24, 0.88, 0.46),
]
_SCALE_FACTORS = [0.55, 0.7, 0.85, 1.0, 1.15, 1.3]
_SYMBOL_HINT_MIN_SCORE = 0.34
_SYMBOL_REORDER_MIN_SCORE = 0.48
_SYMBOL_REORDER_MIN_MARGIN = 0.06


def _crop_relative(image: Image.Image, window: tuple[float, float, float, float]) -> Image.Image:
    width, height = image.size
    left, top, right, bottom = window
    return image.crop((int(width * left), int(height * top), int(width * right), int(height * bottom)))


def _best_card_image(image_path: str | Path) -> Image.Image:
    candidates = extract_card_candidates(image_path)
    detected = [candidate for candidate in candidates if candidate.source.startswith('detected_')]
    if detected:
        return detected[0].image
    return max(candidates, key=lambda candidate: candidate.confidence).image


def _download_symbol(symbol_url: str) -> Path | None:
    if not symbol_url:
        return None
    _SYMBOL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(symbol_url.split('?')[0]).suffix or '.png'
    filename = hashlib.sha256(symbol_url.encode('utf-8')).hexdigest() + suffix
    path = _SYMBOL_CACHE_DIR / filename
    if path.exists() and path.stat().st_size > 0:
        return path
    try:
        response = httpx.get(symbol_url, timeout=8, follow_redirects=True, headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()
        path.write_bytes(response.content)
        return path
    except Exception as exc:
        logger.info('Could not download set symbol %s: %s', symbol_url, exc)
        return None


def _prepare_search_region(image: Image.Image) -> np.ndarray:
    gray = cv2.cvtColor(np.array(image.convert('RGB')), cv2.COLOR_RGB2GRAY)
    enlarged = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    blurred = cv2.GaussianBlur(enlarged, (3, 3), 0)
    edges = cv2.Canny(blurred, 70, 180)
    return edges


def _prepare_symbol_template(path: Path) -> np.ndarray | None:
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        return None
    if len(image.shape) == 3 and image.shape[2] == 4:
        bgr = image[:, :, :3]
        alpha = image[:, :, 3]
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.bitwise_and(gray, gray, mask=alpha)
    elif len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    gray = cv2.copyMakeBorder(gray, 6, 6, 6, 6, cv2.BORDER_CONSTANT, value=255)
    edges = cv2.Canny(gray, 70, 180)
    if not np.any(edges):
        return None
    return edges


def _template_match_score(region: np.ndarray, template: np.ndarray) -> float:
    best = 0.0
    for scale in _SCALE_FACTORS:
        resized = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        if resized.shape[0] >= region.shape[0] or resized.shape[1] >= region.shape[1]:
            continue
        result = cv2.matchTemplate(region, resized, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        best = max(best, float(max_val))
    return best


def _candidate_set_record(option: dict[str, Any]) -> dict[str, Any] | None:
    set_code = str(option.get('set_code') or '').strip()
    if set_code:
        record = get_pokemon_set_by_code(set_code=set_code)
        if record is not None:
            return record
    set_name = str(option.get('set_name') or '').strip()
    if set_name:
        return get_pokemon_set_by_name(set_name=set_name)
    return None


def _build_search_regions(card_image: Image.Image) -> list[np.ndarray]:
    windows = _CLASSIC_SET_SYMBOL_WINDOWS + _FALLBACK_SET_SYMBOL_WINDOWS
    regions: list[np.ndarray] = []
    for window in windows:
        region = _prepare_search_region(_crop_relative(card_image, window))
        if np.any(region):
            regions.append(region)
    return regions


def _stable_enriched_options(enriched: list[dict[str, Any]], original_order: list[dict[str, Any]]) -> list[dict[str, Any]]:
    original_index = {str(option.get('card_id') or ''): index for index, option in enumerate(original_order)}
    return sorted(
        enriched,
        key=lambda option: (
            -float(option.get('confidence') or 0.0),
            original_index.get(str(option.get('card_id') or ''), 999),
        ),
    )


def _should_apply_rerank(enriched: list[dict[str, Any]]) -> bool:
    ranked_scores = sorted((float(option.get('symbol_score') or 0.0) for option in enriched), reverse=True)
    if not ranked_scores:
        return False
    best_score = ranked_scores[0]
    second_score = ranked_scores[1] if len(ranked_scores) > 1 else 0.0
    return best_score >= _SYMBOL_REORDER_MIN_SCORE and (best_score - second_score) >= _SYMBOL_REORDER_MIN_MARGIN


def rerank_candidate_options_by_symbol(*, image_path: str | Path, candidate_options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reorder candidate options using set symbol template matching when available."""

    if len(candidate_options) < 2:
        return candidate_options
    try:
        card_image = _best_card_image(image_path)
        search_regions = _build_search_regions(card_image)
        if not search_regions:
            return candidate_options
    except Exception as exc:
        logger.info('Could not prepare set symbol search region for %s: %s', image_path, exc)
        return candidate_options

    enriched: list[dict[str, Any]] = []
    for option in candidate_options:
        enriched_option = dict(option)
        set_record = _candidate_set_record(enriched_option)
        symbol_url = str((set_record or {}).get('symbol_image_url') or '')
        if not symbol_url:
            enriched_option['symbol_score'] = 0.0
            enriched.append(enriched_option)
            continue
        symbol_path = _download_symbol(symbol_url)
        if symbol_path is None:
            enriched_option['symbol_score'] = 0.0
            enriched.append(enriched_option)
            continue
        template = _prepare_symbol_template(symbol_path)
        if template is None:
            enriched_option['symbol_score'] = 0.0
            enriched.append(enriched_option)
            continue
        score = max(_template_match_score(region, template) for region in search_regions)
        enriched_option['symbol_score'] = round(score, 3)
        if score >= _SYMBOL_HINT_MIN_SCORE:
            reasons = list(enriched_option.get('reasons') or [])
            reasons.append(f'Set symbol similarity: {score:.2f}')
            enriched_option['reasons'] = reasons[:4]
        enriched.append(enriched_option)

    if _should_apply_rerank(enriched):
        logger.info(
            'Applying decisive symbol rerank for %s with scores=%s',
            image_path,
            [round(float(option.get('symbol_score') or 0.0), 3) for option in enriched],
        )
        return sorted(
            enriched,
            key=lambda option: (
                float(option.get('symbol_score') or 0.0),
                float(option.get('confidence') or 0.0),
            ),
            reverse=True,
        )

    logger.info(
        'Keeping original shortlist order for %s because symbol scores were not decisive: %s',
        image_path,
        [round(float(option.get('symbol_score') or 0.0), 3) for option in enriched],
    )
    return _stable_enriched_options(enriched, candidate_options)
