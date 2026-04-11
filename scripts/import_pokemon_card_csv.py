"""Import English Pokémon card CSV data from GitHub and normalize it into staging + cards."""

from __future__ import annotations

import csv
import argparse
import json
import os
import re
import sys
import tempfile
import unicodedata
import uuid
import zipfile
import time
from pathlib import Path
from typing import Any

import httpx
import psycopg
from psycopg.types.json import Json

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_config

GITHUB_ZIP_URL = 'https://github.com/tradingcarddex/Pokemon-Card-CSV/archive/refs/heads/main.zip'
SOURCE_NAME = 'pokemon-card-csv'
CARD_NUMBER_RE = re.compile(r'^(?P<left>[A-Za-z0-9]+)(?:/(?P<right>[A-Za-z0-9]+))?$')
SET_NAME_SPLIT_RE = re.compile(r'\s*[—–:/|]+\s*')
VARIANT_HINTS = ['Reverse Holo', 'Holo', 'Promo', 'Full Art', 'Illustration Rare', 'Special Illustration Rare']
MANUAL_SET_NAME_OVERRIDES = {
    'Wizards Black Star Promos': 'Wizards Black Star Promos',
    'POP Series 1': 'POP Series 1',
    'McDonald Collection 2017': 'McDonald\'s Collection 2017',
}



MAX_FILE_RETRIES = 3
RETRY_SLEEP_SECONDS = 3

def log_progress(event: str, **details: Any) -> None:
    payload = {'event': event, **details}
    print(json.dumps(payload), flush=True)


def get_database_url() -> str:
    config = get_config()
    database_url = os.getenv('DATABASE_POOLER_URL') or config.database_url
    if not database_url:
        raise SystemExit('No database connection string found. Set DATABASE_POOLER_URL or DATABASE_URL.')
    return database_url


def normalize_whitespace(value: str) -> str:
    return ' '.join(value.split())


