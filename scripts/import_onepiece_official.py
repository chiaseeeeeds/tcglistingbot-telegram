"""Import One Piece card data from the official EN and JP cardlist pages."""

from __future__ import annotations

import argparse
import html
import json
import os
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

EN_CARDLIST_URL = 'https://en.onepiece-cardgame.com/cardlist/'
JP_CARDLIST_URL = 'https://www.onepiece-cardgame.com/cardlist/'
SERIES_CODE_RE = re.compile(r'\[([^\]]+)\]')
CARD_ID_RE = re.compile(r'^(?P<set_code>[A-Z]+\d+)-(?P<number>\d+)(?:_(?P<variant>[A-Za-z0-9]+))?$')
RARITY_RE = re.compile(r'^(?P<code>[A-Z]+\d+-\d+(?:_[A-Za-z0-9]+)?)\s*\|\s*(?P<rarity>[^|]+?)\s*\|')
SET_NAME_RE = re.compile(r'Card Set\(s\)\s*(?P<set_name>.+?)\s*(?:CARD VIEW|Notes|$)')
JP_SET_NAME_RE = re.compile(r'収録商品\s*(?P<set_name>.+?)\s*(?:カードを見る|CARD VIEW|このカードのQ&A|$)')


def get_database_url() -> str:
    config = get_config()
    database_url = os.getenv('DATABASE_POOLER_URL') or config.database_url
    if not database_url:
        raise SystemExit('No database connection string found. Set DATABASE_POOLER_URL or DATABASE_URL.')
    return database_url


def normalize_space(value: str) -> str:
    return ' '.join(html.unescape(value).split())


def normalize_series_label(label: str) -> str:
    return normalize_space(BeautifulSoup(label, 'html.parser').get_text(' ', strip=True))


def canonical_series_code(label: str) -> str | None:
    match = SERIES_CODE_RE.search(label)
    if not match:
        return None
    raw_code = match.group(1).replace(' ', '').upper()
    if raw_code.startswith(('OP-', 'ST-', 'EB-', 'PRB-')):
        return raw_code.replace('-', '')
    if raw_code.startswith('P-'):
        return 'P'
    if raw_code == 'OP15-EB04':
        return 'EB04'
    return raw_code.replace('-', '')


def fetch_html(client: httpx.Client, *, url: str, data: dict[str, str] | None = None) -> str:
    response = client.get(url) if data is None else client.post(url, data=data)
    response.raise_for_status()
    return response.text


def parse_series_options(html_text: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html_text, 'html.parser')
    select = soup.find('select', {'name': 'series'})
    if select is None:
        raise RuntimeError('Could not find One Piece series selector on official cardlist page.')

    options: list[dict[str, str]] = []
    for option in select.find_all('option'):
        value = (option.get('value') or '').strip()
        label = normalize_series_label(option.decode_contents())
        code = canonical_series_code(label)
        if not value or not code:
            continue
        options.append({'series_id': value, 'series_code': code, 'series_label': label})
    return options


def extract_modal_text(modal) -> str:
    return normalize_space(modal.get_text(' ', strip=True))


def parse_cards_from_html(html_text: str, *, language: str, default_series_label: str) -> dict[str, dict[str, Any]]:
    soup = BeautifulSoup(html_text, 'html.parser')
    cards: dict[str, dict[str, Any]] = {}
    for anchor in soup.select('a.modalOpen[data-src^="#"]'):
        modal_id = (anchor.get('data-src') or '').lstrip('#')
        match = CARD_ID_RE.match(modal_id)
        if match is None:
            continue
        modal = soup.find(id=modal_id)
        if modal is None:
            continue
        modal_text = extract_modal_text(modal)
        rarity_match = RARITY_RE.search(modal_text)
        rarity = normalize_space(rarity_match.group('rarity')) if rarity_match else None
        set_name_match = SET_NAME_RE.search(modal_text) if language == 'en' else JP_SET_NAME_RE.search(modal_text)
        set_name = normalize_space(set_name_match.group('set_name')) if set_name_match else default_series_label
        image = anchor.find('img')
        card_name = normalize_space((image.get('alt') if image else '') or '')
        card_code = match.group('set_code') + '-' + match.group('number') + (f"_{match.group('variant')}" if match.group('variant') else '')
        cards[card_code] = {
            'set_code': match.group('set_code'),
            'card_number': match.group('number'),
            'variant': match.group('variant') or '',
            'rarity': rarity,
            'set_name': set_name,
            'card_name': card_name,
        }
    return cards


