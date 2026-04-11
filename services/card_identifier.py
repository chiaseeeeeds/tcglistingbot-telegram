"""Card identification helpers driven by OCR text and local catalog data."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from db.cards import list_cards_by_identifier, list_cards_for_game

_TOKEN_RE = re.compile(r'[A-Za-z0-9]+')
_CARD_RATIO_RE = re.compile(r'\b(\d{1,3})\s*/\s*(\d{1,3})\b')
_SET_BLOCK_RE = re.compile(r'\b([A-Z]{2,5})\s*(?:EN|JP)?\s*(\d{1,3}/\d{1,3})\b', re.IGNORECASE)
_MANUAL_IDENTIFIER_RE = re.compile(r'^\s*([A-Z]{2,5})\s+(\d{1,3}/\d{1,3})\s*$', re.IGNORECASE)
_COMPACT_RATIO_RE = re.compile(r'(?<!\d)(\d{6})(?!\d)')
_NAME_STOPWORDS = {'name', 'identifier', 'pokemon', 'trainer', 'energy', 'stage', 'basic', 'ability'}


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
    candidate_options: list[dict[str, Any]] = field(default_factory=list)


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
        if normalized.isalpha() and len(normalized) < 2:
            continue
        if normalized in _NAME_STOPWORDS:
            continue
        tokens.add(normalized)
    return tokens


def _extract_identifiers(raw_text: str) -> dict[str, str]:
    """Extract likely set code and printed card number from OCR text."""

    metadata: dict[str, str] = {}
    upper_text = raw_text.upper()
    set_match = _SET_BLOCK_RE.search(upper_text)
    if set_match:
        metadata['detected_set_code'] = set_match.group(1)
        metadata['detected_print_number'] = set_match.group(2).replace(' ', '')

    ratio_match = _CARD_RATIO_RE.search(raw_text)
    if ratio_match and 'detected_print_number' not in metadata:
        metadata['detected_print_number'] = f'{ratio_match.group(1)}/{ratio_match.group(2)}'

    if 'detected_print_number' not in metadata:
        compact_match = _COMPACT_RATIO_RE.search(upper_text.replace(' ', ''))
        if compact_match:
            digits = compact_match.group(1)
            metadata['detected_print_number'] = f'{digits[:3]}/{digits[3:]}'

    return metadata


def parse_manual_identifier(value: str) -> dict[str, str] | None:
    """Parse a manual seller identifier like `PAF 234/091`."""

    match = _MANUAL_IDENTIFIER_RE.match(value.strip().upper())
    if not match:
        return None
    return {
        'detected_set_code': match.group(1),
        'detected_print_number': match.group(2),
    }


def _fuzzy_name_overlap(raw_tokens: set[str], target_tokens: set[str]) -> tuple[set[str], set[str]]:
    exact = raw_tokens & target_tokens
    fuzzy: set[str] = set()
    for raw_token in raw_tokens:
        if raw_token in exact:
            continue
        for target_token in target_tokens:
            if target_token in exact or target_token in fuzzy:
                continue
            ratio = SequenceMatcher(None, raw_token, target_token).ratio()
            if (
                ratio >= 0.84
                or raw_token.startswith(target_token)
                or target_token.startswith(raw_token)
                or (len(target_token) >= 4 and target_token in raw_token)
                or (len(raw_token) >= 4 and raw_token in target_token)
            ):
                fuzzy.add(target_token)
                break
    return exact, fuzzy


def _display_name_for_card(card: dict[str, Any]) -> str:
    pieces = [str(card.get('card_name_en') or card.get('card_name_jp') or 'Unknown')]
    if card.get('variant'):
        pieces.append(str(card['variant']))
    if card.get('set_name'):
        pieces.append(f"({card['set_name']})")
    return ' '.join(pieces)


def _candidate_option(*, score: float, card: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    return {
        'card_id': str(card.get('id') or ''),
        'display_name': _display_name_for_card(card),
        'confidence': round(min(score, 0.99), 2),
        'set_code': str(card.get('set_code') or ''),
        'set_name': str(card.get('set_name') or ''),
        'card_number': str(card.get('card_number') or ''),
        'reasons': reasons[:3],
    }


def _top_candidate_options(contender_scores: list[tuple[float, dict[str, Any], list[str]]], *, limit: int = 3) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    ranked = sorted(contender_scores, key=lambda item: item[0], reverse=True)
    for score, card, reasons in ranked:
        if score < 0.22:
            continue
        card_id = str(card.get('id') or '')
        if not card_id or card_id in seen:
            continue
        seen.add(card_id)
        options.append(_candidate_option(score=score, card=card, reasons=reasons))
        if len(options) >= limit:
            break
    return options


def _score_identifier_candidates(
    *,
    raw_text: str,
    detected: dict[str, str],
    candidates: list[dict[str, str]],
) -> tuple[dict[str, str] | None, float, list[str]]:
    """Score exact set-code/card-number candidates using OCR name and variant hints."""

    raw_lower = raw_text.lower()
    raw_tokens = _tokenize(raw_text)
    best_card: dict[str, str] | None = None
    best_score = -1.0
    best_reasons: list[str] = []

    for card in candidates:
        card_name_en = str(card.get('card_name_en') or '')
        card_name_jp = str(card.get('card_name_jp') or '')
        variant = str(card.get('variant') or '')
        score = 0.0
        reasons = ['Set code and printed number matched the catalog.']

        english_tokens = _tokenize(card_name_en)
        japanese_tokens = _tokenize(card_name_jp)
        variant_tokens = _tokenize(variant)
        target_tokens = english_tokens | japanese_tokens | variant_tokens
        exact_overlap, fuzzy_overlap = _fuzzy_name_overlap(raw_tokens, target_tokens)
        if exact_overlap:
            token_score = min(len(exact_overlap) / max(len(target_tokens), 1), 1.0)
            score += token_score * 0.35
            reasons.append(f"Name token overlap: {', '.join(sorted(exact_overlap))}")
        if fuzzy_overlap:
            score += min(len(fuzzy_overlap) * 0.08, 0.2)
            reasons.append(f"OCR-similar name tokens: {', '.join(sorted(fuzzy_overlap))}")

        if variant and variant.lower() in raw_lower:
            score += 0.15
            reasons.append(f'Variant matched OCR text: {variant}')
        elif not variant:
            score += 0.08

        if card_name_en and len(card_name_en.strip()) >= 3 and card_name_en.lower() in raw_lower:
            score += 0.25
            reasons.append(f'Exact English name matched: {card_name_en}')

        if card_name_jp and len(card_name_jp.strip()) >= 2 and card_name_jp.lower() in raw_lower:
            score += 0.25
            reasons.append(f'Exact Japanese name matched: {card_name_jp}')

        if score > best_score:
            best_card = card
            best_score = score
            best_reasons = reasons

    if not candidates:
        return None, 0.0, []

    return best_card or candidates[0], min(0.78 + max(best_score, 0.0), 0.99), best_reasons or ['Set code and printed number matched the catalog.']


def identify_card_from_text(*, raw_text: str, game: str) -> CardIdentificationResult:
    """Match OCR text against the seeded local catalog for one game."""

    detected = _extract_identifiers(raw_text)
    detected_print_number = detected.get('detected_print_number', '')
    detected_left_number = detected_print_number.split('/')[0].lstrip('0') if detected_print_number else ''
    detected_set_code = detected.get('detected_set_code', '').upper()

    if detected_set_code and detected_left_number:
        identifier_candidates = list_cards_by_identifier(
            game=game,
            set_code=detected_set_code,
            card_number=detected_left_number,
        )
        if not identifier_candidates and detected_left_number:
            identifier_candidates = list_cards_by_identifier(
                game=game,
                set_code=detected_set_code,
                card_number=detected_left_number.zfill(3),
            )
        if identifier_candidates:
            matched_card, confidence, reasons = _score_identifier_candidates(
                raw_text=raw_text,
                detected=detected,
                candidates=identifier_candidates,
            )
            candidate_options = [
                _candidate_option(score=confidence, card=card, reasons=reasons if card == matched_card else ['Set code and printed number matched the catalog.'])
                for card in identifier_candidates[:3]
            ]
            if matched_card is not None:
                return CardIdentificationResult(
                    matched=True,
                    confidence=confidence,
                    display_name=_display_name_for_card(matched_card),
                    card_id=str(matched_card.get('id') or ''),
                    raw_text=raw_text,
                    match_reasons=reasons,
                    metadata={
                        'game': game,
                        'set_code': str(matched_card.get('set_code') or ''),
                        'card_number': str(matched_card.get('card_number') or ''),
                        'detected_print_number': detected_print_number,
                    },
                    candidate_options=candidate_options,
                )

    catalog = list_cards_for_game(game)
    if not catalog:
        return CardIdentificationResult(
            matched=False,
            confidence=0.0,
            display_name='Unknown card',
            card_id=None,
            raw_text=raw_text,
            match_reasons=['No catalog cards are loaded for this game yet.'],
            metadata={'game': game, **detected},
            candidate_options=[],
        )

    raw_lower = raw_text.lower()
    raw_tokens = _tokenize(raw_text)
    detected_print_number = detected.get('detected_print_number', '')
    detected_left_number = detected_print_number.split('/')[0].lstrip('0') if detected_print_number else ''
    detected_set_code = detected.get('detected_set_code', '').lower()

    best_score = 0.0
    best_card: dict[str, Any] | None = None
    best_reasons: list[str] = []
    contender_scores: list[tuple[float, dict[str, Any], list[str]]] = []

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
        target_tokens = english_tokens | japanese_tokens | variant_tokens

        exact_overlap, fuzzy_overlap = _fuzzy_name_overlap(raw_tokens, target_tokens)
        if exact_overlap:
            token_score = min(len(exact_overlap) / max(len(target_tokens), 1), 1.0)
            score += token_score * 0.5
            reasons.append(f"Name token overlap: {', '.join(sorted(exact_overlap))}")
        if fuzzy_overlap:
            score += min(len(fuzzy_overlap) * 0.09, 0.24)
            reasons.append(f"OCR-similar name tokens: {', '.join(sorted(fuzzy_overlap))}")

        if set_code and re.search(r'\b' + re.escape(set_code.lower()) + r'\b', raw_lower):
            score += 0.28
            reasons.append(f'Set code matched in OCR text: {set_code}')

        if detected_set_code and set_code and detected_set_code == set_code.lower():
            score += 0.4
            reasons.append(f'Detected set code matched identifier block: {set_code}')
        elif detected_set_code and set_code:
            score -= 0.14

        has_name_signal = bool(
            exact_overlap or fuzzy_overlap or (card_name_en and card_name_en.lower() in raw_lower) or (card_name_jp and card_name_jp.lower() in raw_lower)
        )
        allow_numeric_match = bool(
            (detected_set_code and set_code and detected_set_code == set_code.lower())
            or (len(detected_left_number) >= 1 and has_name_signal)
        )
        if allow_numeric_match and card_number and re.search(r'\b' + re.escape(card_number.lower()) + r'\b', raw_lower):
            score += 0.12
            reasons.append(f'Card number matched in OCR text: {card_number}')

        if allow_numeric_match and detected_left_number and card_number and detected_left_number == card_number.lstrip('0'):
            score += 0.38
            reasons.append(f'Printed number matched identifier block: {detected_print_number}')
        elif allow_numeric_match and detected_left_number and card_number and detected_left_number.zfill(len(card_number)) == card_number:
            score += 0.38
            reasons.append(f'Printed number matched identifier block: {detected_print_number}')
        elif detected_left_number and allow_numeric_match and card_number:
            score -= 0.25

        if card_name_en and len(card_name_en.strip()) >= 3 and card_name_en.lower() in raw_lower:
            score += 0.26
            reasons.append(f'Exact English name matched: {card_name_en}')

        if card_name_jp and len(card_name_jp.strip()) >= 2 and card_name_jp.lower() in raw_lower:
            score += 0.26
            reasons.append(f'Exact Japanese name matched: {card_name_jp}')

        contender_scores.append((score, card, reasons))
        if score > best_score:
            best_score = score
            best_card = card
            best_reasons = reasons

    candidate_options = _top_candidate_options(contender_scores)

    if best_card is None or best_score < 0.25:
        reasons = ['OCR text did not confidently match the local catalog.']
        if detected_print_number:
            reasons.append(f'Detected printed identifier: {detected_print_number}')
        if detected_set_code:
            reasons.append(f'Detected set code: {detected_set_code.upper()}')
        if candidate_options:
            reasons.append('I found a few possible name + number candidates you can choose from below.')
        return CardIdentificationResult(
            matched=False,
            confidence=best_score,
            display_name='Unknown card',
            card_id=None,
            raw_text=raw_text,
            match_reasons=reasons,
            metadata={'game': game, **detected},
            candidate_options=candidate_options,
        )

    best_name_key = str(best_card.get('card_name_en') or best_card.get('card_name_jp') or '').strip().lower()
    same_name_cards = [
        card for card in catalog
        if str(card.get('card_name_en') or card.get('card_name_jp') or '').strip().lower() == best_name_key
    ]
    near_best = [item for item in contender_scores if item[0] >= best_score - 0.08 and item[0] > 0.3]
    weak_identifier_support = not detected_set_code and len(detected_left_number) < 2

    if weak_identifier_support and len(same_name_cards) > 1:
        return CardIdentificationResult(
            matched=False,
            confidence=round(min(best_score, 0.99), 2),
            display_name='Unknown card',
            card_id=None,
            raw_text=raw_text,
            match_reasons=[
                'OCR found a plausible card name, but that name appears in multiple sets or variants.',
                'A clearer printed identifier is needed before I can auto-match safely.',
            ],
            metadata={'game': game, **detected},
            candidate_options=candidate_options,
        )

    try:
        detected_left_number_int = int(detected_left_number) if detected_left_number else 0
    except ValueError:
        detected_left_number_int = 0
    older_style_name_number_mode = not detected_set_code and 0 < detected_left_number_int <= 120
    close_competition = len(near_best) > 1 and (best_score - near_best[1][0] < 0.12) if len(near_best) > 1 else False
    if older_style_name_number_mode and (close_competition or best_score < 0.62):
        return CardIdentificationResult(
            matched=False,
            confidence=round(min(best_score, 0.99), 2),
            display_name='Unknown card',
            card_id=None,
            raw_text=raw_text,
            match_reasons=[
                'I found likely matches using name + printed number, but old-set cards are still ambiguous without set-symbol confirmation.',
                'Choose one of the shortlist options, or send the title manually if OCR picked the wrong one.',
            ],
            metadata={'game': game, **detected},
            candidate_options=candidate_options,
        )

    if not detected_set_code and detected_left_number and len(near_best) > 3 and best_score < 0.52:
        return CardIdentificationResult(
            matched=False,
            confidence=round(min(best_score, 0.99), 2),
            display_name='Unknown card',
            card_id=None,
            raw_text=raw_text,
            match_reasons=[
                'The printed number was seen, but too many catalog candidates remain close.',
                'A cleaner set code or clearer name OCR is needed to avoid a wrong auto-match.',
            ],
            metadata={'game': game, **detected},
            candidate_options=candidate_options,
        )

    return CardIdentificationResult(
        matched=True,
        confidence=round(min(best_score, 0.99), 2),
        display_name=_display_name_for_card(best_card),
        card_id=str(best_card['id']),
        raw_text=raw_text,
        match_reasons=best_reasons,
        metadata={
            'game': str(best_card.get('game') or game),
            'set_code': str(best_card.get('set_code') or ''),
            'card_number': str(best_card.get('card_number') or ''),
            **detected,
        },
        candidate_options=candidate_options,
    )
