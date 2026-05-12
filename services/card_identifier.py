"""Card identification helpers driven by OCR text and local catalog data."""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any

from db.cards import list_cards_by_identifier, list_cards_for_game
from db.pokemon_sets import list_pokemon_sets
from services.candidate_generation import generate_catalog_candidates
from services.candidate_scoring import TextContext, NameScoringWeights, compute_name_evidence, score_name_evidence
from services.ocr_signals import OCRStructuredResult

_TOKEN_RE = re.compile(r'[A-Za-z0-9]+|[\u3040-\u30ffー]+|[\u4e00-\u9fff]+')
_CARD_RATIO_RE = re.compile(r'\b(\d{1,3})\s*/\s*(\d{1,3})\b')
_SET_BLOCK_RE = re.compile(r'\b([A-Z0-9]{2,5})\s*(?:EN|JP)?\s*(\d{1,3}/\d{1,3})\b', re.IGNORECASE)
_MANUAL_IDENTIFIER_RE = re.compile(r'^\s*([A-Z0-9]{2,5})\s+(\d{1,3}/\d{1,3})\s*$', re.IGNORECASE)
_COMPACT_RATIO_RE = re.compile(r'(?<!\d)(\d{6})(?!\d)')
_IDENTIFIER_BLOCK_RE = re.compile(r'IDENTIFIER\s*:\s*([^\n|]+)', re.IGNORECASE)
_SET_NAME_SPLIT_RE = re.compile(r'\s*[—–:/|]+\s*')
_NAME_STOPWORDS = {'name', 'identifier', 'pokemon', 'trainer', 'energy', 'stage', 'basic', 'ability'}
_SET_NAME_STOPWORDS = {'series', 'set', 'expansion', 'scarlet', 'violet', 'sun', 'moon', 'sword', 'shield', 'black', 'white'}
CARD_IDENTIFIER_BUILD_MARKER = 'card-identify-2026-04-12-shared-evidence-v17'

logger = logging.getLogger(__name__)


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
        if not normalized:
            continue
        if normalized.isascii() and normalized.isalpha() and len(normalized) < 2:
            continue
        if normalized in _NAME_STOPWORDS:
            continue
        tokens.add(normalized)
    return tokens


def _extract_identifiers_from_structured(structured: OCRStructuredResult, *, raw_text: str, game: str | None = None) -> dict[str, str]:
    """Extract likely identifiers directly from structured OCR signals."""

    metadata: dict[str, str] = {}
    set_code_text = structured.top_value('set_code_text').strip().upper()
    printed_ratio = structured.top_value('printed_ratio').strip().upper()
    identifier_text = structured.top_value('identifier').strip().upper()
    set_name_text = structured.top_value('set_name_text').strip()

    if set_code_text and not set_code_text.isdigit():
        metadata['detected_set_code'] = set_code_text
    ratio_candidates = [
        candidate
        for candidate in (
            printed_ratio,
            _extract_best_ratio(identifier_text),
            _extract_best_ratio(raw_text),
        )
        if candidate
    ]
    selected_ratio = _select_preferred_ratio(ratio_candidates)
    if selected_ratio:
        metadata['detected_print_number'] = selected_ratio
    if set_name_text and game == 'pokemon' and 'detected_set_code' not in metadata:
        metadata.update(_detect_pokemon_set_from_text(set_name_text))
    if game == 'pokemon' and 'detected_set_code' not in metadata and 'detected_set_name' not in metadata:
        name_alias_text = ' '.join(signal.value for signal in structured.signals if signal.kind in {'set_name_text', 'name_en', 'name_jp'})
        if name_alias_text.strip() and not _looks_like_modern_print_ratio(selected_ratio):
            metadata.update(_detect_pokemon_set_from_text(name_alias_text))
    if 'detected_print_number' not in metadata or (game == 'pokemon' and 'detected_set_code' not in metadata):
        fallback = _extract_identifiers(raw_text, game=game)
        metadata = {**fallback, **metadata}
    return metadata


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


def _ocr_text_context(*, raw_text: str, structured: OCRStructuredResult | None = None) -> tuple[str, str, set[str], list[str]]:
    searchable_text = _structured_search_text(structured) or raw_text
    raw_lower = searchable_text.lower()
    raw_tokens = _tokenize(searchable_text)
    raw_word_tokens = list(dict.fromkeys([token for token in raw_tokens if len(token) >= 2]))
    return searchable_text, raw_lower, raw_tokens, raw_word_tokens


