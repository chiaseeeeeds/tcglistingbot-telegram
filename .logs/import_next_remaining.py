import os
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path('/Users/chiawei/orchids-projects/telegram-bot-api')
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import psycopg
from config import get_config
from scripts.import_pokemon_card_csv import download_repo_archive, fetch_set_mappings, fetch_imported_source_files, process_file

cfg = get_config()
dsn = os.getenv('DATABASE_POOLER_URL') or cfg.database_url

csv_index = download_repo_archive()
entries = {entry['file_name']: entry for entry in csv_index}
ordered_names = [entry['file_name'] for entry in csv_index]

with psycopg.connect(dsn) as conn:
    set_mappings = fetch_set_mappings(conn)
    imported = fetch_imported_source_files(conn)

remaining = [name for name in ordered_names if name not in imported]
if not remaining:
    print('DONE')
    raise SystemExit(0)

target = remaining[0]
result = process_file(dsn, entries[target], set_mappings, str(uuid.uuid4()))
print({'target': target, **result, 'remaining_after': len(remaining) - 1})
