"""Live PriceCharting price lookup helpers."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from config import get_config

logger = logging.getLogger(__name__)

_API_PRODUCTS_URL = 'https://www.pricecharting.com/api/products'
_API_PRODUCT_URL = 'https://www.pricecharting.com/api/product'
_SEARCH_URL_TEMPLATE = 'https://www.pricecharting.com/search-products?type=pokemon-cards&q={query}'
_TIMEOUT = 30.0
_HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; TCGListingBot/1.0)', 'Accept': 'application/json,text/html'}
_PRICE_RE = re.compile(r'\$\s*([0-9]+(?:\.[0-9]{2})?)')


@dataclass(frozen=True)
class PriceChartingPrice:
    source: str
    amount_sgd: float
    note: str


def _response_html(response: Any) -> str:
    for attr in ('body', 'html_content', 'text'):
        value = getattr(response, attr, None)
        if value is None:
            continue
        text = str(value)
        if text and text != 'None':
            return text
    return ''


def _blocked_response(*, response: Any, html: str) -> bool:
    lowered = html.lower()
    return getattr(response, 'status', 0) in {401, 403, 429} or 'just a moment' in lowered or 'cf-browser-verification' in lowered or 'attention required' in lowered


@lru_cache(maxsize=8)
def _fx_rate_to_sgd(base_currency: str) -> float:
    currency = base_currency.upper()
    if currency == 'SGD':
        return 1.0
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS) as client:
        response = client.get(f'https://open.er-api.com/v6/latest/{currency}')
        response.raise_for_status()
        payload = response.json()
    rate = float((payload.get('rates') or {}).get('SGD') or 0)
    if rate <= 0:
        raise RuntimeError(f'Could not convert {currency} to SGD.')
    return rate


def _normalize_spaces(value: str) -> str:
    return ' '.join(value.split())


def _build_queries(*, card_name: str, card_number: str | None, set_name: str | None) -> list[str]:
    queries: list[str] = []
    normalized_name = _normalize_spaces(card_name)
    normalized_number = (card_number or '').strip().lstrip('0')
    normalized_set = _normalize_spaces(set_name or '')
    if normalized_name and normalized_number and normalized_set:
        queries.append(f'{normalized_name} {normalized_number}/{normalized_set}')
        queries.append(f'{normalized_name} {normalized_number} {normalized_set}')
    if normalized_name and normalized_number:
        queries.append(f'{normalized_name} {normalized_number}')
    if normalized_name and normalized_set:
        queries.append(f'{normalized_name} {normalized_set}')
    if normalized_name:
        queries.append(normalized_name)
    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        if query not in seen:
            seen.add(query)
            deduped.append(query)
    return deduped


def _score_product(product: dict[str, Any], *, card_name: str, card_number: str | None, set_name: str | None) -> float:
    score = 0.0
    product_name = _normalize_spaces(str(product.get('product-name') or product.get('product_name') or '')).lower()
    console_name = _normalize_spaces(str(product.get('console-name') or product.get('console_name') or '')).lower()
    requested_name = _normalize_spaces(card_name).lower()
    requested_set = _normalize_spaces(set_name or '').lower()
    requested_number = (card_number or '').strip().lstrip('0')
    if requested_name and requested_name in product_name:
        score += 3.0
    elif requested_name and any(token in product_name for token in requested_name.split() if len(token) >= 4):
        score += 1.2
    if requested_set and requested_set in console_name:
        score += 2.0
    elif requested_set and any(token in console_name for token in requested_set.split() if len(token) >= 4):
        score += 1.0
    if requested_number and requested_number in product_name:
        score += 2.0
    return score


def _api_search(query: str, token: str) -> list[dict[str, Any]]:
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS) as client:
        response = client.get(_API_PRODUCTS_URL, params={'t': token, 'q': query})
        response.raise_for_status()
        payload = response.json()
    return list(payload.get('products') or [])


def _api_product(product_id: str, token: str) -> dict[str, Any] | None:
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS) as client:
        response = client.get(_API_PRODUCT_URL, params={'t': token, 'id': product_id})
        response.raise_for_status()
        payload = response.json()
    if payload.get('status') != 'success':
        return None
    return dict(payload)


def _extract_api_price(product: dict[str, Any]) -> PriceChartingPrice | None:
    loose_price = product.get('loose-price')
    if loose_price is None:
        return None
    try:
        usd_amount = float(loose_price) / 100.0
    except (TypeError, ValueError):
        return None
    return PriceChartingPrice(
        source='PriceCharting ungraded',
        amount_sgd=round(usd_amount * _fx_rate_to_sgd('USD'), 2),
        note='Approx. SGD from PriceCharting ungraded card price.',
    )


def _scrape_search_results(query: str) -> list[dict[str, str]]:
    search_url = _SEARCH_URL_TEMPLATE.format(query=quote_plus(query))
    try:
        from scrapling.fetchers import PlayWrightFetcher, StealthyFetcher
    except Exception as exc:
        logger.info('Scrapling is not available for PriceCharting fallback: %s', exc)
        return []
    html = ''
    response: Any | None = None
    try:
        response = StealthyFetcher.fetch(search_url, headless=True, wait=2500, timeout=60000, disable_resources=False, block_images=True)
        html = _response_html(response)
    except Exception as exc:
        logger.info('Scrapling PriceCharting stealth search failed for %s: %s', query, exc)
    if (not html or _blocked_response(response=response, html=html)):
        try:
            response = PlayWrightFetcher.fetch(search_url, headless=True, wait=2500, timeout=90000, disable_resources=False, stealth=True)
            html = _response_html(response)
        except Exception as exc:
            logger.info('Scrapling PriceCharting Playwright search failed for %s: %s', query, exc)
            return []
    if not html or _blocked_response(response=response, html=html):
        return []
    soup = BeautifulSoup(html, 'html.parser')
    results: list[dict[str, str]] = []
    for anchor in soup.select('a[href^="/game/"]')[:10]:
        href = str(anchor.get('href') or '').strip()
        label = _normalize_spaces(anchor.get_text(' ', strip=True))
        if not href or not label:
            continue
        parent_text = _normalize_spaces(anchor.parent.get_text(' ', strip=True)) if anchor.parent else label
        results.append({'url': f'https://www.pricecharting.com{href}', 'label': label, 'context': parent_text})
    return results


def _scrape_product_price(url: str) -> PriceChartingPrice | None:
    try:
        from scrapling.fetchers import PlayWrightFetcher, StealthyFetcher
    except Exception:
        return None
    html = ''
    response: Any | None = None
    try:
        response = StealthyFetcher.fetch(url, headless=True, wait=2500, timeout=60000, disable_resources=False, block_images=True)
        html = _response_html(response)
    except Exception as exc:
        logger.info('Scrapling PriceCharting stealth product fetch failed for %s: %s', url, exc)
    if not html or _blocked_response(response=response, html=html):
        try:
            response = PlayWrightFetcher.fetch(url, headless=True, wait=2500, timeout=90000, disable_resources=False, stealth=True)
            html = _response_html(response)
        except Exception as exc:
            logger.info('Scrapling PriceCharting Playwright product fetch failed for %s: %s', url, exc)
            return None
    if not html or _blocked_response(response=response, html=html):
        return None
    soup = BeautifulSoup(html, 'html.parser')
    body_text = soup.get_text(' ', strip=True)
    ungraded_index = body_text.lower().find('ungraded')
    snippet = body_text[ungraded_index:ungraded_index + 120] if ungraded_index >= 0 else body_text[:500]
    match = _PRICE_RE.search(snippet)
    if not match:
        return None
    usd_amount = float(match.group(1).replace(',', ''))
    return PriceChartingPrice(
        source='PriceCharting ungraded',
        amount_sgd=round(usd_amount * _fx_rate_to_sgd('USD'), 2),
        note='Approx. SGD from PriceCharting public page scrape.',
    )


def lookup_pricecharting_live_prices(*, card_name: str, card_number: str | None, set_name: str | None) -> list[PriceChartingPrice]:
    token = get_config().pricecharting_api_token.strip()
    queries = _build_queries(card_name=card_name, card_number=card_number, set_name=set_name)

    if token:
        for query in queries:
            try:
                products = _api_search(query, token)
            except Exception as exc:
                logger.info('PriceCharting API search failed for %s: %s', query, exc)
                continue
            ranked = sorted(products, key=lambda product: _score_product(product, card_name=card_name, card_number=card_number, set_name=set_name), reverse=True)
            if not ranked:
                continue
            product_id = str(ranked[0].get('id') or '').strip()
            if not product_id:
                continue
            try:
                product = _api_product(product_id, token)
            except Exception as exc:
                logger.info('PriceCharting API product lookup failed for %s: %s', product_id, exc)
                continue
            if product is None:
                continue
            ref = _extract_api_price(product)
            if ref is not None:
                return [ref]

    for query in queries:
        results = _scrape_search_results(query)
        if not results:
            continue
        ranked = sorted(results, key=lambda item: _score_product({'product-name': item['label'], 'console-name': item['context']}, card_name=card_name, card_number=card_number, set_name=set_name), reverse=True)
        for result in ranked[:2]:
            ref = _scrape_product_price(result['url'])
            if ref is not None:
                return [ref]

    return []