def canonicalize_set_name(value: str) -> str:
    normalized = unicodedata.normalize('NFKD', normalize_whitespace(value)).encode('ascii', 'ignore').decode('ascii')
    normalized = normalized.lower()
    replacements = {
        '&': ' and ',
        '—': ' ',
        '-': ' ',
        ':': ' ',
        "'": '',
        '.': ' ',
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    normalized = normalized.replace('pokemon tcg', 'pokemon')
    normalized = normalized.replace('pokemon', 'pokemon ')
    normalized = normalized.replace('trainer gallery', '')
    normalized = normalized.replace('galarian gallery', '')
    normalized = normalized.replace('classic collection', '')
    normalized = normalized.replace('shiny vault', '')
    normalized = normalized.replace('radiant collection', '')
    normalized = normalized.replace('galaxy holo', '')
    normalized = ' '.join(normalized.split())
    alias_map = {
        'base': 'base set',
        'black and white': 'black and white',
        'diamond and pearl': 'diamond and pearl',
        'firered and leafgreen': 'ex firered and leafgreen',
        'fire red and leaf green': 'ex firered and leafgreen',
        'go': 'pokemon go',
        '151': 'scarlet and violet 151',
        'pokemon go': 'pokemon go',
        'deoxys': 'ex deoxys',
        'dragon': 'ex dragon',
        'team rocket returns': 'ex team rocket returns',
        'evolutions': 'xy evolutions',
        'futsal collection': 'pokemon futsal',
        'ex trainer kit latias': 'latias trainer kit',
        'ex trainer kit latios': 'latios trainer kit',
        'ex trainer kit 2 minun': 'minun trainer kit 2',
        'ex trainer kit 2 plusle': 'plusle trainer kit 2',
    }
    return alias_map.get(normalized, normalized)


def slug_to_set_name(file_name: str) -> str:
    stem = file_name.removesuffix('.csv')
    stem = stem.removeprefix('Pokemon-')
    stem = stem.replace('-', ' ')
    stem = normalize_whitespace(stem)
    return MANUAL_SET_NAME_OVERRIDES.get(stem, stem)


def set_name_aliases(set_name: str) -> set[str]:
    aliases: set[str] = set()
    canonical_full = canonicalize_set_name(set_name)
    if canonical_full:
        aliases.add(canonical_full)
    parts = [part for part in SET_NAME_SPLIT_RE.split(set_name) if normalize_whitespace(part)]
    if len(parts) > 1:
        canonical_suffix = canonicalize_set_name(parts[-1])
        if canonical_suffix:
            aliases.add(canonical_suffix)
    return aliases


def download_repo_archive() -> list[dict[str, str]]:
    client = httpx.Client(timeout=60, follow_redirects=True, headers={'User-Agent': 'Mozilla/5.0'})
    response = client.get(GITHUB_ZIP_URL)
    response.raise_for_status()

    temp_dir = Path(tempfile.mkdtemp(prefix='pokemon-card-csv-'))
    archive_path = temp_dir / 'pokemon-card-csv.zip'
    archive_path.write_bytes(response.content)

    extract_dir = temp_dir / 'repo'
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(extract_dir)

    root_dir = next(extract_dir.iterdir())
    csv_index: list[dict[str, str]] = []
    for csv_path in sorted(root_dir.rglob('*.csv')):
        relative = csv_path.relative_to(root_dir)
        parts = relative.parts
        if len(parts) < 2:
            continue
        csv_index.append(
            {
                'series_name': parts[0],
                'file_name': csv_path.name,
                'download_url': GITHUB_ZIP_URL,
                'html_url': f'https://github.com/tradingcarddex/Pokemon-Card-CSV/blob/main/{relative.as_posix()}',
                'local_path': str(csv_path),
            }
        )
    return csv_index


def resolve_set_mapping(set_name: str, set_mappings: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    canonical = canonicalize_set_name(set_name)
    exact = set_mappings.get(canonical)
    if exact:
        return exact


    explicit_map = {
        'latias trainer kit': {'set_name': 'Latias Trainer Kit', 'set_code': 'LTK'},
        'latios trainer kit': {'set_name': 'Latios Trainer Kit', 'set_code': 'LTI'},
        'minun trainer kit 2': {'set_name': 'EX Trainer Kit 2 Minun', 'set_code': 'TK2M'},
        'plusle trainer kit 2': {'set_name': 'EX Trainer Kit 2 Plusle', 'set_code': 'TK2P'},
        'vivid voltage': {'set_name': 'Sword & Shield—Vivid Voltage', 'set_code': 'VIV'},
        'ancient origins': {'set_name': 'XY—Ancient Origins', 'set_code': 'AOR'},
        'breakpoint': {'set_name': 'XY—BREAKpoint', 'set_code': 'BKP'},
        'breakthrough': {'set_name': 'XY—BREAKthrough', 'set_code': 'BKT'},
        'double crisis': {'set_name': 'Double Crisis', 'set_code': 'DCR'},
        'fates collide': {'set_name': 'XY—Fates Collide', 'set_code': 'FCO'},
        'flashfire': {'set_name': 'XY—Flashfire', 'set_code': 'FLF'},
        'furious fists': {'set_name': 'XY—Furious Fists', 'set_code': 'FFI'},
        'generations': {'set_name': 'Generations', 'set_code': 'GEN'},
        'kalos starter set': {'set_name': 'XY—Kalos Starter Set', 'set_code': 'KSS'},
        'phantom forces': {'set_name': 'XY—Phantom Forces', 'set_code': 'PHF'},
        'primal clash': {'set_name': 'XY—Primal Clash', 'set_code': 'PRC'},
        'roaring skies': {'set_name': 'XY—Roaring Skies', 'set_code': 'ROS'},
        'steam siege': {'set_name': 'XY—Steam Siege', 'set_code': 'STS'},
        'xy black star promos': {'set_name': 'XY Black Star Promos', 'set_code': 'XYP'},
        'xy': {'set_name': 'XY', 'set_code': 'XY'},
        'white flare': {'set_name': 'Scarlet & Violet—White Flare', 'set_code': 'WHT'},
    }
    if canonical in explicit_map:
        return explicit_map[canonical]

    candidates = []
    for mapped_name, mapped_value in set_mappings.items():
        if canonical in mapped_name or mapped_name in canonical:
            candidates.append(mapped_value)
    if len(candidates) == 1:
        return candidates[0]

    return None


def fetch_imported_source_files(connection: psycopg.Connection) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute("select distinct source_file from pokemon_cards_staging")
        rows = cursor.fetchall()
    return {row[0] for row in rows}


def build_staging_payloads(csv_entry: dict[str, str], set_name: str, set_code: str | None, batch_id: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for row in fetch_csv_rows(csv_entry):
        card_number_left, printed_total = parse_card_number(row['Number'])
        variant = derive_variant(row['Name'], row['Rarity']) or ''
        payloads.append(
            {
                'language': 'en',
                'series_name': csv_entry['series_name'],
                'set_name': set_name,
                'set_code': set_code,
                'card_name': row['Name'],
                'card_number': card_number_left,
                'printed_total': printed_total,
                'rarity': row['Rarity'],
                'variant': variant,
                'source_file': csv_entry['file_name'],
                'source_url': csv_entry['html_url'],
                'source_name': SOURCE_NAME,
                'raw_payload': row,
                'import_batch_id': batch_id,
            }
        )
    return payloads


def process_file(
    database_url: str,
    csv_entry: dict[str, str],
    set_mappings: dict[str, dict[str, Any]],
    batch_id: str,
) -> dict[str, Any]:
    set_name = slug_to_set_name(csv_entry['file_name'])
    set_mapping = resolve_set_mapping(set_name, set_mappings)
    set_code = set_mapping['set_code'] if set_mapping else None
    payloads = build_staging_payloads(csv_entry, set_name, set_code, batch_id)

    staging_sql = """
        insert into pokemon_cards_staging (
            language,
            series_name,
            set_name,
            set_code,
            card_name,
            card_number,
            printed_total,
            rarity,
            variant,
            source_file,
            source_url,
            source_name,
            raw_payload,
            import_batch_id
        )
        select
            record.language,
            record.series_name,
            record.set_name,
            record.set_code,
            record.card_name,
            record.card_number,
            record.printed_total,
            record.rarity,
            record.variant,
            record.source_file,
            record.source_url,
            record.source_name,
            record.raw_payload,
            record.import_batch_id
        from jsonb_to_recordset(%s::jsonb) as record(
            language text,
            series_name text,
            set_name text,
            set_code text,
            card_name text,
            card_number text,
            printed_total text,
            rarity text,
            variant text,
            source_file text,
            source_url text,
            source_name text,
            raw_payload jsonb,
            import_batch_id text
        )
        on conflict (language, set_name, card_name, card_number, variant)
        do update set
            series_name = excluded.series_name,
            set_code = excluded.set_code,
            printed_total = excluded.printed_total,
            rarity = excluded.rarity,
            source_file = excluded.source_file,
            source_url = excluded.source_url,
            raw_payload = excluded.raw_payload,
            import_batch_id = excluded.import_batch_id,
            updated_at = now()
    """

    card_update_sql = """
        update cards as card
        set set_name = staging.set_name,
            card_name_en = staging.card_name,
            rarity = staging.rarity,
            variant = nullif(staging.variant, ''),
            is_active = true
        from pokemon_cards_staging as staging
        where staging.import_batch_id = %s
          and staging.source_file = %s
          and staging.set_code is not null
          and card.game = 'pokemon'
          and card.set_code = staging.set_code
          and card.card_number = staging.card_number
          and coalesce(card.variant, '') = staging.variant
    """

    card_insert_sql = """
        insert into cards (
            game,
            set_code,
            set_name,
            card_number,
            card_name_en,
            rarity,
            variant,
            is_active,
            created_at
        )
        select
            'pokemon',
            staging.set_code,
            staging.set_name,
            staging.card_number,
            staging.card_name,
            staging.rarity,
            nullif(staging.variant, ''),
            true,
            now()
        from (
            select distinct on (source.set_code, source.card_number, source.variant)
                source.set_code,
                source.set_name,
                source.card_number,
                source.card_name,
                source.rarity,
                source.variant
            from pokemon_cards_staging as source
            where source.import_batch_id = %s
              and source.source_file = %s
              and source.set_code is not null
            order by source.set_code, source.card_number, source.variant, source.card_name
        ) as staging
        left join cards as card
            on card.game = 'pokemon'
           and card.set_code = staging.set_code
           and card.card_number = staging.card_number
           and coalesce(card.variant, '') = staging.variant
        where card.id is null
    """

    staging_link_sql = """
        update pokemon_cards_staging as staging
        set normalized_card_id = card.id,
            updated_at = now()
        from cards as card
        where staging.import_batch_id = %s
          and staging.source_file = %s
          and staging.set_code is not null
          and card.game = 'pokemon'
          and card.set_code = staging.set_code
          and card.card_number = staging.card_number
          and coalesce(card.variant, '') = staging.variant
    """

    if not payloads:
        return {'rows': 0, 'cards': 0, 'set_name': set_name, 'set_code': set_code}

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(staging_sql, (json.dumps(payloads),))
            cards_upserted = 0
            if set_code:
                cursor.execute(card_update_sql, (batch_id, csv_entry['file_name']))
                cursor.execute(card_insert_sql, (batch_id, csv_entry['file_name']))
                cursor.execute(staging_link_sql, (batch_id, csv_entry['file_name']))
                cards_upserted = len(payloads)
            connection.commit()
    return {'rows': len(payloads), 'cards': cards_upserted, 'set_name': set_name, 'set_code': set_code}


def fetch_set_mappings(connection: psycopg.Connection) -> dict[str, dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(
            "select set_name, set_code, series_name from pokemon_sets where language = 'en'"
        )
        rows = cursor.fetchall()
    mappings: dict[str, dict[str, Any]] = {}
    ambiguous_aliases: set[str] = set()
    for set_name, set_code, series_name in rows:
        mapping = {'set_code': set_code, 'series_name': series_name, 'set_name': set_name}
        for alias in set_name_aliases(set_name):
            existing = mappings.get(alias)
            if existing is not None and existing['set_code'] != set_code:
                ambiguous_aliases.add(alias)
                continue
            mappings[alias] = mapping
    for alias in ambiguous_aliases:
        mappings.pop(alias, None)
    return mappings


def fetch_existing_cards(connection: psycopg.Connection) -> dict[tuple[str, str, str], str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            select id, set_code, card_number, coalesce(variant, '')
            from cards
            where game = 'pokemon'
            """
        )
        rows = cursor.fetchall()
    return {
        (set_code, card_number, variant): str(card_id)
        for card_id, set_code, card_number, variant in rows
    }


def parse_card_number(value: str) -> tuple[str, str | None]:
    normalized = normalize_whitespace(value)
    match = CARD_NUMBER_RE.match(normalized)
    if not match:
        return normalized, None
    return match.group('left'), match.group('right')


def derive_variant(card_name: str, rarity: str) -> str | None:
    for hint in VARIANT_HINTS:
        if hint.lower() in card_name.lower() or hint.lower() in rarity.lower():
            return hint
    return None


def fetch_csv_rows(csv_entry: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(csv_entry['local_path']).open('r', encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            name = normalize_whitespace(row.get('Name', ''))
            number = normalize_whitespace(row.get('Number', ''))
            rarity = normalize_whitespace(row.get('Rarity', ''))
            if not name or not number:
                continue
            rows.append({'Name': name, 'Number': number, 'Rarity': rarity})
    return rows


def import_all(resume: bool = True) -> dict[str, Any]:
    started_at = time.perf_counter()
    log_progress('import_started', resume=resume)
    database_url = get_database_url()
    batch_id = str(uuid.uuid4())
    log_progress('download_started', source=GITHUB_ZIP_URL)
    csv_index = download_repo_archive()
    log_progress('download_completed', csv_files=len(csv_index), elapsed_seconds=round(time.perf_counter() - started_at, 2))

    log_progress('db_connect_started')
    with psycopg.connect(database_url) as connection:
        log_progress('db_connect_completed', elapsed_seconds=round(time.perf_counter() - started_at, 2))
        set_mappings = fetch_set_mappings(connection)
        imported_source_files = fetch_imported_source_files(connection) if resume else set()
    log_progress(
        'set_mappings_loaded',
        count=len(set_mappings),
        imported_source_files=len(imported_source_files),
        elapsed_seconds=round(time.perf_counter() - started_at, 2),
    )

    imported_staging = 0
    imported_cards = 0
    unresolved_sets: set[str] = set()
    skipped_files = 0

    for file_index, csv_entry in enumerate(csv_index, start=1):
        file_name = csv_entry['file_name']
        if file_name in imported_source_files:
            skipped_files += 1
            log_progress('file_skipped', progress_files=f'{file_index}/{len(csv_index)}', current_file=file_name)
            continue

        last_error: Exception | None = None
        for attempt in range(1, MAX_FILE_RETRIES + 1):
            try:
                result = process_file(database_url, csv_entry, set_mappings, batch_id)
                imported_staging += result['rows']
                imported_cards += result['cards']
                if not result['set_code']:
                    unresolved_sets.add(result['set_name'])
                log_progress(
                    'file_imported',
                    progress_files=f'{file_index}/{len(csv_index)}',
                    current_file=file_name,
                    current_file_rows=result['rows'],
                    staging_rows_imported=imported_staging,
                    cards_upserted=imported_cards,
                    unresolved_set_count=len(unresolved_sets),
                    attempt=attempt,
                )
                imported_source_files.add(file_name)
                break
            except (psycopg.OperationalError, psycopg.InterfaceError, OSError) as exc:
                last_error = exc
                log_progress(
                    'file_retry',
                    progress_files=f'{file_index}/{len(csv_index)}',
                    current_file=file_name,
                    attempt=attempt,
                    error=str(exc),
                )
                time.sleep(RETRY_SLEEP_SECONDS * attempt)
        else:
            raise RuntimeError(f'Failed to import {file_name} after {MAX_FILE_RETRIES} attempts') from last_error

    return {
        'batch_id': batch_id,
        'csv_files': len(csv_index),
        'skipped_files': skipped_files,
        'staging_rows_imported': imported_staging,
        'cards_upserted': imported_cards,
        'unresolved_sets': sorted(unresolved_sets),
        'unresolved_set_count': len(unresolved_sets),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-resume', action='store_true', help='Reprocess all files instead of skipping already imported source files.')
    args = parser.parse_args()

    result = import_all(resume=not args.no_resume)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
