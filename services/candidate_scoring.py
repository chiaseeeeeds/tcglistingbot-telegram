"""Shared evidence model and scoring helpers for card identification."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any


@dataclass(frozen=True)
class TextContext:
    raw_lower: str
    raw_tokens: set[str]
    raw_word_tokens: list[str]


@dataclass(frozen=True)
class NameEvidence:
    exact_overlap: set[str]
    fuzzy_overlap: set[str]
    merged_overlap: set[str]
    exact_name_hit_en: bool
    exact_name_hit_jp: bool
    variant_hit: bool
    best_word_ratio: float
    best_word_token: str

    @property
    def exact_name_hit(self) -> bool:
        return self.exact_name_hit_en or self.exact_name_hit_jp

    @property
    def has_name_signal(self) -> bool:
        return bool(self.exact_overlap or self.fuzzy_overlap or self.merged_overlap or self.exact_name_hit)


@dataclass(frozen=True)
class NameScoringWeights:
    exact_weight: float
    exact_cap: float
    fuzzy_weight: float
    fuzzy_cap: float
    merged_weight: float
    merged_cap: float
    exact_name_bonus: float = 0.0
    strong_word_bonus: float = 0.0
    word_bonus: float = 0.0
    variant_bonus: float = 0.0
    loose_variant_bonus: float = 0.0


def compute_name_evidence(
    *,
    context: TextContext,
    card: dict[str, Any],
    tokenize,
    fuzzy_name_overlap,
    merged_name_overlap,
) -> NameEvidence:
    card_name_en = str(card.get('card_name_en') or '')
    card_name_jp = str(card.get('card_name_jp') or '')
    variant = str(card.get('variant') or '')
    target_tokens = tokenize(card_name_en) | tokenize(card_name_jp) | tokenize(variant)
    exact_overlap, fuzzy_overlap = fuzzy_name_overlap(context.raw_tokens, target_tokens)
    merged_overlap = merged_name_overlap(context.raw_tokens, target_tokens) - exact_overlap - fuzzy_overlap
    best_word_ratio = 0.0
    best_word_token = ''
    for raw_word in context.raw_word_tokens:
        for target_token in target_tokens:
            ratio = SequenceMatcher(None, raw_word, target_token).ratio()
            if ratio > best_word_ratio:
                best_word_ratio = ratio
                best_word_token = target_token
    exact_name_hit_en = bool(card_name_en and len(card_name_en.strip()) >= 3 and card_name_en.lower() in context.raw_lower)
    exact_name_hit_jp = bool(card_name_jp and len(card_name_jp.strip()) >= 2 and card_name_jp.lower() in context.raw_lower)
    variant_hit = bool(variant and variant.lower() in context.raw_lower)
    return NameEvidence(
        exact_overlap=exact_overlap,
        fuzzy_overlap=fuzzy_overlap,
        merged_overlap=merged_overlap,
        exact_name_hit_en=exact_name_hit_en,
        exact_name_hit_jp=exact_name_hit_jp,
        variant_hit=variant_hit,
        best_word_ratio=best_word_ratio,
        best_word_token=best_word_token,
    )


def score_name_evidence(*, evidence: NameEvidence, card_name_en: str, card_name_jp: str, variant: str, weights: NameScoringWeights) -> tuple[float, list[str], bool]:
    score = 0.0
    reasons: list[str] = []
    if evidence.exact_overlap:
        score += min(len(evidence.exact_overlap) * weights.exact_weight, weights.exact_cap)
        reasons.append(f"Name token overlap: {', '.join(sorted(evidence.exact_overlap))}")
    if evidence.fuzzy_overlap:
        score += min(len(evidence.fuzzy_overlap) * weights.fuzzy_weight, weights.fuzzy_cap)
        reasons.append(f"OCR-similar name tokens: {', '.join(sorted(evidence.fuzzy_overlap))}")
    if evidence.merged_overlap:
        score += min(len(evidence.merged_overlap) * weights.merged_weight, weights.merged_cap)
        reasons.append(f"Merged OCR name tokens resembled: {', '.join(sorted(evidence.merged_overlap))}")
    if evidence.best_word_ratio >= 0.92 and weights.strong_word_bonus > 0:
        score += weights.strong_word_bonus
        reasons.append(f'Primary OCR token strongly resembled: {evidence.best_word_token}')
    elif evidence.best_word_ratio >= 0.84 and weights.word_bonus > 0:
        score += weights.word_bonus
        reasons.append(f'Primary OCR token resembled: {evidence.best_word_token}')
    if evidence.exact_name_hit_en and weights.exact_name_bonus > 0:
        score += weights.exact_name_bonus
        if card_name_en:
            reasons.append(f'Exact English name matched: {card_name_en}')
    if evidence.exact_name_hit_jp and weights.exact_name_bonus > 0:
        score += weights.exact_name_bonus
        if card_name_jp:
            reasons.append(f'Exact Japanese name matched: {card_name_jp}')
    if evidence.variant_hit and weights.variant_bonus > 0 and variant:
        score += weights.variant_bonus
        reasons.append(f'Variant matched OCR text: {variant}')
    elif (not evidence.variant_hit) and weights.loose_variant_bonus > 0 and not variant:
        score += weights.loose_variant_bonus
    return score, reasons, evidence.has_name_signal