def _build_text_context(*, raw_text: str, structured: OCRStructuredResult | None = None) -> TextContext:
    _, raw_lower, raw_tokens, raw_word_tokens = _ocr_text_context(raw_text=raw_text, structured=structured)
    return TextContext(raw_lower=raw_lower, raw_tokens=raw_tokens, raw_word_tokens=raw_word_tokens)


def _compute_card_name_evidence(*, context: TextContext, card: dict[str, Any]):
    return compute_name_evidence(
        context=context,
        card=card,
        tokenize=_tokenize,
        fuzzy_name_overlap=_fuzzy_name_overlap,
        merged_name_overlap=_merged_name_overlap,
    )


def _score_card_name_evidence(*, context: TextContext, card: dict[str, Any], weights: NameScoringWeights) -> tuple[Any, float, list[str]]:
    evidence = _compute_card_name_evidence(context=context, card=card)
    score, reasons, _ = score_name_evidence(
        evidence=evidence,
        card_name_en=str(card.get('card_name_en') or ''),
        card_name_jp=str(card.get('card_name_jp') or ''),
        variant=str(card.get('variant') or ''),
        weights=weights,
    )
    return evidence, score, reasons


def _extract_identifiers(raw_text: str, *, game: str | None = None) -> dict[str, str]:
    """Extract likely set code and printed card number from OCR text."""

    metadata: dict[str, str] = {}
    upper_text = raw_text.upper()
    identifier_block = _extract_identifier_block(upper_text)
    set_match = _SET_BLOCK_RE.search(identifier_block) or _SET_BLOCK_RE.search(upper_text)
    if set_match:
        candidate_set_code = set_match.group(1).strip().upper()
        candidate_print_number = set_match.group(2).replace(' ', '')
        if not candidate_set_code.isdigit():
            metadata['detected_set_code'] = candidate_set_code
            metadata['detected_print_number'] = candidate_print_number

    if 'detected_print_number' not in metadata:
        ratio_candidates = [
            candidate
            for candidate in (
                _extract_best_ratio(identifier_block),
                _extract_best_ratio(raw_text),
            )
            if candidate
        ]
        selected_ratio = _select_preferred_ratio(ratio_candidates)
        if selected_ratio:
            metadata['detected_print_number'] = selected_ratio

    if 'detected_print_number' not in metadata:
        compact_source = identifier_block or upper_text
        compact_match = _COMPACT_RATIO_RE.search(compact_source.replace(' ', '')) or _COMPACT_RATIO_RE.search(upper_text.replace(' ', ''))
        if compact_match:
            digits = compact_match.group(1)
            metadata['detected_print_number'] = f'{digits[:3]}/{digits[3:]}'

    if game == 'pokemon' and 'detected_set_code' not in metadata:
        detected_print_number = str(metadata.get('detected_print_number') or '')
        if not _looks_like_modern_print_ratio(detected_print_number):
            metadata.update(_detect_pokemon_set_from_text(raw_text))

    return metadata


def _extract_identifier_block(raw_text: str) -> str:
    match = _IDENTIFIER_BLOCK_RE.search(raw_text)
    return match.group(1).strip().upper() if match else ''


def _ratio_sort_key(ratio: str) -> tuple[int, int, int, int]:
    left_text, _, total_text = ratio.partition('/')
    try:
        left = int(left_text)
        total = int(total_text)
    except ValueError:
        return (0, 0, 0, 0)
    return (len(left_text.lstrip('0') or '0'), left, -abs(total - left), total)


def _extract_best_ratio(raw_text: str) -> str:
    candidates = [f'{left}/{right}' for left, right in _CARD_RATIO_RE.findall(raw_text)]
    return _select_preferred_ratio(candidates)


def _select_preferred_ratio(candidates: list[str]) -> str:
    if not candidates:
        return ''
    counts: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    for index, candidate in enumerate(candidates):
        normalized = candidate.strip().upper().replace(' ', '')
        if not normalized:
            continue
        counts[normalized] = counts.get(normalized, 0) + 1
        first_seen.setdefault(normalized, index)
    if not counts:
        return ''
    return max(
        counts,
        key=lambda ratio: (
            counts[ratio],
            _ratio_sort_key(ratio),
            -first_seen[ratio],
        ),
    )


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



def _strong_name_signal(*, raw_text: str, card: dict[str, Any], structured: OCRStructuredResult | None = None) -> bool:
    context = _build_text_context(raw_text=raw_text, structured=structured)
    evidence = _compute_card_name_evidence(context=context, card=card)
    if evidence.exact_overlap or evidence.merged_overlap:
        return True
    if len(evidence.fuzzy_overlap) >= 2:
        return True
    return evidence.exact_name_hit


