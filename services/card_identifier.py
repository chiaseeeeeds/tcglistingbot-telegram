"""Card identification helpers driven by OCR text and local catalog data."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any

from db.cards import list_cards_by_identifier, list_cards_for_game
from db.pokemon_sets import list_pokemon_sets

_TOKEN_RE = re.compile(r'[A-Za-z0-9]+')
_CARD_RATIO_RE = re.compile(r'\b(\d{1,3})\s*/\s*(\d{1,3})\b')
_SET_BLOCK_RE = re.compile(r'\b([A-Z0-9]{2,5})\s*(?:EN|JP)?\s*(\d{1,3}/\d{1,3})\b', re.IGNORECASE)
_MANUAL_IDENTIFIER_RE = re.compile(r'^\s*([A-Z0-9]{2,5})\s+(\d{1,3}/\d{1,3})\s*$', re.IGNORECASE)
_COMPACT_RATIO_RE = re.compile(r'(?<!\d)(\d{6})(?!\d)')
_SET_NAME_SPLIT_RE = re.compile(r'\s*[—–:/|]+\s*')
_NAME_STOPWORDS = {'name', 'identifier', 'pokemon', 'trainer', 'energy', 'stage', 'basic', 'ability'}
_SET_NAME_STOPWORDS = {'series', 'set', 'expansion', 'scarlet', 'violet', 'sun', 'moon', 'sword', 'shield', 'black', 'white'}
CARD_IDENTIFIER_BUILD_MARKER = 'card-identify-2026-04-12-structured-signals-v13'


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


def _normalize_phrase(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', value.lower()).strip()


def _set_aliases(set_name: str) -> list[str]:
    normalized = _normalize_phrase(set_name)
    if not normalized:
        return []

    aliases = [normalized]
    split_parts = [part for part in _SET_NAME_SPLIT_RE.split(set_name) if _normalize_phrase(part)]
    if len(split_parts) > 1:
        aliases.append(_normalize_phrase(split_parts[-1]))

    deduped: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        if alias in seen:
            continue
        seen.add(alias)
        deduped.append(alias)
    return deduped


@lru_cache(maxsize=1)
def _pokemon_set_match_entries() -> tuple[dict[str, Any], ...]:
    entries: list[dict[str, Any]] = []
    for set_record in list_pokemon_sets():
        set_name = str(set_record.get('set_name') or '').strip()
        set_code = str(set_record.get('set_code') or '').strip().upper()
        if not set_name or not set_code:
            continue
        for alias in _set_aliases(set_name):
            alias_tokens = [token for token in alias.split() if len(token) >= 3 and token not in _SET_NAME_STOPWORDS]
            if len(alias_tokens) < 2:
                continue
            entries.append(
                {
                    'set_code': set_code,
                    'set_name': set_name,
                    'alias': alias,
                    'alias_tokens': alias_tokens,
                }
            )
    return tuple(entries)


@lru_cache(maxsize=1)
def _pokemon_set_card_counts() -> dict[str, str]:
    counts: dict[str, str] = {}
    for set_record in list_pokemon_sets():
        set_code = str(set_record.get('set_code') or '').strip().upper()
        card_count = str(set_record.get('card_count') or '').strip()
        if not set_code or not card_count:
            continue
        counts[set_code] = card_count
    return counts


def _detect_pokemon_set_from_text(raw_text: str) -> dict[str, str]:
    raw_normalized = _normalize_phrase(raw_text)
    if len(raw_normalized) < 6:
        return {}
    raw_tokens = {token for token in raw_normalized.split() if len(token) >= 3}
    best_match: dict[str, str] = {}
    best_score = 0.0
    for entry in _pokemon_set_match_entries():
        set_name = str(entry['set_name'])
        set_code = str(entry['set_code'])
        alias = str(entry['alias'])
        set_token_set = set(entry['alias_tokens'])
        overlap = raw_tokens & set_token_set
        token_ratio = len(overlap) / max(len(set_token_set), 1)
        score = 0.0
        if alias in raw_normalized:
            score = 1.0
        elif len(overlap) >= 2 and token_ratio >= 0.67:
            score = 0.82 + min(len(overlap) * 0.05, 0.12)
        elif len(set_token_set) == 2 and overlap == set_token_set:
            score = 0.92
        if score > best_score:
            best_score = score
            best_match = {'detected_set_name': set_name, 'detected_set_code': set_code, 'detected_set_alias': alias}
    return best_match if best_score >= 0.82 else {}


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


def _extract_identifiers(raw_text: str, *, game: str | None = None) -> dict[str, str]:
    """Extract likely set code and printed card number from OCR text."""

    metadata: dict[str, str] = {}
    upper_text = raw_text.upper()
    set_match = _SET_BLOCK_RE.search(upper_text)
    if set_match:
        candidate_set_code = set_match.group(1).strip().upper()
        candidate_print_number = set_match.group(2).replace(' ', '')
        if not candidate_set_code.isdigit():
            metadata['detected_set_code'] = candidate_set_code
            metadata['detected_print_number'] = candidate_print_number

    ratio_match = _CARD_RATIO_RE.search(raw_text)
    if ratio_match and 'detected_print_number' not in metadata:
        metadata['detected_print_number'] = f'{ratio_match.group(1)}/{ratio_match.group(2)}'

    if 'detected_print_number' not in metadata:
        compact_match = _COMPACT_RATIO_RE.search(upper_text.replace(' ', ''))
        if compact_match:
            digits = compact_match.group(1)
            metadata['detected_print_number'] = f'{digits[:3]}/{digits[3:]}'

    if game == 'pokemon' and 'detected_set_code' not in metadata:
        metadata.update(_detect_pokemon_set_from_text(raw_text))

    return metadata


def parse_manual_identifier(value: str) -> dict[str, str] | None:
    """Parse a manual seller identifier like `ABC 123/456`."""

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




def _merged_name_overlap(raw_tokens: set[str], target_tokens: set[str]) -> set[str]:
    rescued: set[str] = set()
    for raw_token in raw_tokens:
        if len(raw_token) < 7 or not raw_token.isalpha():
            continue
        for target_token in target_tokens:
            if len(target_token) < 5 or not target_token.isalpha():
                continue
            ratio = SequenceMatcher(None, raw_token, target_token).ratio()
            if ratio >= 0.72:
                rescued.add(target_token)
                continue
            if len(raw_token) >= len(target_token) and target_token in raw_token:
                rescued.add(target_token)
    return rescued



def _strong_name_signal(*, raw_text: str, raw_tokens: set[str], card: dict[str, Any]) -> bool:
    raw_lower = raw_text.lower()
    card_name_en = str(card.get('card_name_en') or '')
    card_name_jp = str(card.get('card_name_jp') or '')
    variant = str(card.get('variant') or '')
    target_tokens = _tokenize(card_name_en) | _tokenize(card_name_jp) | _tokenize(variant)
    exact_overlap, fuzzy_overlap = _fuzzy_name_overlap(raw_tokens, target_tokens)
    merged_overlap = _merged_name_overlap(raw_tokens, target_tokens) - exact_overlap - fuzzy_overlap
    if exact_overlap or merged_overlap:
        return True
    if len(fuzzy_overlap) >= 2:
        return True
    if card_name_en and len(card_name_en.strip()) >= 4 and card_name_en.lower() in raw_lower:
        return True
    if card_name_jp and len(card_name_jp.strip()) >= 2 and card_name_jp.lower() in raw_lower:
        return True
    return False


def _detected_print_total(detected_print_number: str) -> str:
    if not detected_print_number or '/' not in detected_print_number:
        return ''
    return detected_print_number.split('/', 1)[1].strip().lstrip('0') or '0'



def _set_total_matches(*, set_code: str, detected_total: str) -> bool:
    if not set_code or not detected_total:
        return False
    raw_count = _pokemon_set_card_counts().get(set_code.strip().upper(), '')
    if not raw_count:
        return False
    normalized_total = detected_total.lstrip('0') or '0'
    return raw_count == normalized_total or raw_count.startswith(normalized_total)

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


def _name_only_shortlist(*, raw_text: str, catalog: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    raw_lower = raw_text.lower()
    raw_tokens = _tokenize(raw_text)
    raw_word_tokens = re.findall(r'[a-z]{4,}', raw_lower)
    contender_scores: list[tuple[float, dict[str, Any], list[str]]] = []
    for card in catalog:
        card_name_en = str(card.get('card_name_en') or '')
        card_name_jp = str(card.get('card_name_jp') or '')
        target_tokens = _tokenize(card_name_en) | _tokenize(card_name_jp)
        if not target_tokens:
            continue
        exact_overlap, fuzzy_overlap = _fuzzy_name_overlap(raw_tokens, target_tokens)
        merged_overlap = _merged_name_overlap(raw_tokens, target_tokens) - exact_overlap - fuzzy_overlap
        exact_name_hit = bool(
            (card_name_en and len(card_name_en.strip()) >= 3 and card_name_en.lower() in raw_lower)
            or (card_name_jp and len(card_name_jp.strip()) >= 2 and card_name_jp.lower() in raw_lower)
        )
        if not (exact_overlap or fuzzy_overlap or merged_overlap or exact_name_hit):
            continue
        score = 0.0
        reasons: list[str] = []
        if exact_overlap:
            score += min(len(exact_overlap) * 0.18, 0.30)
            reasons.append(f"Name token overlap: {', '.join(sorted(exact_overlap))}")
        if fuzzy_overlap:
            score += min(len(fuzzy_overlap) * 0.20, 0.28)
            reasons.append(f"OCR-similar name tokens: {', '.join(sorted(fuzzy_overlap))}")
        if merged_overlap and not fuzzy_overlap:
            score += min(len(merged_overlap) * 0.08, 0.12)
            reasons.append(f"Merged OCR name tokens resembled: {', '.join(sorted(merged_overlap))}")
        best_ratio = 0.0
        best_pair = ''
        for raw_token in raw_word_tokens:
            for target_token in target_tokens:
                ratio = SequenceMatcher(None, raw_token, target_token).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_pair = target_token
        if best_ratio >= 0.92:
            score += 0.30
            reasons.append(f'Primary OCR token strongly resembled: {best_pair}')
        elif best_ratio >= 0.84:
            score += 0.16
            reasons.append(f'Primary OCR token resembled: {best_pair}')
        if exact_name_hit:
            score += 0.25
            reasons.append('Exact card name text appeared in OCR.')
        contender_scores.append((score, card, reasons))
    options: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    ranked = sorted(contender_scores, key=lambda item: item[0], reverse=True)
    for score, card, reasons in ranked:
        if score < 0.12:
            continue
        option = _candidate_option(score=score, card=card, reasons=reasons)
        display_name = str(option.get('display_name') or '')
        display_key = display_name.split('(')[0].strip().lower()
        if display_key in seen_names:
            continue
        seen_names.add(display_key)
        options.append(option)
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
    detected_print_total = _detected_print_total(detected.get('detected_print_number', ''))
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
        merged_overlap = _merged_name_overlap(raw_tokens, target_tokens) - exact_overlap - fuzzy_overlap
        if exact_overlap:
            token_score = min(len(exact_overlap) / max(len(target_tokens), 1), 1.0)
            score += token_score * 0.35
            reasons.append(f"Name token overlap: {', '.join(sorted(exact_overlap))}")
        if fuzzy_overlap:
            score += min(len(fuzzy_overlap) * 0.08, 0.2)
            reasons.append(f"OCR-similar name tokens: {', '.join(sorted(fuzzy_overlap))}")
        if merged_overlap:
            score += min(len(merged_overlap) * 0.14, 0.28)
            reasons.append(f"Merged OCR name tokens resembled: {', '.join(sorted(merged_overlap))}")

        if _set_total_matches(set_code=str(card.get('set_code') or ''), detected_total=detected_print_total):
            score += 0.48
            reasons.append(f'Printed total matched set count: {detected_print_total}')
        elif detected_print_total:
            score -= 0.08

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


def _unique_print_ratio_match(*, raw_text: str, game: str, detected: dict[str, str], catalog: list[dict[str, Any]], debug_metadata: dict[str, str]) -> CardIdentificationResult | None:
    detected_print_number = detected.get('detected_print_number', '')
    if not detected_print_number or '/' not in detected_print_number:
        return None
    if detected.get('detected_set_code'):
        return None

    detected_left_number = detected_print_number.split('/', 1)[0].lstrip('0') or '0'
    detected_print_total = _detected_print_total(detected_print_number)
    if not detected_left_number or not detected_print_total:
        return None

    total_matches = [
        card for card in catalog
        if (str(card.get('card_number') or '').lstrip('0') or '0') == detected_left_number
        and _set_total_matches(set_code=str(card.get('set_code') or ''), detected_total=detected_print_total)
    ]
    if len(total_matches) != 1:
        return None

    card = total_matches[0]
    raw_lower = raw_text.lower()
    raw_tokens = _tokenize(raw_text)
    card_name_en = str(card.get('card_name_en') or '')
    card_name_jp = str(card.get('card_name_jp') or '')
    variant = str(card.get('variant') or '')
    target_tokens = _tokenize(card_name_en) | _tokenize(card_name_jp) | _tokenize(variant)
    exact_overlap, fuzzy_overlap = _fuzzy_name_overlap(raw_tokens, target_tokens)
    merged_overlap = _merged_name_overlap(raw_tokens, target_tokens) - exact_overlap - fuzzy_overlap
    exact_name_hit = bool(
        (card_name_en and len(card_name_en.strip()) >= 3 and card_name_en.lower() in raw_lower)
        or (card_name_jp and len(card_name_jp.strip()) >= 2 and card_name_jp.lower() in raw_lower)
    )

    reasons = [
        f'Printed number + total uniquely matched the catalog: {detected_print_number}',
        f"Unique set-total candidate resolved to {str(card.get('set_code') or '')}.",
    ]
    confidence = 0.9
    if exact_overlap:
        reasons.append(f"Name token overlap: {', '.join(sorted(exact_overlap))}")
        confidence = 0.95
    elif merged_overlap:
        reasons.append(f"Merged OCR name tokens resembled: {', '.join(sorted(merged_overlap))}")
        confidence = 0.94
    elif fuzzy_overlap:
        reasons.append(f"OCR-similar name tokens: {', '.join(sorted(fuzzy_overlap))}")
        confidence = 0.93
    elif exact_name_hit:
        reasons.append('Exact card name text also appeared in OCR.')
        confidence = 0.96

    return CardIdentificationResult(
        matched=True,
        confidence=round(confidence, 2),
        display_name=_display_name_for_card(card),
        card_id=str(card.get('id') or ''),
        raw_text=raw_text,
        match_reasons=reasons,
        metadata={
            'game': str(card.get('game') or game),
            'set_code': str(card.get('set_code') or ''),
            'card_number': str(card.get('card_number') or ''),
            'resolver': 'unique_print_ratio_match',
            **debug_metadata,
            **detected,
        },
        candidate_options=[_candidate_option(score=confidence, card=card, reasons=reasons)],
    )





def _maybe_nearby_ratio_name_match(*, raw_text: str, game: str, detected: dict[str, str], catalog: list[dict[str, Any]], debug_metadata: dict[str, str]) -> CardIdentificationResult | None:
    if game != 'pokemon':
        return None
    detected_print_number = detected.get('detected_print_number', '')
    if not detected_print_number or '/' not in detected_print_number or detected.get('detected_set_code'):
        return None
    detected_left_number = detected_print_number.split('/', 1)[0].lstrip('0') or '0'
    detected_print_total = _detected_print_total(detected_print_number)
    if not detected_left_number.isdigit() or not detected_print_total:
        return None
    raw_lower = raw_text.lower()
    raw_tokens = _tokenize(raw_text)
    raw_word_tokens = re.findall(r'[a-z]{4,}', raw_lower)
    contender_scores: list[tuple[float, dict[str, Any], list[str]]] = []
    for card in catalog:
        card_number = str(card.get('card_number') or '').strip()
        if not card_number.isdigit():
            continue
        if not _set_total_matches(set_code=str(card.get('set_code') or ''), detected_total=detected_print_total):
            continue
        distance = abs(int(card_number) - int(detected_left_number))
        if distance > 2:
            continue
        card_name_en = str(card.get('card_name_en') or '')
        card_name_jp = str(card.get('card_name_jp') or '')
        variant = str(card.get('variant') or '')
        target_tokens = _tokenize(card_name_en) | _tokenize(card_name_jp) | _tokenize(variant)
        exact_overlap, fuzzy_overlap = _fuzzy_name_overlap(raw_tokens, target_tokens)
        merged_overlap = _merged_name_overlap(raw_tokens, target_tokens) - exact_overlap - fuzzy_overlap
        exact_name_hit = bool(
            (card_name_en and len(card_name_en.strip()) >= 3 and card_name_en.lower() in raw_lower)
            or (card_name_jp and len(card_name_jp.strip()) >= 2 and card_name_jp.lower() in raw_lower)
        )
        if not (exact_overlap or fuzzy_overlap or merged_overlap or exact_name_hit):
            continue
        score = 0.14
        reasons: list[str] = [f'Printed total matched set count: {detected_print_total}']
        if exact_overlap:
            score += min(len(exact_overlap) * 0.18, 0.30)
            reasons.append(f"Name token overlap: {', '.join(sorted(exact_overlap))}")
        if fuzzy_overlap:
            score += min(len(fuzzy_overlap) * 0.18, 0.26)
            reasons.append(f"OCR-similar name tokens: {', '.join(sorted(fuzzy_overlap))}")
        if merged_overlap:
            score += min(len(merged_overlap) * 0.12, 0.18)
            reasons.append(f"Merged OCR name tokens resembled: {', '.join(sorted(merged_overlap))}")
        best_ratio = 0.0
        best_pair = ''
        for raw_token in raw_word_tokens:
            for target_token in target_tokens:
                ratio = SequenceMatcher(None, raw_token, target_token).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_pair = target_token
        if best_ratio >= 0.92:
            score += 0.18
            reasons.append(f'Primary OCR token strongly resembled: {best_pair}')
        elif best_ratio >= 0.84:
            score += 0.10
            reasons.append(f'Primary OCR token resembled: {best_pair}')
        if exact_name_hit:
            score += 0.22
            reasons.append('Exact card name text appeared in OCR.')
        if distance == 0:
            score += 0.12
            reasons.append(f'Printed number matched identifier block: {detected_print_number}')
        elif distance == 1:
            score += 0.05
            reasons.append('Printed number was off by one, but name and set total were stronger.')
        else:
            score += 0.02
            reasons.append('Printed number was close, and the name evidence was stronger than the ratio OCR.')
        contender_scores.append((score, card, reasons))
    if not contender_scores:
        return None
    contender_scores.sort(key=lambda item: item[0], reverse=True)
    best_score, best_card, best_reasons = contender_scores[0]
    second_score = contender_scores[1][0] if len(contender_scores) > 1 else 0.0
    candidate_options = _top_candidate_options(contender_scores, limit=6)
    if best_score >= 0.40 and (best_score - second_score >= 0.06 or len(contender_scores) == 1):
        return CardIdentificationResult(
            matched=True,
            confidence=round(min(0.66 + best_score, 0.95), 2),
            display_name=_display_name_for_card(best_card),
            card_id=str(best_card.get('id') or ''),
            raw_text=raw_text,
            match_reasons=best_reasons,
            metadata={
                'game': str(best_card.get('game') or game),
                'set_code': str(best_card.get('set_code') or ''),
                'card_number': str(best_card.get('card_number') or ''),
                'resolver': 'nearby_ratio_name_match',
                **debug_metadata,
                **detected,
            },
            candidate_options=candidate_options,
        )
    return CardIdentificationResult(
        matched=False,
        confidence=round(min(best_score, 0.99), 2),
        display_name='Unknown card',
        card_id=None,
        raw_text=raw_text,
        match_reasons=[
            'I found likely old-card matches using name plus a nearby printed ratio, but I need a bit more confidence before auto-matching.',
            'Choose one of the shortlist options, or send the printed identifier manually if OCR got it wrong.',
        ],
        metadata={'game': game, 'resolver': 'nearby_ratio_name_shortlist', **debug_metadata, **detected},
        candidate_options=candidate_options,
    )

def _maybe_modern_ratio_match(*, raw_text: str, game: str, detected: dict[str, str], catalog: list[dict[str, Any]], debug_metadata: dict[str, str]) -> CardIdentificationResult | None:
    if game != 'pokemon':
        return None
    detected_print_number = detected.get('detected_print_number', '')
    if not detected_print_number or '/' not in detected_print_number:
        return None
    detected_set_code = detected.get('detected_set_code', '').strip()
    if detected_set_code:
        return None
    detected_left_number = detected_print_number.split('/', 1)[0].lstrip('0') or '0'
    detected_print_total = _detected_print_total(detected_print_number)
    if not detected_left_number.isdigit() or int(detected_left_number) < 100:
        return None

    raw_lower = raw_text.lower()
    raw_tokens = _tokenize(raw_text)
    contender_scores: list[tuple[float, dict[str, Any], list[str]]] = []

    for card in catalog:
        card_number = str(card.get('card_number') or '').strip()
        if (card_number.lstrip('0') or '0') != detected_left_number:
            continue

        card_name_en = str(card.get('card_name_en') or '')
        card_name_jp = str(card.get('card_name_jp') or '')
        variant = str(card.get('variant') or '')
        target_tokens = _tokenize(card_name_en) | _tokenize(card_name_jp) | _tokenize(variant)
        exact_overlap, fuzzy_overlap = _fuzzy_name_overlap(raw_tokens, target_tokens)
        merged_overlap = _merged_name_overlap(raw_tokens, target_tokens) - exact_overlap - fuzzy_overlap

        score = 0.0
        reasons: list[str] = []

        if _set_total_matches(set_code=str(card.get('set_code') or ''), detected_total=detected_print_total):
            score += 0.55
            reasons.append(f'Printed total matched set count: {detected_print_total}')
        else:
            score -= 0.10

        name_signal = False
        if exact_overlap:
            name_signal = True
            score += min(len(exact_overlap) * 0.20, 0.35)
            reasons.append(f"Name token overlap: {', '.join(sorted(exact_overlap))}")
        if fuzzy_overlap:
            name_signal = True
            score += min(len(fuzzy_overlap) * 0.12, 0.24)
            reasons.append(f"OCR-similar name tokens: {', '.join(sorted(fuzzy_overlap))}")
        if merged_overlap:
            name_signal = True
            score += min(len(merged_overlap) * 0.22, 0.32)
            reasons.append(f"Merged OCR name tokens resembled: {', '.join(sorted(merged_overlap))}")

        if variant:
            variant_lower = variant.lower()
            if variant_lower in raw_lower:
                name_signal = True
                score += 0.10
                reasons.append(f'Variant matched OCR text: {variant}')
            elif 'illustration' in variant_lower and 'rare' in variant_lower:
                score += 0.04

        if not name_signal:
            continue

        if re.search(r'\b' + re.escape(detected_left_number) + r'\b', raw_lower):
            score += 0.12
            reasons.append(f'Card number matched in OCR text: {detected_left_number}')

        score += 0.38
        reasons.append(f'Printed number matched identifier block: {detected_print_number}')

        contender_scores.append((score, card, reasons))

    if not contender_scores:
        return None

    contender_scores.sort(key=lambda item: item[0], reverse=True)
    best_score, best_card, best_reasons = contender_scores[0]
    second_score = contender_scores[1][0] if len(contender_scores) > 1 else 0.0
    candidate_options = _top_candidate_options(contender_scores)

    if best_score >= 0.75 and (best_score - second_score >= 0.12 or len(contender_scores) == 1):
        return CardIdentificationResult(
            matched=True,
            confidence=round(min(best_score, 0.99), 2),
            display_name=_display_name_for_card(best_card),
            card_id=str(best_card.get('id') or ''),
            raw_text=raw_text,
            match_reasons=best_reasons,
            metadata={
                'game': str(best_card.get('game') or game),
                'set_code': str(best_card.get('set_code') or ''),
                'card_number': str(best_card.get('card_number') or ''),
                'resolver': 'pokemon_modern_identifier_first',
                **debug_metadata,
                **detected,
            },
            candidate_options=candidate_options,
        )

    return CardIdentificationResult(
        matched=False,
        confidence=round(min(best_score, 0.99), 2),
        display_name='Unknown card',
        card_id=None,
        raw_text=raw_text,
        match_reasons=[
            'I found likely modern high-number matches from the printed identifier, but I need a bit more confidence before auto-matching.',
            'Choose one of the shortlist options, or send the title manually if OCR picked the wrong one.',
        ],
        metadata={'game': game, 'resolver': 'pokemon_modern_identifier_shortlist', **debug_metadata, **detected},
        candidate_options=candidate_options,
    )

def identify_card_from_text(*, raw_text: str, game: str) -> CardIdentificationResult:
    """Match OCR text against the seeded local catalog for one game."""

    detected = _extract_identifiers(raw_text, game=game)
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
                        'resolver': 'exact_identifier',
                        'service_build': CARD_IDENTIFIER_BUILD_MARKER,
                    },
                    candidate_options=candidate_options,
                )

    catalog = list_cards_for_game(game)
    number_candidate_count = '0'
    number_candidate_preview = 'none'
    if detected_left_number:
        number_matches = [
            row for row in catalog
            if (str(row.get('card_number') or '').strip().lstrip('0') or '0') == detected_left_number
        ]
        number_candidate_count = str(len(number_matches))
        number_candidate_preview = ','.join(
            sorted({str(row.get('set_code') or '').strip().upper() for row in number_matches if str(row.get('set_code') or '').strip()})[:6]
        ) or 'none'
    debug_metadata = {
        'service_build': CARD_IDENTIFIER_BUILD_MARKER,
        'catalog_size': str(len(catalog)),
        'detected_left_number': detected_left_number or 'none',
        'number_candidate_count': number_candidate_count,
        'number_candidate_preview': number_candidate_preview,
    }
    if not catalog:
        return CardIdentificationResult(
            matched=False,
            confidence=0.0,
            display_name='Unknown card',
            card_id=None,
            raw_text=raw_text,
            match_reasons=['No catalog cards are loaded for this game yet.'],
            metadata={'game': game, 'resolver': 'catalog_empty', **debug_metadata, **detected},
            candidate_options=[],
        )

    unique_ratio_result = _unique_print_ratio_match(raw_text=raw_text, game=game, detected=detected, catalog=catalog, debug_metadata=debug_metadata)
    if unique_ratio_result is not None:
        return unique_ratio_result

    nearby_ratio_result = _maybe_nearby_ratio_name_match(raw_text=raw_text, game=game, detected=detected, catalog=catalog, debug_metadata=debug_metadata)
    if nearby_ratio_result is not None:
        return nearby_ratio_result

    modern_ratio_result = _maybe_modern_ratio_match(raw_text=raw_text, game=game, detected=detected, catalog=catalog, debug_metadata=debug_metadata)
    if modern_ratio_result is not None:
        return modern_ratio_result

    raw_lower = raw_text.lower()
    raw_tokens = _tokenize(raw_text)
    detected_print_number = detected.get('detected_print_number', '')
    detected_left_number = detected_print_number.split('/')[0].lstrip('0') if detected_print_number else ''
    detected_print_total = _detected_print_total(detected_print_number)
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
        merged_overlap = _merged_name_overlap(raw_tokens, target_tokens) - exact_overlap - fuzzy_overlap
        if exact_overlap:
            token_score = min(len(exact_overlap) / max(len(target_tokens), 1), 1.0)
            score += token_score * 0.5
            reasons.append(f"Name token overlap: {', '.join(sorted(exact_overlap))}")
        if fuzzy_overlap:
            score += min(len(fuzzy_overlap) * 0.09, 0.24)
            reasons.append(f"OCR-similar name tokens: {', '.join(sorted(fuzzy_overlap))}")
        if merged_overlap:
            score += min(len(merged_overlap) * 0.18, 0.32)
            reasons.append(f"Merged OCR name tokens resembled: {', '.join(sorted(merged_overlap))}")

        if set_code and re.search(r'\b' + re.escape(set_code.lower()) + r'\b', raw_lower):
            score += 0.28
            reasons.append(f'Set code matched in OCR text: {set_code}')

        if detected_set_code and set_code and detected_set_code == set_code.lower():
            score += 0.4
            reasons.append(f'Detected set code matched identifier block: {set_code}')
        elif detected_set_code and set_code:
            score -= 0.14

        has_name_signal = bool(
            exact_overlap
            or fuzzy_overlap
            or merged_overlap
            or (card_name_en and card_name_en.lower() in raw_lower)
            or (card_name_jp and card_name_jp.lower() in raw_lower)
        )
        allow_numeric_match = bool(
            (detected_set_code and set_code and detected_set_code == set_code.lower())
            or (len(detected_left_number) >= 1 and has_name_signal)
        )
        if allow_numeric_match and card_number and re.search(r'\b' + re.escape(card_number.lower()) + r'\b', raw_lower):
            score += 0.12
            reasons.append(f'Card number matched in OCR text: {card_number}')

        exact_name_hit = bool(
            (card_name_en and len(card_name_en.strip()) >= 3 and card_name_en.lower() in raw_lower)
            or (card_name_jp and len(card_name_jp.strip()) >= 2 and card_name_jp.lower() in raw_lower)
        )
        strong_name_number_signal = exact_name_hit or len(exact_overlap) >= 2 or len(merged_overlap) >= 2

        if allow_numeric_match and detected_left_number and card_number and detected_left_number == card_number.lstrip('0'):
            score += 0.52 if strong_name_number_signal else 0.38
            reasons.append(
                f"{'Exact name + printed number matched' if strong_name_number_signal else 'Printed number matched identifier block'}: {detected_print_number}"
            )
        elif allow_numeric_match and detected_left_number and card_number and detected_left_number.zfill(len(card_number)) == card_number:
            score += 0.52 if strong_name_number_signal else 0.38
            reasons.append(
                f"{'Exact name + printed number matched' if strong_name_number_signal else 'Printed number matched identifier block'}: {detected_print_number}"
            )
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
        if not candidate_options and not detected_print_number:
            candidate_options = _name_only_shortlist(raw_text=raw_text, catalog=catalog)
        reasons = ['OCR text did not confidently match the local catalog.']
        if detected_print_number:
            reasons.append(f'Detected printed identifier: {detected_print_number}')
        if detected_set_code:
            reasons.append(f'Detected set code: {detected_set_code.upper()}')
        if candidate_options:
            reasons.append('I found likely name-based candidates you can choose from below.')
        return CardIdentificationResult(
            matched=False,
            confidence=best_score,
            display_name='Unknown card',
            card_id=None,
            raw_text=raw_text,
            match_reasons=reasons,
            metadata={'game': game, 'resolver': 'generic_catalog_no_match', **debug_metadata, **detected},
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
            metadata={'game': game, 'resolver': 'generic_name_ambiguous', **debug_metadata, **detected},
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
            metadata={'game': game, 'resolver': 'old_set_name_number_ambiguous', **debug_metadata, **detected},
            candidate_options=candidate_options,
        )

    if detected_set_code and best_card is not None and str(best_card.get('set_code') or '').lower() != detected_set_code:
        if not _strong_name_signal(raw_text=raw_text, raw_tokens=raw_tokens, card=best_card):
            return CardIdentificationResult(
                matched=False,
                confidence=round(min(best_score, 0.99), 2),
                display_name='Unknown card',
                card_id=None,
                raw_text=raw_text,
                match_reasons=[
                    'OCR saw a set code, but the best catalog hit came from a different set without strong enough name evidence.',
                    'This is treated as no-match to avoid hidden overfitting or accidental title hallucination.',
                ],
                metadata={'game': game, 'resolver': 'generic_set_code_mismatch_guard', **debug_metadata, **detected},
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
            metadata={'game': game, 'resolver': 'generic_too_many_close_candidates', **debug_metadata, **detected},
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
            'resolver': 'generic_catalog_match',
            **debug_metadata,
            **detected,
        },
        candidate_options=candidate_options,
    )
