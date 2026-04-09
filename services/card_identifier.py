"""Card identification helpers driven by OCR text and local catalog data."""

from __future__ import annotations

import re
from dataclasses import dataclass

from db.cards import list_cards_for_game

_TOKEN_RE = re.compile(r'[A-Za-z0-9]+')
_CARD_RATIO_RE = re.compile(r'\b(\d{1,3})\s*/\s*(\d{1,3})\b')
_SET_BLOCK_RE = re.compile(r'\b([A-Z]{2,5})\s*(?:EN|JP)?\s*(\d{1,3}/\d{1,3})\b', re.IGNORECASE)


@dataclass(frozen=True)
class CardIdentificationResult:
    """Best-effort local card match for a seller photo."""

    matched: bool
    confidence: float
    display_name: str
    card_id: str | None
    raw_text: str
    match_reasons: list[str]
    metadata: dict[str, str]


def _tokenize(value: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(value)}


def _extract_identifiers(raw_text: str) -> dict[str, str]:
    """Extract likely set code and printed card number from OCR text."""

    metadata: dict[str, str] = {}
    set_match = _SET_BLOCK_RE.search(raw_text.upper())
    if set_match:
        metadata['detected_set_code'] = set_match.group(1)
        metadata['detected_print_number'] = set_match.group(2).replace(' ', '')

    ratio_match = _CARD_RATIO_RE.search(raw_text)
    if ratio_match and 'detected_print_number' not in metadata:
        metadata['detected_print_number'] = f'{ratio_match.group(1)}/{ratio_match.group(2)}'

    return metadata


def identify_card_from_text(*, raw_text: str, game: str) -> CardIdentificationResult:
    """Match OCR text against the seeded local catalog for one game."""

    catalog = list_cards_for_game(game)
    detected = _extract_identifiers(raw_text)
    if not catalog:
        return CardIdentificationResult(
            matched=False,
            confidence=0.0,
            display_name='Unknown card',
            card_id=None,
            raw_text=raw_text,
            match_reasons=['No catalog cards are loaded for this game yet.'],
            metadata={'game': game, **detected},
        )

    raw_lower = raw_text.lower()
    raw_tokens = _tokenize(raw_text)
    detected_print_number = detected.get('detected_print_number', '')
    detected_left_number = detected_print_number.split('/')[0] if detected_print_number else ''
    detected_set_code = detected.get('detected_set_code', '').lower()

    best_score = 0.0
    best_card: dict[str, str] | None = None
    best_reasons: list[str] = []

    for card in catalog:
        card_name_en = str(card.get('card_name_en') or '')
        card_name_jp = str(card.get('card_name_jp') or '')
        set_code = str(card.get('set_code') or '')
        card_number = str(card.get('card_number') or '')
        variant = str(card.get('variant') or '')

        score = 0.0
        reasons: list[str] = []
        english_tokens = _tokenize(card_name_en)
        japanese_tokens = _tokenize(card_name_jp)
        variant_tokens = _tokenize(variant)

        overlap = raw_tokens & (english_tokens | japanese_tokens | variant_tokens)
        if overlap:
            token_score = min(len(overlap) / max(len(english_tokens | japanese_tokens | variant_tokens), 1), 1.0)
            score += token_score * 0.55
            reasons.append(f"Name token overlap: {', '.join(sorted(overlap))}")

        if set_code and set_code.lower() in raw_lower:
            score += 0.25
            reasons.append(f'Set code matched in OCR text: {set_code}')

        if detected_set_code and set_code and detected_set_code == set_code.lower():
            score += 0.35
            reasons.append(f'Detected set code matched identifier block: {set_code}')

        if card_number and card_number.lower() in raw_lower:
            score += 0.15
            reasons.append(f'Card number matched in OCR text: {card_number}')

        if detected_left_number and card_number and detected_left_number == card_number.lstrip('0'):
            score += 0.35
            reasons.append(f'Printed number matched identifier block: {detected_print_number}')
        elif detected_left_number and card_number and detected_left_number.zfill(len(card_number)) == card_number:
            score += 0.35
            reasons.append(f'Printed number matched identifier block: {detected_print_number}')

        if card_name_en and card_name_en.lower() in raw_lower:
            score += 0.2
            reasons.append(f'Exact English name matched: {card_name_en}')

        if card_name_jp and card_name_jp.lower() in raw_lower:
            score += 0.2
            reasons.append(f'Exact Japanese name matched: {card_name_jp}')

        if score > best_score:
            best_score = score
            best_card = card
            best_reasons = reasons

    if best_card is None or best_score < 0.2:
        reasons = ['OCR text did not confidently match the local catalog.']
        if detected_print_number:
            reasons.append(f'Detected printed identifier: {detected_print_number}')
        if detected_set_code:
            reasons.append(f'Detected set code: {detected_set_code.upper()}')
        return CardIdentificationResult(
            matched=False,
            confidence=best_score,
            display_name='Unknown card',
            card_id=None,
            raw_text=raw_text,
            match_reasons=reasons,
            metadata={'game': game, **detected},
        )

    pieces = [best_card.get('card_name_en') or best_card.get('card_name_jp') or 'Unknown']
    if best_card.get('variant'):
        pieces.append(str(best_card['variant']))
    if best_card.get('set_name'):
        pieces.append(f"({best_card['set_name']})")

    return CardIdentificationResult(
        matched=True,
        confidence=round(min(best_score, 0.99), 2),
        display_name=' '.join(pieces),
        card_id=str(best_card['id']),
        raw_text=raw_text,
        match_reasons=best_reasons,
        metadata={
            'game': str(best_card.get('game') or game),
            'set_code': str(best_card.get('set_code') or ''),
            'card_number': str(best_card.get('card_number') or ''),
            **detected,
        },
    )