def _detected_print_total(detected_print_number: str) -> str:
    if not detected_print_number or '/' not in detected_print_number:
        return ''
    return detected_print_number.split('/', 1)[1].strip().lstrip('0') or '0'


def _looks_like_modern_print_ratio(detected_print_number: str) -> bool:
    if not detected_print_number or '/' not in detected_print_number:
        return False
    left, _, total = detected_print_number.partition('/')
    left = left.strip().lstrip('0') or '0'
    total = total.strip().lstrip('0') or '0'
    if not left.isdigit() or not total.isdigit():
        return False
    return int(left) >= 100 or int(total) >= 100



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


def _name_only_shortlist(*, raw_text: str, catalog: list[dict[str, Any]], limit: int = 3, structured: OCRStructuredResult | None = None) -> list[dict[str, Any]]:
    context = _build_text_context(raw_text=raw_text, structured=structured)
    weights = NameScoringWeights(
        exact_weight=0.18,
        exact_cap=0.30,
        fuzzy_weight=0.20,
        fuzzy_cap=0.28,
        merged_weight=0.08,
        merged_cap=0.12,
        exact_name_bonus=0.25,
        strong_word_bonus=0.30,
        word_bonus=0.16,
    )
    contender_scores: list[tuple[float, dict[str, Any], list[str]]] = []
    for card in catalog:
        target_tokens = _tokenize(str(card.get('card_name_en') or '')) | _tokenize(str(card.get('card_name_jp') or ''))
        if not target_tokens:
            continue
        evidence, score, reasons = _score_card_name_evidence(context=context, card=card, weights=weights)
        if not evidence.has_name_signal:
            continue
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
    structured: OCRStructuredResult | None = None,
) -> tuple[dict[str, str] | None, float, list[str]]:
    """Score exact set-code/card-number candidates using OCR name and variant hints."""

    context = _build_text_context(raw_text=raw_text, structured=structured)
    detected_print_total = _detected_print_total(detected.get('detected_print_number', ''))
    weights = NameScoringWeights(
        exact_weight=0.12,
        exact_cap=0.35,
        fuzzy_weight=0.08,
        fuzzy_cap=0.20,
        merged_weight=0.14,
        merged_cap=0.28,
        exact_name_bonus=0.25,
        variant_bonus=0.15,
        loose_variant_bonus=0.08,
    )
    best_card: dict[str, str] | None = None
    best_score = -1.0
    best_reasons: list[str] = []

    for card in candidates:
        evidence, score, name_reasons = _score_card_name_evidence(context=context, card=card, weights=weights)
        reasons = ['Set code and printed number matched the catalog.', *name_reasons]

        if _set_total_matches(set_code=str(card.get('set_code') or ''), detected_total=detected_print_total):
            score += 0.48
            reasons.append(f'Printed total matched set count: {detected_print_total}')
        elif detected_print_total:
            score -= 0.08

        if score > best_score:
            best_card = card
            best_score = score
            best_reasons = reasons

    if not candidates:
        return None, 0.0, []

    return best_card or candidates[0], min(0.78 + max(best_score, 0.0), 0.99), best_reasons or ['Set code and printed number matched the catalog.']


def _unique_print_ratio_match(*, raw_text: str, game: str, detected: dict[str, str], catalog: list[dict[str, Any]], debug_metadata: dict[str, str], structured: OCRStructuredResult | None = None) -> CardIdentificationResult | None:
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
    context = _build_text_context(raw_text=raw_text, structured=structured)
    evidence = _compute_card_name_evidence(context=context, card=card)

    reasons = [
        f'Printed number + total uniquely matched the catalog: {detected_print_number}',
        f"Unique set-total candidate resolved to {str(card.get('set_code') or '')}.",
    ]
    confidence = 0.9
    if evidence.exact_overlap:
        reasons.append(f"Name token overlap: {', '.join(sorted(evidence.exact_overlap))}")
        confidence = 0.95
    elif evidence.merged_overlap:
        reasons.append(f"Merged OCR name tokens resembled: {', '.join(sorted(evidence.merged_overlap))}")
        confidence = 0.94
    elif evidence.fuzzy_overlap:
        reasons.append(f"OCR-similar name tokens: {', '.join(sorted(evidence.fuzzy_overlap))}")
        confidence = 0.93
    elif evidence.exact_name_hit:
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





