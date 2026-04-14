#!/bin/bash
set -u
cd "/Users/chiawei/orchids-projects/telegram-bot-api"
END_PAGE=586
get_current_start() {
  python3 - <<"PY2"
import json
from pathlib import Path
p = Path(".logs/pokemon_jp_import_checkpoint.json")
if p.exists():
    payload = json.loads(p.read_text())
    print(int(payload.get("last_completed_page") or 0) + 1)
else:
    print(1)
PY2
}
CURRENT="$(get_current_start)"
echo "[loop] resilient JP import starting from page ${CURRENT} to ${END_PAGE} at $(date)"
while [ "$CURRENT" -le "$END_PAGE" ]; do
  CHUNK_END=$((CURRENT + 19))
  if [ "$CHUNK_END" -gt "$END_PAGE" ]; then CHUNK_END="$END_PAGE"; fi
  ATTEMPT=1
  while true; do
    echo "[loop] chunk ${CURRENT}-${CHUNK_END} attempt ${ATTEMPT} at $(date)"
    if .venv/bin/python -u scripts/import_pokemon_jp_official.py       --start-page "$CURRENT"       --end-page "$CHUNK_END"       --concurrency 2       --checkpoint-file .logs/pokemon_jp_import_checkpoint.json; then
      break
    fi
    NEW_CURRENT="$(get_current_start)"
    echo "[loop] chunk failure for ${CURRENT}-${CHUNK_END}; checkpoint now says next page ${NEW_CURRENT} at $(date)"
    if [ "$NEW_CURRENT" -gt "$CURRENT" ]; then
      CURRENT="$NEW_CURRENT"
      CHUNK_END=$((CURRENT + 19))
      if [ "$CHUNK_END" -gt "$END_PAGE" ]; then CHUNK_END="$END_PAGE"; fi
      echo "[loop] adopting advanced checkpoint and retrying from ${CURRENT}-${CHUNK_END}"
    fi
    SLEEP_SECONDS=$((ATTEMPT * 20))
    if [ "$SLEEP_SECONDS" -gt 300 ]; then SLEEP_SECONDS=300; fi
    echo "[loop] sleeping ${SLEEP_SECONDS}s before retry"
    sleep "$SLEEP_SECONDS"
    ATTEMPT=$((ATTEMPT + 1))
  done
  CURRENT="$(get_current_start)"
done
echo "[loop] completed JP import through page ${END_PAGE} at $(date)"