def upsert_cards(connection: psycopg.Connection, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
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
    payload = Json(rows)
    with connection.cursor() as cursor:
        cursor.execute(update_sql, (payload,))
        cursor.execute(insert_sql, (payload,))
    connection.commit()


def write_checkpoint(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description='Import One Piece cards from the official EN and JP cardlist pages.')
    parser.add_argument('--limit-series', type=int, default=0, help='Optional limit on the number of series pages to import per language.')
    parser.add_argument('--checkpoint-file', default='.logs/onepiece_import_checkpoint.json')
    args = parser.parse_args()

    checkpoint_path = Path(args.checkpoint_file) if args.checkpoint_file else None
    client = httpx.Client(timeout=60, follow_redirects=True, headers={'User-Agent': 'Mozilla/5.0'}, http2=False)
    en_root_html = fetch_html(client, url=EN_CARDLIST_URL)
    jp_root_html = fetch_html(client, url=JP_CARDLIST_URL)
    en_options = parse_series_options(en_root_html)
    jp_options = parse_series_options(jp_root_html)
    if args.limit_series > 0:
        en_options = en_options[:args.limit_series]
        jp_options = jp_options[:args.limit_series]

    english_cards: dict[str, dict[str, Any]] = {}
    processed_en = 0
    processed_jp = 0

    with psycopg.connect(get_database_url(), autocommit=False) as connection:
        for option in en_options:
            html_text = fetch_html(client, url=EN_CARDLIST_URL, data={'search': 'true', 'series': option['series_id']})
            parsed = parse_cards_from_html(html_text, language='en', default_series_label=option['series_label'])
            batch_rows: list[dict[str, Any]] = []
            for card_code, payload in parsed.items():
                row = {
                    'game': 'onepiece',
                    'set_code': payload['set_code'],
                    'set_name': payload['set_name'] or option['series_label'],
                    'card_number': payload['card_number'],
                    'card_name_en': payload['card_name'] or card_code,
                    'card_name_jp': None,
                    'rarity': payload['rarity'],
                    'variant': payload['variant'],
                }
                english_cards[card_code] = row
                batch_rows.append(row)
            upsert_cards(connection, batch_rows)
            processed_en += 1
            write_checkpoint(checkpoint_path, {'processed_en_series': processed_en, 'processed_jp_series': processed_jp, 'en_total': len(en_options), 'jp_total': len(jp_options)})
            print(json.dumps({'event': 'onepiece_en_series_imported', 'series_code': option['series_code'], 'cards': len(parsed), 'progress': f'{processed_en}/{len(en_options)}'}), flush=True)

        for option in jp_options:
            html_text = fetch_html(client, url=JP_CARDLIST_URL, data={'search': 'true', 'series': option['series_id']})
            parsed = parse_cards_from_html(html_text, language='jp', default_series_label=option['series_label'])
            batch_rows: list[dict[str, Any]] = []
            for card_code, payload in parsed.items():
                base = english_cards.get(card_code)
                if base is None:
                    base = {
                        'game': 'onepiece',
                        'set_code': payload['set_code'],
                        'set_name': payload['set_name'] or option['series_label'],
                        'card_number': payload['card_number'],
                        'card_name_en': payload['card_name'] or card_code,
                        'card_name_jp': payload['card_name'] or None,
                        'rarity': payload['rarity'],
                        'variant': payload['variant'],
                    }
                    english_cards[card_code] = base
                else:
                    if payload.get('card_name'):
                        base['card_name_jp'] = payload['card_name']
                    if payload.get('set_name') and (not base.get('set_name') or base.get('set_name') == option['series_label']):
                        base['set_name'] = payload['set_name']
                    if payload.get('rarity') and not base.get('rarity'):
                        base['rarity'] = payload['rarity']
                batch_rows.append(dict(base))
            upsert_cards(connection, batch_rows)
            processed_jp += 1
            write_checkpoint(checkpoint_path, {'processed_en_series': processed_en, 'processed_jp_series': processed_jp, 'en_total': len(en_options), 'jp_total': len(jp_options)})
            print(json.dumps({'event': 'onepiece_jp_series_imported', 'series_code': option['series_code'], 'cards': len(parsed), 'progress': f'{processed_jp}/{len(jp_options)}'}), flush=True)

    print(json.dumps({'event': 'onepiece_import_complete', 'cards_upserted': len(english_cards)}), flush=True)


if __name__ == '__main__':
    main()
