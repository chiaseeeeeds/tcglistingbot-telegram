"""Import Japanese Pokémon cards from the official card search API and detail pages."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import sys
from pathlib import Path
from typing import Any

import httpx
import psycopg
from bs4 import BeautifulSoup
from psycopg.types.json import Json

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_config

RESULT_API_URL = 'https://www.pokemon-card.com/card-search/resultAPI.php'
DETAIL_URL_TEMPLATE = 'https://www.pokemon-card.com/card-search/details.php/card/{card_id}/regu/all'
_BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
    'Referer': 'https://www.pokemon-card.com/card-search/',
    'Origin': 'https://www.pokemon-card.com',
}


async def get_with_retries(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    label: str,
    retries: int,
    retryable_statuses: set[int] | None = None,
) -> httpx.Response:
    retryable = retryable_statuses or {403, 408, 409, 425, 429, 500, 502, 503, 504}
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            last_error = exc
            status_code = exc.response.status_code if exc.response is not None else None
            if attempt >= retries or status_code not in retryable:
                break
            delay = min(45.0, (3.0 * attempt) + random.uniform(0.5, 1.5))
            print(json.dumps({'event': 'pokemon_jp_retry_wait', 'label': label, 'attempt': attempt, 'status_code': status_code, 'delay_seconds': round(delay, 2)}), flush=True)
            await asyncio.sleep(delay)
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt >= retries:
                break
            delay = min(20.0, (1.5 * attempt) + random.uniform(0.25, 0.75))
            print(json.dumps({'event': 'pokemon_jp_retry_wait', 'label': label, 'attempt': attempt, 'delay_seconds': round(delay, 2)}), flush=True)
            await asyncio.sleep(delay)
    raise RuntimeError(f'Could not fetch {label}: {last_error}')
CARD_NUMBER_RE = re.compile(r'(\d+[A-Za-z]?)[\s\u00a0]*\/[\s\u00a0]*(\d+[A-Za-z]?)')
SET_NAME_RE = re.compile(r'拡張パック|強化拡張パック|ハイクラスパック|プロモカード|スタートデッキ|構築デッキ|デッキビルドBOX|スターターセット|スペシャルデッキセット')


class CardDetailParseError(RuntimeError):
    """Raised when an official JP card detail page cannot be parsed into a catalog identity."""


class CardDetailFetchError(RuntimeError):
    """Raised when an official JP card detail page cannot be fetched reliably."""


def get_database_url() -> str:
    config = get_config()
    database_url = os.getenv('DATABASE_POOLER_URL') or config.database_url
    if not database_url:
        raise SystemExit('No database connection string found. Set DATABASE_POOLER_URL or DATABASE_URL.')
    return database_url



def normalize_space(value: str) -> str:
    return ' '.join(value.split())



def rarity_from_detail(soup: BeautifulSoup) -> str | None:
    rarity_img = soup.select_one('img[src*="/assets/images/card/rarity/"]')
    alt = normalize_space(rarity_img.get('alt') or '') if rarity_img else ''
    return alt or None



def parse_set_name(soup: BeautifulSoup) -> str:
    candidates = []
    for anchor in soup.select('.PopupSub a.Link'):
        text = normalize_space(anchor.get_text(' ', strip=True))
        if text:
            candidates.append(text)
    for candidate in candidates:
        if SET_NAME_RE.search(candidate):
            return candidate
    if candidates:
        return candidates[0]
    return 'ポケモンカード公式検索'



def parse_detail_html(html_text: str, *, card_id: str, thumb_path: str, card_name_fallback: str) -> dict[str, Any]:
    soup = BeautifulSoup(html_text, 'html.parser')
    heading = soup.select_one('h1.Heading1')
    card_name_jp = normalize_space(heading.get_text(' ', strip=True)) if heading else normalize_space(card_name_fallback)

    regulation_img = soup.select_one('img.img-regulation')
    set_code = normalize_space(regulation_img.get('alt') or '') if regulation_img else ''
    if not set_code:
        parts = [part for part in thumb_path.split('/') if part]
        if len(parts) >= 2:
            set_code = parts[-2]
    if not set_code:
        raise CardDetailParseError(f'Could not parse set code for card {card_id}')

    subtext = normalize_space((soup.select_one('.subtext') or soup).get_text(' ', strip=True))
    number_match = CARD_NUMBER_RE.search(subtext)
    if number_match is None:
        raise CardDetailParseError(f'Could not parse collector number for card {card_id}')
    card_number = number_match.group(1)

    return {
        'game': 'pokemon',
        'set_code': set_code,
        'set_name': parse_set_name(soup),
        'card_number': card_number,
        'card_name_en': card_name_jp,
        'card_name_jp': card_name_jp,
        'rarity': rarity_from_detail(soup),
        'variant': '',
        'source_url': DETAIL_URL_TEMPLATE.format(card_id=card_id),
    }


async def fetch_page(client: httpx.AsyncClient, page: int) -> dict[str, Any]:
    response = await get_with_retries(
        client,
        RESULT_API_URL,
        params={'regulation_sidebar_form': 'all', 'page': page},
        label=f'result page {page}',
        retries=6,
    )
    payload = response.json()
    if int(payload.get('result') or 0) != 1:
        raise RuntimeError(f'Official Pokémon result API returned an error for page {page}: {payload}')
    return payload



async def fetch_detail(client: httpx.AsyncClient, card: dict[str, Any]) -> dict[str, Any]:
    card_id = str(card['cardID'])
    detail_url = DETAIL_URL_TEMPLATE.format(card_id=card_id)
    await asyncio.sleep(random.uniform(0.12, 0.28))
    try:
        response = await get_with_retries(
            client,
            detail_url,
            label=f'detail card {card_id}',
            retries=4,
        )
    except Exception as exc:
        raise CardDetailFetchError(f'Could not fetch detail page for card {card_id}: {exc}') from exc
    return parse_detail_html(
        response.text,
        card_id=card_id,
        thumb_path=str(card.get('cardThumbFile') or ''),
        card_name_fallback=str(card.get('cardNameAltText') or card.get('cardNameViewText') or card_id),
    )




def dedupe_card_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            str(row.get('game') or ''),
            str(row.get('set_code') or ''),
            str(row.get('card_number') or ''),
            str(row.get('variant') or ''),
        )
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = row
            continue
        existing_name = str(existing.get('card_name_jp') or existing.get('card_name_en') or '')
        candidate_name = str(row.get('card_name_jp') or row.get('card_name_en') or '')
        if len(candidate_name) > len(existing_name):
            deduped[key] = row
    return list(deduped.values())

def upsert_pokemon_sets(connection: psycopg.Connection, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    payload = Json(rows)
    update_sql = """
        update pokemon_sets as target
        set set_code = source.set_code,
            set_name = source.set_name,
            source_url = source.source_url,
            source_name = source.source_name
        from jsonb_to_recordset(%s::jsonb) as source(
            language text,
            set_code text,
            set_name text,
            source_url text,
            source_name text
        )
        where target.language = source.language
          and target.set_name = source.set_name
    """
    insert_sql = """
        insert into pokemon_sets (language, set_code, set_name, source_url, source_name)
        select source.language, source.set_code, source.set_name, source.source_url, source.source_name
        from jsonb_to_recordset(%s::jsonb) as source(
            language text,
            set_code text,
            set_name text,
            source_url text,
            source_name text
        )
        where not exists (
            select 1 from pokemon_sets target
            where target.language = source.language and target.set_name = source.set_name
        )
    """
    with connection.cursor() as cursor:
        cursor.execute(update_sql, (payload,))
        cursor.execute(insert_sql, (payload,))



def upsert_cards(connection: psycopg.Connection, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    payload = Json(rows)
    update_sql = """
        update cards as card
        set set_name = source.set_name,
            card_name_en = source.card_name_en,
            card_name_jp = source.card_name_jp,
            rarity = source.rarity,
            variant = nullif(source.variant, ''),
            is_active = true
        from jsonb_to_recordset(%s::jsonb) as source(
            game text,
            set_code text,
            set_name text,
            card_number text,
            card_name_en text,
            card_name_jp text,
            rarity text,
            variant text
        )
        where card.game = source.game
          and card.set_code = source.set_code
          and card.card_number = source.card_number
          and coalesce(card.variant, '') = coalesce(source.variant, '')
    """
    insert_sql = """
        insert into cards (
            game,
            set_code,
            set_name,
            card_number,
            card_name_en,
            card_name_jp,
            rarity,
            variant,
            is_active
        )
        select
            source.game,
            source.set_code,
            source.set_name,
            source.card_number,
            source.card_name_en,
            source.card_name_jp,
            source.rarity,
            nullif(source.variant, ''),
            true
        from jsonb_to_recordset(%s::jsonb) as source(
            game text,
            set_code text,
            set_name text,
            card_number text,
            card_name_en text,
            card_name_jp text,
            rarity text,
            variant text
        )
        where not exists (
            select 1
            from cards as card
            where card.game = source.game
              and card.set_code = source.set_code
              and card.card_number = source.card_number
              and coalesce(card.variant, '') = coalesce(source.variant, '')
        )
    """
    with connection.cursor() as cursor:
        cursor.execute(update_sql, (payload,))
        cursor.execute(insert_sql, (payload,))


async def run_import(*, start_page: int, end_page: int | None, concurrency: int, checkpoint_file: Path | None) -> dict[str, Any]:
    limits = httpx.Limits(max_connections=max(concurrency * 2, 20), max_keepalive_connections=max(concurrency, 10))
    timeout = httpx.Timeout(30.0, connect=30.0)
    imported_pages = 0
    imported_cards = 0
    page = start_page

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=_BROWSER_HEADERS, http2=False, limits=limits) as client:
        first_page = await fetch_page(client, page)
        max_page = int(first_page.get('maxPage') or page)
        if end_page is None or end_page > max_page:
            end_page = max_page

        while page <= end_page:
            payload = first_page if page == start_page else await fetch_page(client, page)
            card_list = list(payload.get('cardList') or [])
            page_sets: dict[tuple[str, str], dict[str, Any]] = {}
            semaphore = asyncio.Semaphore(concurrency)
            skipped_cards = 0

            async def _wrapped(card: dict[str, Any]) -> dict[str, Any] | None:
                async with semaphore:
                    try:
                        return await fetch_detail(client, card)
                    except (CardDetailParseError, CardDetailFetchError) as exc:
                        print(
                            json.dumps(
                                {
                                    'event': 'pokemon_jp_card_skipped',
                                    'page': page,
                                    'card_id': str(card.get('cardID') or ''),
                                    'card_name': str(card.get('cardNameAltText') or card.get('cardNameViewText') or ''),
                                    'reason': str(exc),
                                },
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )
                        return None

            detail_rows = [row for row in await asyncio.gather(*[_wrapped(card) for card in card_list]) if row is not None]
            deduped_rows = dedupe_card_rows(detail_rows)
            skipped_cards = len(card_list) - len(detail_rows) + (len(detail_rows) - len(deduped_rows))
            detail_rows = deduped_rows
            for row in detail_rows:
                page_sets[(row['set_code'], row['set_name'])] = {
                    'language': 'jp',
                    'set_code': row['set_code'],
                    'set_name': row['set_name'],
                    'source_url': row['source_url'],
                    'source_name': 'pokemon-card-official-jp',
                }

            with psycopg.connect(get_database_url(), autocommit=False) as connection:
                upsert_pokemon_sets(connection, list(page_sets.values()))
                upsert_cards(connection, detail_rows)
                connection.commit()

            imported_pages += 1
            imported_cards += len(detail_rows)
            checkpoint_payload = {
                'last_completed_page': page,
                'end_page': end_page,
                'imported_pages': imported_pages,
                'imported_cards': imported_cards,
                'skipped_cards': skipped_cards,
            }
            if checkpoint_file is not None:
                checkpoint_file.write_text(json.dumps(checkpoint_payload, ensure_ascii=False, indent=2))
            print(
                json.dumps(
                    {
                        'event': 'pokemon_jp_page_imported',
                        'page': page,
                        'cards': len(detail_rows),
                        'skipped_cards': skipped_cards,
                        'end_page': end_page,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            await asyncio.sleep(0.5 + random.uniform(0.0, 0.4))
            page += 1

    return {'pages': imported_pages, 'cards': imported_cards, 'end_page': end_page}



def main() -> None:
    parser = argparse.ArgumentParser(description='Import Japanese Pokémon cards from the official search API.')
    parser.add_argument('--start-page', type=int, default=1)
    parser.add_argument('--end-page', type=int, default=0, help='Optional ending page; default imports through the reported max page.')
    parser.add_argument('--concurrency', type=int, default=8)
    parser.add_argument('--checkpoint-file', default='.logs/pokemon_jp_import_checkpoint.json')
    parser.add_argument('--resume', action='store_true', help='Resume from the checkpoint file if present.')
    args = parser.parse_args()

    checkpoint_path = Path(args.checkpoint_file)
    start_page = args.start_page
    if args.resume and checkpoint_path.exists():
        payload = json.loads(checkpoint_path.read_text())
        start_page = int(payload.get('last_completed_page') or 0) + 1

    result = asyncio.run(
        run_import(
            start_page=start_page,
            end_page=(args.end_page or None),
            concurrency=max(1, args.concurrency),
            checkpoint_file=checkpoint_path,
        )
    )
    print(json.dumps({'event': 'pokemon_jp_import_complete', **result}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
