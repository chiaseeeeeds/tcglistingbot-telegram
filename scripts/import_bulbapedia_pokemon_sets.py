"""Import English Pokémon set metadata from Bulbapedia into `pokemon_sets`."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
import psycopg
from bs4 import BeautifulSoup, Tag

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_config

SOURCE_URL = 'https://bulbapedia.bulbagarden.net/wiki/List_of_Pok%C3%A9mon_Trading_Card_Game_expansions'
SOURCE_NAME = 'bulbapedia'
SERIES_STOP_MARKERS = {
    'Japanese-exclusive releases',
    'Japanese-exclusive expansions',
    'Japanese-exclusive decks',
    'Japanese-exclusive promotional cards',
}


def get_database_url() -> str:
    config = get_config()
    database_url = os.getenv('DATABASE_POOLER_URL') or config.database_url
    if not database_url:
        raise SystemExit('No database connection string found. Set DATABASE_POOLER_URL or DATABASE_URL.')
    return database_url


def normalize_whitespace(value: str) -> str:
    return ' '.join(value.split())


def parse_card_count(value: str) -> int | None:
    digits = ''.join(character for character in value if character.isdigit())
    return int(digits) if digits else None


def parse_release_date(value: str) -> str | None:
    normalized = normalize_whitespace(value)
    if not normalized or normalized in {'—', '-'}:
        return None
    for fmt in ('%B %d, %Y', '%B %Y', '%Y'):
        try:
            parsed = datetime.strptime(normalized, fmt)
            if fmt == '%B %Y':
                return parsed.date().replace(day=1).isoformat()
            if fmt == '%Y':
                return parsed.date().replace(month=1, day=1).isoformat()
            return parsed.date().isoformat()
        except ValueError:
            continue
    return None


def extract_series_name(table: Tag) -> str | None:
    current: Tag | None = table
    while current is not None:
        current = current.find_previous(['h2', 'h3', 'h4'])
        if current is None:
            return None
        headline = normalize_whitespace(current.get_text(' ', strip=True).replace('[edit]', ''))
        if not headline:
            continue
        if headline in SERIES_STOP_MARKERS:
            return None
        return headline
    return None


def map_header_positions(header_cells: list[str]) -> dict[str, int]:
    return {header: index for index, header in enumerate(header_cells)}


def get_cell_text(cells: list[Tag], header_map: dict[str, int], header_name: str) -> str:
    index = header_map.get(header_name)
    if index is None or index >= len(cells):
        return ''
    return normalize_whitespace(cells[index].get_text(' ', strip=True))


def get_cell_image_url(cells: list[Tag], header_map: dict[str, int], header_name: str) -> str | None:
    index = header_map.get(header_name)
    if index is None or index >= len(cells):
        return None
    image = cells[index].find('img')
    if image is None:
        return None
    source = image.get('src') or image.get('data-src') or ''
    if not source:
        return None
    return urljoin(SOURCE_URL, source)


def fetch_rows() -> list[dict[str, Any]]:
    client = httpx.Client(timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
    html = client.get(SOURCE_URL).text
    soup = BeautifulSoup(html, 'html.parser')

    rows: list[dict[str, Any]] = []
    for table in soup.select('table'):
        header_cells = [normalize_whitespace(th.get_text(' ', strip=True)) for th in table.select('tr th')[:8]]
        if 'Name of Expansion' not in header_cells or 'Set abb.' not in header_cells:
            continue

        series_name = extract_series_name(table)
        if series_name is None or series_name in SERIES_STOP_MARKERS:
            continue

        header_map = map_header_positions(header_cells)
        for row in table.select('tr')[1:]:
            cells = row.find_all('td')
            if not cells:
                continue
            set_name = get_cell_text(cells, header_map, 'Name of Expansion')
            if not set_name:
                continue
            rows.append(
                {
                    'language': 'en',
                    'series_name': series_name,
                    'set_number': get_cell_text(cells, header_map, 'Set no.') or None,
                    'set_name': set_name,
                    'set_code': get_cell_text(cells, header_map, 'Set abb.') or None,
                    'expansion_type': get_cell_text(cells, header_map, 'Type of Expansion') or None,
                    'card_count': parse_card_count(get_cell_text(cells, header_map, 'No. of cards')),
                    'release_date': parse_release_date(
                        get_cell_text(cells, header_map, 'Release date')
                        or get_cell_text(cells, header_map, 'Release period')
                    ),
                    'symbol_image_url': get_cell_image_url(cells, header_map, 'Symbol'),
                    'logo_image_url': get_cell_image_url(cells, header_map, 'Logo of Expansion'),
                    'source_url': SOURCE_URL,
                }
            )
    return rows


def upsert_rows(rows: list[dict[str, Any]]) -> int:
    sql = """
        insert into pokemon_sets (
            language,
            series_name,
            set_number,
            set_name,
            set_code,
            expansion_type,
            card_count,
            release_date,
            symbol_image_url,
            logo_image_url,
            source_url,
            source_name
        )
        values (
            %(language)s,
            %(series_name)s,
            %(set_number)s,
            %(set_name)s,
            %(set_code)s,
            %(expansion_type)s,
            %(card_count)s,
            %(release_date)s,
            %(symbol_image_url)s,
            %(logo_image_url)s,
            %(source_url)s,
            %(source_name)s
        )
        on conflict (language, set_name)
        do update set
            series_name = excluded.series_name,
            set_number = excluded.set_number,
            set_code = excluded.set_code,
            expansion_type = excluded.expansion_type,
            card_count = excluded.card_count,
            release_date = excluded.release_date,
            symbol_image_url = excluded.symbol_image_url,
            logo_image_url = excluded.logo_image_url,
            source_url = excluded.source_url,
            source_name = excluded.source_name,
            updated_at = now()
    """
    with psycopg.connect(get_database_url()) as connection:
        with connection.cursor() as cursor:
            for row in rows:
                cursor.execute(sql, {**row, 'source_name': SOURCE_NAME})
        connection.commit()
    return len(rows)


def main() -> None:
    rows = fetch_rows()
    imported = upsert_rows(rows)
    print({'rows_imported': imported, 'source_url': SOURCE_URL})


if __name__ == '__main__':
    main()
