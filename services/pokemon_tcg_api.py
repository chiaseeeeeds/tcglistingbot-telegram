"""Live Pokémon price lookups via the Pokémon TCG API."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_API_URL = 'https://api.pokemontcg.io/v2/cards'
_FX_URL_TEMPLATE = 'https://open.er-api.com/v6/latest/{base}'
_TIMEOUT = 20.0
_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; TCGListingBot/1.0)',
    'Accept': 'application/json',
}


@dataclass(frozen=True)
class PokemonLivePrice:
    source: str
    amount_sgd: float
    note: str


@lru_cache(maxsize=64)
def _search_cards(query: str) -> list[dict[str, Any]]:
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS) as client:
        response = client.get(_API_URL, params={'q': query, 'pageSize': 8})
        response.raise_for_status()
        payload = response.json()
    return list(payload.get('data') or [])


@lru_cache(maxsize=8)
def _fx_rate_to_sgd(base_currency: str) -> float:
    currency = base_currency.upper()
    if currency == 'SGD':
        return 1.0
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS) as client:
        response = client.get(_FX_URL_TEMPLATE.format(base=currency))
        response.raise_for_status()
        payload = response.json()
    rate = float((payload.get('rates') or {}).get('SGD') or 0)
    if rate <= 0:
        raise RuntimeError(f'Could not convert {currency} to SGD.')
    return rate


def _normalize_spaces(value: str) -> str:
    return ' '.join(value.split())


def _score_api_card(card: dict[str, Any], *, card_name: str, card_number: str | None, set_name: str | None) -> float:
    score = 0.0
    api_name = _normalize_spaces(str(card.get('name') or '')).lower()
    requested_name = _normalize_spaces(card_name).lower()
    if api_name == requested_name:
        score += 3.0
    elif requested_name and requested_name in api_name:
        score += 2.0

    api_number = str(card.get('number') or '').strip()
    normalized_number = (card_number or '').strip().lstrip('0')
    if api_number and normalized_number and api_number.lstrip('0') == normalized_number:
        score += 4.0

    api_set_name = _normalize_spaces(str((card.get('set') or {}).get('name') or '')).lower()
    requested_set_name = _normalize_spaces(set_name or '').lower()
    if api_set_name and requested_set_name:
        if api_set_name == requested_set_name:
            score += 2.0
        elif requested_set_name in api_set_name or api_set_name in requested_set_name:
            score += 1.0
    return score


def _pick_best_card(cards: list[dict[str, Any]], *, card_name: str, card_number: str | None, set_name: str | None) -> dict[str, Any] | None:
    best_card: dict[str, Any] | None = None
    best_score = -1.0
    for card in cards:
        score = _score_api_card(card, card_name=card_name, card_number=card_number, set_name=set_name)
        if score > best_score:
            best_score = score
            best_card = card
    if best_score < 2.0:
        return None
    return best_card


def _build_queries(*, card_name: str, card_number: str | None, set_name: str | None) -> list[str]:
    queries: list[str] = []
    normalized_name = _normalize_spaces(card_name)
    if card_number and normalized_name:
        queries.append(f'name:"{normalized_name}" number:{card_number.lstrip("0") or "0"}')
    if set_name and card_number and normalized_name:
        queries.append(f'set.name:"{_normalize_spaces(set_name)}" number:{card_number.lstrip("0") or "0"} name:"{normalized_name}"')
    if card_number and normalized_name:
        first_word = normalized_name.split()[0]
        queries.append(f'number:{card_number.lstrip("0") or "0"} name:{first_word}')
    queries.append(f'name:"{normalized_name}"')
    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        if query not in seen:
            seen.add(query)
            deduped.append(query)
    return deduped


def _extract_tcgplayer_market(card: dict[str, Any]) -> PokemonLivePrice | None:
    tcgplayer = card.get('tcgplayer') or {}
    prices = tcgplayer.get('prices') or {}
    best_bucket: dict[str, Any] | None = None
    best_bucket_name = ''
    for bucket_name in ['holofoil', 'reverseHolofoil', 'normal', '1stEditionHolofoil', '1stEditionNormal']:
        bucket = prices.get(bucket_name)
        if isinstance(bucket, dict) and any(bucket.get(key) is not None for key in ['market', 'mid', 'low']):
            best_bucket = bucket
            best_bucket_name = bucket_name
            break
    if best_bucket is None:
        return None
    usd_amount = best_bucket.get('market') or best_bucket.get('mid') or best_bucket.get('low')
    if usd_amount is None:
        return None
    sgd_amount = round(float(usd_amount) * _fx_rate_to_sgd('USD'), 2)
    updated_at = str(tcgplayer.get('updatedAt') or 'recently')
    return PokemonLivePrice(
        source='TCGplayer market',
        amount_sgd=sgd_amount,
        note=f'Approx. SGD from {best_bucket_name} USD pricing, updated {updated_at}.',
    )


def _extract_cardmarket_trend(card: dict[str, Any]) -> PokemonLivePrice | None:
    cardmarket = card.get('cardmarket') or {}
    prices = cardmarket.get('prices') or {}
    eur_amount = prices.get('trendPrice') or prices.get('averageSellPrice') or prices.get('avg7') or prices.get('lowPrice')
    if eur_amount is None:
        return None
    sgd_amount = round(float(eur_amount) * _fx_rate_to_sgd('EUR'), 2)
    updated_at = str(cardmarket.get('updatedAt') or 'recently')
    return PokemonLivePrice(
        source='Cardmarket trend',
        amount_sgd=sgd_amount,
        note=f'Approx. SGD from EUR market data, updated {updated_at}.',
    )


def lookup_pokemon_live_prices(*, card_name: str, card_number: str | None, set_name: str | None) -> list[PokemonLivePrice]:
    """Return best-effort live Pokémon pricing references in SGD."""

    best_card: dict[str, Any] | None = None
    for query in _build_queries(card_name=card_name, card_number=card_number, set_name=set_name):
        try:
            cards = _search_cards(query)
        except Exception as exc:
            logger.warning('Pokémon API lookup failed for query %s: %s', query, exc)
            continue
        best_card = _pick_best_card(cards, card_name=card_name, card_number=card_number, set_name=set_name)
        if best_card is not None:
            break
    if best_card is None:
        return []

    references: list[PokemonLivePrice] = []
    for extractor in (_extract_tcgplayer_market, _extract_cardmarket_trend):
        try:
            reference = extractor(best_card)
        except Exception as exc:
            logger.warning('Pokémon live price normalization failed for %s: %s', best_card.get('id'), exc)
            continue
        if reference is not None:
            references.append(reference)
    return references
