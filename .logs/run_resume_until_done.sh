#!/bin/zsh
set -e
cd /Users/chiawei/orchids-projects/telegram-bot-api
for attempt in {1..20}; do
  echo "=== resume pass $attempt ===" >> .logs/pokemon_import.log
  .venv/bin/python -u scripts/import_pokemon_card_csv.py >> .logs/pokemon_import.log 2>&1 || true
  remaining=$(.venv/bin/python - <<'PY'
import os, psycopg
from config import get_config
from scripts.import_pokemon_card_csv import download_repo_archive
cfg=get_config(); dsn=os.getenv('DATABASE_POOLER_URL') or cfg.database_url
all_files = [entry['file_name'] for entry in download_repo_archive()]
with psycopg.connect(dsn) as conn, conn.cursor() as cur:
    cur.execute('select distinct source_file from pokemon_cards_staging')
    imported = {row[0] for row in cur.fetchall()}
print(len([name for name in all_files if name not in imported]))
PY
)
  echo "remaining_files=$remaining" >> .logs/pokemon_import.log
  if [ "$remaining" = "0" ]; then
    break
  fi
  sleep 2
done
