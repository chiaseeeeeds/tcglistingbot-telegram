"""Apply SQL migration files to the configured Postgres database."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import get_config


def main() -> None:
    """Run SQL files from `migrations/` in filename order using a direct or pooler URL."""

    config = get_config()
    database_url = os.getenv('DATABASE_POOLER_URL') or config.database_url
    if not database_url:
        raise SystemExit(
            'No database connection string found. Set DATABASE_POOLER_URL or DATABASE_URL.'
        )

    migration_dir = Path('migrations')
    migration_files = sorted(migration_dir.glob('*.sql'))
    if not migration_files:
        raise SystemExit('No migration files found.')

    try:
        with psycopg.connect(database_url) as connection:
            with connection.cursor() as cursor:
                for migration_file in migration_files:
                    sql = migration_file.read_text()
                    print(f'Applying {migration_file.name}...')
                    cursor.execute(sql)
            connection.commit()
    except psycopg.OperationalError as exc:
        raise SystemExit(
            'Database connection failed. If you are using a Supabase direct connection string, '
            'try the Session pooler connection string in DATABASE_POOLER_URL instead.'
        ) from exc

    print('Migrations applied successfully.')


if __name__ == '__main__':
    main()
