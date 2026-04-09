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


def lookup_price_references(*, game: str, card_name: str) -> list[PriceReference]:
    """Return best-effort price references for the current draft.

    v1 uses internal listing history as a safe fallback while external web sources are still being
    wired up.
    """

    response = (
        get_client()
        .table('listings')
        .select('card_name, price_sgd, created_at')
        .eq('game', game)
        .order('created_at', desc=True)
        .limit(25)
        .execute()
    )
    rows = extract_many(response)
    normalized_name = card_name.strip().lower()
    matching_rows = [
        row for row in rows
        if normalized_name and normalized_name in str(row.get('card_name') or '').strip().lower()
    ]
    prices = [float(row['price_sgd']) for row in matching_rows if row.get('price_sgd') is not None]
    if not prices:
        return []

    references: list[PriceReference] = [
        PriceReference(
            source='Bot market history',
            amount_sgd=round(statistics.mean(prices), 2),
            note=f'Average from {len(prices)} prior matching listings.',
        )
    ]
    if len(prices) > 1:
        references.append(
            PriceReference(
                source='Bot market median',
                amount_sgd=round(statistics.median(prices), 2),
                note='Median across recent matching listings.',
            )
        )
    return references
