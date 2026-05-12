"""Generic catalog candidate generation for OCR-backed card identification."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from services.ocr_signals import OCRStructuredResult

_TOKEN_RE = re.compile(r'[A-Za-z0-9]+|[\u3040-\u30ffー]+|[\u4e00-\u9fff]+')
_NAME_STOPWORDS = {'name', 'identifier', 'pokemon', 'trainer', 'energy', 'stage', 'basic', 'ability'}


def _normalize_token(token: str) -> str:
    normalized = token.lower().strip()
    normalized = normalized.replace('’', "'")
    normalized = normalized.rstrip("'s") if normalized.endswith("'s") else normalized
    normalized = normalized.replace('0', 'o').replace('1', 'l')
    return normalized


def _tokenize(value: str) -> set[str]:
    tokens: set[str] = set()
    for token in _TOKEN_RE.findall(value):
        normalized = _normalize_token(token)
        if not normalized:
            continue
        if normalized.isascii() and normalized.isalpha() and len(normalized) < 2:
            continue
        if normalized in _NAME_STOPWORDS:
            continue
        tokens.add(normalized)
    return tokens


def _structured_search_text(structured: OCRStructuredResult | None) -> str:
    if structured is None:
        return ''
    values: list[str] = []
    seen: set[str] = set()
    for signal in structured.signals:
        if signal.kind not in {'name_en', 'name_jp', 'set_name_text', 'set_code_text', 'variant_token', 'printed_ratio', 'identifier'}:
            continue
        value = str(signal.value or '').strip()
        if not value:
            continue
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        values.append(value)
    return ' '.join(values)


def build_search_text(*, raw_text: str, structured: OCRStructuredResult | None = None) -> str:
    return _structured_search_text(structured) or raw_text


def generate_catalog_candidates(
    *,
    game: str,
    catalog: list[dict[str, Any]],
    raw_text: str,
    structured: OCRStructuredResult | None,
    detected: dict[str, str],
) -> list[dict[str, Any]]:
    """Return a recall-oriented generic candidate pool for later scoring."""

    if not catalog:
        return []

    search_text = build_search_text(raw_text=raw_text, structured=structured)
    raw_lower = search_text.lower()
    raw_tokens = _tokenize(search_text)
    raw_words = list(dict.fromkeys([token for token in raw_tokens if len(token) >= 2]))

    detected_set_code = str(detected.get('detected_set_code') or '').strip().upper()
    detected_print_number = str(detected.get('detected_print_number') or '').strip()
    detected_left_number = detected_print_number.split('/', 1)[0].lstrip('0') if detected_print_number else ''
    detected_print_total = detected_print_number.split('/', 1)[1].lstrip('0') if '/' in detected_print_number else ''

    selected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def add(card: dict[str, Any]) -> None:
        card_id = str(card.get('id') or '')
        if not card_id or card_id in seen_ids:
            return
        seen_ids.add(card_id)
        selected.append(card)

    if detected_set_code and detected_left_number:
        for card in catalog:
            row_set_code = str(card.get('set_code') or '').strip().upper()
            row_number = str(card.get('card_number') or '').strip()
            row_number_unpadded = row_number.lstrip('0') or '0'
            if row_set_code == detected_set_code and row_number_unpadded == detected_left_number:
                add(card)

    if detected_left_number:
        for card in catalog:
            row_number = str(card.get('card_number') or '').strip()
            if (row_number.lstrip('0') or '0') == detected_left_number:
                add(card)

    if detected_set_code:
        for card in catalog:
            if str(card.get('set_code') or '').strip().upper() == detected_set_code:
                add(card)

    for card in catalog:
        card_name_en = str(card.get('card_name_en') or '')
        card_name_jp = str(card.get('card_name_jp') or '')
        variant = str(card.get('variant') or '')
        set_name = str(card.get('set_name') or '')
        target_tokens = _tokenize(card_name_en) | _tokenize(card_name_jp) | _tokenize(variant) | _tokenize(set_name)
        if not target_tokens:
            continue
        exact_overlap = raw_tokens & target_tokens
        fuzzy_match = False
        if not exact_overlap:
            for raw_token in raw_tokens:
                for target_token in target_tokens:
                    ratio = SequenceMatcher(None, raw_token, target_token).ratio()
                    if ratio >= 0.84 or raw_token.startswith(target_token) or target_token.startswith(raw_token):
                        fuzzy_match = True
                        break
                if fuzzy_match:
                    break
        exact_name_hit = bool(
            (card_name_en and len(card_name_en.strip()) >= 3 and card_name_en.lower() in raw_lower)
            or (card_name_jp and len(card_name_jp.strip()) >= 2 and card_name_jp.lower() in raw_lower)
            or (set_name and len(set_name.strip()) >= 4 and set_name.lower() in raw_lower)
        )
        word_match = False
        if not (exact_overlap or fuzzy_match or exact_name_hit):
            for raw_word in raw_words:
                for target_token in target_tokens:
                    if SequenceMatcher(None, raw_word, target_token).ratio() >= 0.9:
                        word_match = True
                        break
                if word_match:
                    break
        if exact_overlap or fuzzy_match or exact_name_hit or word_match:
            add(card)

    return selected or list(catalog)
