#!/usr/bin/env bash
# Lancé par cron : collecte puis pousse les nouvelles données sur GitHub.
# Tout est dans une fonction : bash lit le script en entier avant que
# git pull puisse le modifier.
main() {
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
source .venv/bin/activate

git pull -q --rebase
python collect.py "$@"
# Données d'événements WhoScored (n'échoue jamais : on réessaiera au prochain passage)
python collect_ws.py || true

git add data
if ! git diff --cached --quiet; then
  git commit -q -m "data: collecte $(date -u +%Y-%m-%d)"
  # quelqu'un (Claude) a pu pousser entre-temps : on rejoue nos commits par-dessus
  for i in 1 2 3; do
    git pull -q --rebase && git push -q && break
    sleep 5
  done
fi
}
main "$@"
exit
