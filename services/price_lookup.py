"""Price reference helpers for listing creation."""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from db.client import extract_many, get_client


@dataclass(frozen=True)
class PriceReference:
    """A normalized price reference shown to the seller before posting."""

    source: str
    amount_sgd: float
    note: str


def lookup_price_references(*, game: str, card_name: str, card_id: str | None = None) -> list[PriceReference]:
    """Return best-effort price references for the current draft.

    v1 uses internal listing history as a safe fallback while external web sources are still being
    wired up.
    """

    exact_rows: list[dict] = []
    if card_id:
        response = (
            get_client()
            .table('listings')
            .select('card_id, card_name, price_sgd, created_at')
            .eq('game', game)
            .eq('card_id', card_id)
            .order('created_at', desc=True)
            .limit(25)
            .execute()
        )
        exact_rows = extract_many(response)

    rows = exact_rows
    exact_match_mode = bool(exact_rows)
    if not rows:
        response = (
            get_client()
            .table('listings')
            .select('card_id, card_name, price_sgd, created_at')
            .eq('game', game)
            .order('created_at', desc=True)
            .limit(25)
            .execute()
        )
        rows = extract_many(response)

    normalized_name = card_name.strip().lower()
    if exact_match_mode:
        matching_rows = rows
    else:
        matching_rows = [
            row for row in rows
            if normalized_name and normalized_name in str(row.get('card_name') or '').strip().lower()
        ]
    prices = [float(row['price_sgd']) for row in matching_rows if row.get('price_sgd') is not None]
    if not prices:
        return []

    average_note = (
        f'Average from {len(prices)} prior listings of this exact card.'
        if exact_match_mode
        else f'Average from {len(prices)} prior matching listings.'
    )
    median_note = (
        'Median across recent listings of this exact card.'
        if exact_match_mode
        else 'Median across recent matching listings.'
    )

    references: list[PriceReference] = [
        PriceReference(
            source='Bot exact history' if exact_match_mode else 'Bot market history',
            amount_sgd=round(statistics.mean(prices), 2),
            note=average_note,
        )
    ]
    if len(prices) > 1:
        references.append(
            PriceReference(
                source='Bot exact median' if exact_match_mode else 'Bot market median',
                amount_sgd=round(statistics.median(prices), 2),
                note=median_note,
            )
        )
    return references
