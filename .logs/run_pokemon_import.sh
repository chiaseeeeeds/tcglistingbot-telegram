#!/bin/zsh
set -e
cd /Users/chiawei/orchids-projects/telegram-bot-api
.venv/bin/python - <<'PY'
import os, psycopg
from config import get_config
cfg = get_config()
dsn = os.getenv('DATABASE_POOLER_URL') or cfg.database_url
with psycopg.connect(dsn) as conn, conn.cursor() as cur:
    cur.execute('''
        select pid
        from pg_stat_activity
        where datname = current_database()
          and application_name='Supavisor'
          and state = 'idle in transaction'
    ''')
    for (pid,) in cur.fetchall():
        cur.execute('select pg_terminate_backend(%s)', (pid,))
        cur.fetchone()
    cur.execute('truncate table pokemon_cards_staging restart identity')
    cur.execute("delete from cards where game = 'pokemon'")
    conn.commit()
    print('reset complete', flush=True)
PY
.venv/bin/python -u scripts/import_pokemon_card_csv.py