def _maybe_nearby_ratio_name_match(*, raw_text: str, game: str, detected: dict[str, str], catalog: list[dict[str, Any]], debug_metadata: dict[str, str], structured: OCRStructuredResult | None = None) -> CardIdentificationResult | None:
    if game != 'pokemon':
        return None
    detected_print_number = detected.get('detected_print_number', '')
    if not detected_print_number or '/' not in detected_print_number or detected.get('detected_set_code'):
        return None
    detected_left_number = detected_print_number.split('/', 1)[0].lstrip('0') or '0'
    detected_print_total = _detected_print_total(detected_print_number)
    if not detected_left_number.isdigit() or not detected_print_total:
        return None
    if int(detected_left_number) >= 100:
        return None
    context = _build_text_context(raw_text=raw_text, structured=structured)
    weights = NameScoringWeights(
        exact_weight=0.18,
        exact_cap=0.30,
        fuzzy_weight=0.18,
        fuzzy_cap=0.26,
        merged_weight=0.12,
        merged_cap=0.18,
        exact_name_bonus=0.22,
        strong_word_bonus=0.18,
        word_bonus=0.10,
    )
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
        evidence, score, name_reasons = _score_card_name_evidence(context=context, card=card, weights=weights)
        if not evidence.has_name_signal:
            continue
        reasons: list[str] = [f'Printed total matched set count: {detected_print_total}', *name_reasons]
        score += 0.14
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

def _maybe_modern_ratio_match(*, raw_text: str, game: str, detected: dict[str, str], catalog: list[dict[str, Any]], debug_metadata: dict[str, str], structured: OCRStructuredResult | None = None) -> CardIdentificationResult | None:
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

    context = _build_text_context(raw_text=raw_text, structured=structured)
    candidate_catalog = generate_catalog_candidates(
        game=game,
        catalog=catalog,
        raw_text=raw_text,
        structured=structured,
        detected=detected,
    )
    weights = NameScoringWeights(
        exact_weight=0.20,
        exact_cap=0.35,
        fuzzy_weight=0.12,
        fuzzy_cap=0.24,
        merged_weight=0.22,
        merged_cap=0.32,
        variant_bonus=0.10,
    )
    contender_scores: list[tuple[float, dict[str, Any], list[str]]] = []

    for card in candidate_catalog:
        card_number = str(card.get('card_number') or '').strip()
        if (card_number.lstrip('0') or '0') != detected_left_number:
            continue

        evidence, score, name_reasons = _score_card_name_evidence(context=context, card=card, weights=weights)
        if not evidence.has_name_signal:
            continue

        reasons: list[str] = [*name_reasons]
        if _set_total_matches(set_code=str(card.get('set_code') or ''), detected_total=detected_print_total):
            score += 0.55
            reasons.append(f'Printed total matched set count: {detected_print_total}')
        else:
            score -= 0.10

        variant = str(card.get('variant') or '')
        if variant and 'illustration' in variant.lower() and 'rare' in variant.lower() and not evidence.variant_hit:
            score += 0.04

        if re.search(r'\b' + re.escape(detected_left_number) + r'\b', context.raw_lower):
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

