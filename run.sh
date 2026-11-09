#!/usr/bin/env bash
# Lancé par cron : collecte puis pousse les nouvelles données sur GitHub.
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate

git pull -q --rebase
python collect.py "$@"

git add data
if ! git diff --cached --quiet; then
  git commit -q -m "data: collecte $(date -u +%Y-%m-%d)"
  git push -q
fi
