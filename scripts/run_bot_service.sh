#!/bin/zsh
set -eu
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p .logs
export PYTHONUNBUFFERED=1
if [ ! -x .venv/bin/python ]; then
  echo "$(date '+%Y-%m-%d %H:%M:%S') missing .venv/bin/python" >> .logs/bot.err
  exit 127
fi
exec .venv/bin/python -u main.py