def identify_card_from_text(*, raw_text: str, game: str, structured: OCRStructuredResult | None = None) -> CardIdentificationResult:
    """Match OCR text against the seeded local catalog for one game."""


    logger.info('Raw text: %s', raw_text)

    detected = _extract_identifiers_from_structured(structured, raw_text=raw_text, game=game) if structured is not None else _extract_identifiers(raw_text, game=game)
    detected_print_number = detected.get('detected_print_number', '')
    detected_left_number = detected_print_number.split('/')[0].lstrip('0') if detected_print_number else ''
    detected_print_total = _detected_print_total(detected_print_number)
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
                structured=structured,
            )
            if matched_card is not None:
                matched_set_code = str(matched_card.get('set_code') or '').strip().upper()
                expected_total = _pokemon_set_card_counts().get(matched_set_code, '') if game == 'pokemon' and detected_print_total else ''
                if expected_total and not _set_total_matches(set_code=matched_set_code, detected_total=detected_print_total):
                    logger.info(
                        'Skipping exact identifier auto-match due to mismatched set total',
                        extra={
                            'game': game,
                            'detected_set_code': detected_set_code,
                            'detected_print_number': detected_print_number,
                            'matched_set_code': matched_set_code,
                            'matched_card_number': str(matched_card.get('card_number') or ''),
                            'expected_total': expected_total,
                        },
                    )
                else:
                    candidate_options = [
                        _candidate_option(score=confidence, card=card, reasons=reasons if card == matched_card else ['Set code and printed number matched the catalog.'])
                        for card in identifier_candidates[:3]
                    ]
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
    candidate_catalog = generate_catalog_candidates(
        game=game,
        catalog=catalog,
        raw_text=raw_text,
        structured=structured,
        detected=detected,
    )
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
        'candidate_pool_size': str(len(candidate_catalog)),
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

    unique_ratio_result = _unique_print_ratio_match(raw_text=raw_text, game=game, detected=detected, catalog=catalog, debug_metadata=debug_metadata, structured=structured)
    if unique_ratio_result is not None:
        return unique_ratio_result

    nearby_ratio_result = _maybe_nearby_ratio_name_match(raw_text=raw_text, game=game, detected=detected, catalog=catalog, debug_metadata=debug_metadata, structured=structured)
    if nearby_ratio_result is not None:
        return nearby_ratio_result

    modern_ratio_result = _maybe_modern_ratio_match(raw_text=raw_text, game=game, detected=detected, catalog=catalog, debug_metadata=debug_metadata, structured=structured)
    if modern_ratio_result is not None:
        return modern_ratio_result

    context = _build_text_context(raw_text=raw_text, structured=structured)
    detected_print_number = detected.get('detected_print_number', '')
    detected_left_number = detected_print_number.split('/')[0].lstrip('0') if detected_print_number else ''
    detected_print_total = _detected_print_total(detected_print_number)
    detected_set_code = detected.get('detected_set_code', '').lower()
    weights = NameScoringWeights(
        exact_weight=0.18,
        exact_cap=0.50,
        fuzzy_weight=0.09,
        fuzzy_cap=0.24,
        merged_weight=0.18,
        merged_cap=0.32,
        exact_name_bonus=0.26,
    )

    best_score = 0.0
    best_card: dict[str, Any] | None = None
    best_reasons: list[str] = []
    contender_scores: list[tuple[float, dict[str, Any], list[str]]] = []

    for card in candidate_catalog:
        card_name_en = str(card.get('card_name_en') or '')
        card_name_jp = str(card.get('card_name_jp') or '')
        set_code = str(card.get('set_code') or '')
        card_number = str(card.get('card_number') or '')

        evidence, score, name_reasons = _score_card_name_evidence(context=context, card=card, weights=weights)
        reasons: list[str] = [*name_reasons]

        if set_code and re.search(r'\b' + re.escape(set_code.lower()) + r'\b', context.raw_lower):
            score += 0.28
            reasons.append(f'Set code matched in OCR text: {set_code}')

        if detected_set_code and set_code and detected_set_code == set_code.lower():
            score += 0.4
            reasons.append(f'Detected set code matched identifier block: {set_code}')
        elif detected_set_code and set_code:
            score -= 0.14

        allow_numeric_match = bool(
            (detected_set_code and set_code and detected_set_code == set_code.lower())
            or (len(detected_left_number) >= 1 and evidence.has_name_signal)
        )
        if allow_numeric_match and card_number and re.search(r'\b' + re.escape(card_number.lower()) + r'\b', context.raw_lower):
            score += 0.12
            reasons.append(f'Card number matched in OCR text: {card_number}')

        strong_name_number_signal = evidence.exact_name_hit or len(evidence.exact_overlap) >= 2 or len(evidence.merged_overlap) >= 2

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

        contender_scores.append((score, card, reasons))
        if score > best_score:
            best_score = score
            best_card = card
            best_reasons = reasons

    candidate_options = _top_candidate_options(contender_scores)

    if best_card is None or best_score < 0.25:
        if not candidate_options and not detected_print_number:
            candidate_options = _name_only_shortlist(raw_text=raw_text, catalog=catalog, structured=structured)
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
        if not _strong_name_signal(raw_text=raw_text, card=best_card, structured=structured):
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

    if detected_set_code and detected_print_total and best_card is not None:
        best_set_code = str(best_card.get('set_code') or '').strip().upper()
        expected_total = _pokemon_set_card_counts().get(best_set_code, '') if game == 'pokemon' else ''
        if expected_total and best_set_code.lower() == detected_set_code and not _set_total_matches(set_code=best_set_code, detected_total=detected_print_total):
            if not _strong_name_signal(raw_text=raw_text, card=best_card, structured=structured):
                return CardIdentificationResult(
                    matched=False,
                    confidence=round(min(best_score, 0.99), 2),
                    display_name='Unknown card',
                    card_id=None,
                    raw_text=raw_text,
                    match_reasons=[
                        'OCR saw a printed ratio, but the total count does not fit the detected set.',
                        f'Detected {detected_print_number}, but {best_set_code} cards should total /{expected_total}.',
                    ],
                    metadata={'game': game, 'resolver': 'generic_print_total_guard', **debug_metadata, **detected},
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
