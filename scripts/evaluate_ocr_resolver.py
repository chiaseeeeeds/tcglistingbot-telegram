"""Evaluate OCR + resolver behavior from a manifest and synthetic catalog audits."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_config
from db.catalog_snapshot import clear_catalog_snapshot_cache, load_catalog_snapshot
from db.cards import clear_card_catalog_cache
from db.pokemon_sets import clear_pokemon_set_cache
from services.card_identifier import CardIdentificationResult, identify_card_from_text
from services.ocr import OCRResult, extract_text_from_image


@dataclass(frozen=True)
class LoadedCase:
    case_id: str
    source: str
    kind: str
    game: str
    tags: tuple[str, ...]
    raw_text: str | None
    image_path: str | None
    expected: dict[str, Any]


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    source: str
    kind: str
    game: str
    tags: tuple[str, ...]
    passed: bool
    failure_reasons: tuple[str, ...]
    raw_text: str
    ocr_text: str | None
    identification: dict[str, Any]


def get_database_url() -> str:
    config = get_config()
    database_url = os.getenv('DATABASE_POOLER_URL') or config.database_url
    if not database_url:
        raise SystemExit('No database connection string found. Set DATABASE_POOLER_URL or DATABASE_URL.')
    return database_url


def load_manifest(path: Path) -> list[LoadedCase]:
    payload = json.loads(path.read_text())
    cases: list[LoadedCase] = []
    for item in payload.get('cases', []):
        cases.append(
            LoadedCase(
                case_id=str(item['id']),
                source=f'manifest:{path.name}',
                kind=str(item.get('kind') or 'text'),
                game=str(item.get('game') or 'pokemon'),
                tags=tuple(str(tag) for tag in item.get('tags', [])),
                raw_text=item.get('raw_text'),
                image_path=item.get('image_path'),
                expected=dict(item.get('expected') or {}),
            )
        )
    return cases


def _snapshot_rows(*, snapshot_payload: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
    if snapshot_payload is None:
        return []
    rows = snapshot_payload.get(key, [])
    if not isinstance(rows, list):
        raise SystemExit(f'Snapshot field must be a list: {key}')
    return [dict(row) for row in rows]


def build_synthetic_exact_identifier_cases(*, per_set: int = 1, snapshot_payload: dict[str, Any] | None = None) -> list[LoadedCase]:
    sql = """
        with ranked as (
            select
                c.set_code,
                c.set_name,
                c.card_number,
                coalesce(c.card_name_en, c.card_name_jp) as card_name,
                ps.card_count,
                row_number() over (
                    partition by c.set_code
                    order by length(coalesce(c.card_name_en, c.card_name_jp)) desc, c.card_number asc
                ) as set_rank
            from cards c
            join pokemon_sets ps
              on ps.set_code = c.set_code
             and ps.language = 'en'
            where c.game = 'pokemon'
              and c.is_active = true
              and ps.card_count is not null
              and coalesce(c.card_name_en, c.card_name_jp) <> ''
              and c.set_code ~ '^[A-Z0-9]{2,5}$'
              and c.card_number ~ '^[0-9]{1,3}$'
        )
        select set_code, set_name, card_number, card_name, card_count
        from ranked
        where set_rank <= %(per_set)s
        order by set_code, set_rank
    """
    cases: list[LoadedCase] = []
    with psycopg.connect(get_database_url()) as connection, connection.cursor() as cursor:
        cursor.execute(sql, {'per_set': per_set})
        for set_code, set_name, card_number, card_name, card_count in cursor.fetchall():
            ratio = f"{str(card_number).lstrip('0') or '0'}/{int(card_count):03d}"
            raw_text = f"IDENTIFIER: {set_code} {ratio} | NAME_EN: {card_name}"
            cases.append(
                LoadedCase(
                    case_id=f'exact_identifier:{set_code}:{card_number}',
                    source='synthetic:exact_identifier',
                    kind='text',
                    game='pokemon',
                    tags=('synthetic', 'catalog', 'exact_identifier'),
                    raw_text=raw_text,
                    image_path=None,
                    expected={
                        'matched': True,
                        'set_code': set_code,
                        'display_name_contains': str(card_name),
                        'resolver_in': ['exact_identifier'],
                    },
                )
            )
    return cases


def build_synthetic_unique_ratio_cases(*, per_set: int = 1, snapshot_payload: dict[str, Any] | None = None) -> list[LoadedCase]:
    sql = """
        with base as (
            select
                c.set_code,
                c.set_name,
                c.card_number,
                coalesce(c.card_name_en, c.card_name_jp) as card_name,
                ps.card_count,
                count(*) over (
                    partition by c.card_number, ps.card_count
                ) as ratio_match_count,
                row_number() over (
                    partition by c.set_code
                    order by length(coalesce(c.card_name_en, c.card_name_jp)) desc, c.card_number asc
                ) as set_rank
            from cards c
            join pokemon_sets ps
              on ps.set_code = c.set_code
             and ps.language = 'en'
            where c.game = 'pokemon'
              and c.is_active = true
              and ps.card_count is not null
              and coalesce(c.card_name_en, c.card_name_jp) <> ''
              and c.set_code ~ '^[A-Z0-9]{2,5}$'
              and c.card_number ~ '^[0-9]{1,3}$'
        )
        select set_code, set_name, card_number, card_name, card_count
        from base
        where ratio_match_count = 1
          and set_rank <= %(per_set)s
        order by set_code, set_rank
    """
    cases: list[LoadedCase] = []
    with psycopg.connect(get_database_url()) as connection, connection.cursor() as cursor:
        cursor.execute(sql, {'per_set': per_set})
        for set_code, set_name, card_number, card_name, card_count in cursor.fetchall():
            ratio = f"{str(card_number).lstrip('0') or '0'}/{int(card_count):03d}"
            raw_text = f"IDENTIFIER: {ratio} | NAME_EN: {card_name}"
            cases.append(
                LoadedCase(
                    case_id=f'unique_ratio:{set_code}:{card_number}',
                    source='synthetic:unique_ratio',
                    kind='text',
                    game='pokemon',
                    tags=('synthetic', 'catalog', 'unique_ratio'),
                    raw_text=raw_text,
                    image_path=None,
                    expected={
                        'matched': True,
                        'set_code': set_code,
                        'display_name_contains': str(card_name),
                    },
                )
            )
    return cases


def _identification_payload(result: CardIdentificationResult) -> dict[str, Any]:
    return {
        'matched': result.matched,
        'confidence': result.confidence,
        'display_name': result.display_name,
        'card_id': result.card_id,
        'resolver': str((result.metadata or {}).get('resolver') or ''),
        'set_code': str((result.metadata or {}).get('set_code') or (result.metadata or {}).get('detected_set_code') or ''),
        'metadata': dict(result.metadata or {}),
        'candidate_options': list(result.candidate_options or []),
        'match_reasons': list(result.match_reasons or []),
    }


def evaluate_case(case: LoadedCase) -> CaseOutcome:
    ocr_result: OCRResult | None = None
    raw_text = case.raw_text or ''
    if case.kind == 'image':
        if not case.image_path:
            raise ValueError(f'Image case {case.case_id} is missing image_path.')
        ocr_result = extract_text_from_image(case.image_path, game=case.game)
        raw_text = ocr_result.text

    identification = identify_card_from_text(raw_text=raw_text, game=case.game)
    observed = _identification_payload(identification)
    failures: list[str] = []
    expected = case.expected

    if 'matched' in expected and bool(expected['matched']) != observed['matched']:
        failures.append('matched_mismatch')
    if expected.get('set_code') and expected['set_code'] != observed['set_code']:
        failures.append('set_code_mismatch')
    if expected.get('display_name_contains'):
        needles = expected['display_name_contains']
        if isinstance(needles, str):
            needles = [needles]
        haystack = observed['display_name'].lower()
        if not all(str(needle).lower() in haystack for needle in needles):
            failures.append('display_name_mismatch')
    if expected.get('resolver_in'):
        allowed = {str(item) for item in expected['resolver_in']}
        if observed['resolver'] not in allowed:
            failures.append('resolver_mismatch')
    if expected.get('confidence_at_least') is not None:
        if float(observed['confidence']) < float(expected['confidence_at_least']):
            failures.append('confidence_too_low')
    if expected.get('ocr_contains') and ocr_result is not None:
        needles = expected['ocr_contains']
        if isinstance(needles, str):
            needles = [needles]
        haystack = ocr_result.text.lower()
        if not all(str(needle).lower() in haystack for needle in needles):
            failures.append('ocr_text_mismatch')
    if expected.get('top_candidate_contains'):
        top = ''
        options = observed['candidate_options']
        if options:
            top = str(options[0].get('display_name') or '')
        if str(expected['top_candidate_contains']).lower() not in top.lower():
            failures.append('top_candidate_mismatch')

    return CaseOutcome(
        case_id=case.case_id,
        source=case.source,
        kind=case.kind,
        game=case.game,
        tags=case.tags,
        passed=not failures,
        failure_reasons=tuple(failures),
        raw_text=raw_text,
        ocr_text=ocr_result.text if ocr_result is not None else None,
        identification=observed,
    )


def summarize(outcomes: list[CaseOutcome]) -> dict[str, Any]:
    total = len(outcomes)
    passed = sum(1 for item in outcomes if item.passed)
    failed = total - passed
    failures_by_reason: Counter[str] = Counter()
    failures_by_source: Counter[str] = Counter()
    failures_by_tag: Counter[str] = Counter()
    for item in outcomes:
        if item.passed:
            continue
        failures_by_source[item.source] += 1
        for reason in item.failure_reasons:
            failures_by_reason[reason] += 1
        for tag in item.tags:
            failures_by_tag[tag] += 1
    return {
        'total_cases': total,
        'passed_cases': passed,
        'failed_cases': failed,
        'pass_rate': round((passed / total) * 100, 2) if total else 0.0,
        'failures_by_reason': dict(failures_by_reason.most_common()),
        'failures_by_source': dict(failures_by_source.most_common()),
        'failures_by_tag': dict(failures_by_tag.most_common()),
    }


def print_summary(summary: dict[str, Any], outcomes: list[CaseOutcome]) -> None:
    print(json.dumps({'summary': summary}, indent=2))
    if summary['failed_cases']:
        print('\nFailing cases:')
        for item in outcomes:
            if item.passed:
                continue
            print(f'- {item.case_id}: {", ".join(item.failure_reasons)} | resolver={item.identification["resolver"]} | display={item.identification["display_name"]}')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Evaluate OCR + resolver behavior from manifests and synthetic catalog audits.')
    parser.add_argument('--manifest', action='append', default=[], help='Path to a JSON manifest file.')
    parser.add_argument('--synthetic-exact-identifier', action='store_true', help='Generate synthetic exact identifier cases across imported Pokémon sets.')
    parser.add_argument('--synthetic-unique-ratio', action='store_true', help='Generate synthetic unique printed-ratio cases across imported Pokémon sets.')
    parser.add_argument('--per-set', type=int, default=1, help='How many synthetic cases to generate per set.')
    parser.add_argument('--limit', type=int, default=0, help='Optional max number of cases to evaluate.')
    parser.add_argument('--json-out', default='', help='Optional path to write full JSON results.')
    parser.add_argument('--catalog-snapshot', default='', help='Optional local snapshot JSON path for offline catalog-backed evaluation.')
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    snapshot_payload: dict[str, Any] | None = None
    if args.catalog_snapshot:
        snapshot_path = Path(args.catalog_snapshot).expanduser().resolve()
        os.environ['CARD_CATALOG_SNAPSHOT_PATH'] = str(snapshot_path)
        clear_catalog_snapshot_cache()
        clear_card_catalog_cache()
        clear_pokemon_set_cache()
        snapshot_payload = load_catalog_snapshot()
        if snapshot_payload is None:
            raise SystemExit('Snapshot path was provided but no snapshot payload could be loaded.')

    cases: list[LoadedCase] = []
    for manifest in args.manifest:
        cases.extend(load_manifest(Path(manifest)))
    if args.synthetic_exact_identifier:
        cases.extend(build_synthetic_exact_identifier_cases(per_set=args.per_set, snapshot_payload=snapshot_payload))
    if args.synthetic_unique_ratio:
        cases.extend(build_synthetic_unique_ratio_cases(per_set=args.per_set, snapshot_payload=snapshot_payload))
    if args.limit > 0:
        cases = cases[: args.limit]
    if not cases:
        raise SystemExit('No evaluation cases were selected.')

    outcomes = [evaluate_case(case) for case in cases]
    summary = summarize(outcomes)
    print_summary(summary, outcomes)

    if args.json_out:
        output_path = Path(args.json_out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(
                {
                    'summary': summary,
                    'cases': [
                        {
                            'case_id': item.case_id,
                            'source': item.source,
                            'kind': item.kind,
                            'game': item.game,
                            'tags': list(item.tags),
                            'passed': item.passed,
                            'failure_reasons': list(item.failure_reasons),
                            'raw_text': item.raw_text,
                            'ocr_text': item.ocr_text,
                            'identification': item.identification,
                        }
                        for item in outcomes
                    ],
                },
                indent=2,
            )
        )

    if summary['failed_cases']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
