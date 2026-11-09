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
  # quelqu'un (Claude) a pu pousser entre-temps : on rejoue nos commits par-dessus
  for i in 1 2 3; do
    git pull -q --rebase && git push -q && break
    sleep 5
  done
fi
