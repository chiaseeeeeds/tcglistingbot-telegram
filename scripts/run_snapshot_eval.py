"""One-command snapshot refresh + offline OCR/resolver evaluation."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_BIN = PROJECT_ROOT / '.venv' / 'bin' / 'python'
DEFAULT_SNAPSHOT_PATH = PROJECT_ROOT / '.snapshots' / 'catalog_snapshot.json'
DEFAULT_LOG_DIR = PROJECT_ROOT / '.logs'


def _run_command(command: Sequence[str]) -> None:
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Refresh local catalog snapshot and run offline OCR/resolver evaluation.')
    parser.add_argument('--game', action='append', default=['pokemon'], help='Game(s) to include in the snapshot export. Repeatable.')
    parser.add_argument('--per-set', type=int, default=1, help='Synthetic cases per set for each enabled audit mode.')
    parser.add_argument('--limit', type=int, default=100, help='Optional cap for total evaluated cases. Use 0 for no cap.')
    parser.add_argument('--skip-exact-identifier', action='store_true', help='Skip synthetic exact-identifier cases.')
    parser.add_argument('--skip-unique-ratio', action='store_true', help='Skip synthetic unique-ratio cases.')
    parser.add_argument('--snapshot-out', default=str(DEFAULT_SNAPSHOT_PATH), help='Snapshot JSON output path.')
    parser.add_argument('--json-out', default='', help='Optional explicit evaluator JSON report path.')
    return parser.parse_args()


def build_report_path(*, explicit_path: str) -> Path:
    if explicit_path.strip():
        return Path(explicit_path).expanduser().resolve()
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    return (DEFAULT_LOG_DIR / f'ocr_eval_snapshot_{timestamp}.json').resolve()


def main() -> None:
    if not PYTHON_BIN.exists():
        raise SystemExit(f'Python virtualenv not found at {PYTHON_BIN}')

    args = parse_args()
    snapshot_path = Path(args.snapshot_out).expanduser().resolve()
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    report_path = build_report_path(explicit_path=args.json_out)

    export_command = [str(PYTHON_BIN), 'scripts/export_catalog_snapshot.py', '--out', str(snapshot_path)]
    for game in args.game:
        export_command.extend(['--game', str(game)])
    _run_command(export_command)

    eval_command = [
        str(PYTHON_BIN),
        'scripts/evaluate_ocr_resolver.py',
        '--catalog-snapshot',
        str(snapshot_path),
        '--per-set',
        str(args.per_set),
        '--json-out',
        str(report_path),
    ]
    if not args.skip_exact_identifier:
        eval_command.append('--synthetic-exact-identifier')
    if not args.skip_unique_ratio:
        eval_command.append('--synthetic-unique-ratio')
    if args.limit > 0:
        eval_command.extend(['--limit', str(args.limit)])
    _run_command(eval_command)
    print(f'Snapshot: {snapshot_path}')
    print(f'Report: {report_path}')


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
