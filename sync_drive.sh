#!/usr/bin/env bash
# Envoie les rapports PDF du dépôt vers Google Drive, dans le dossier
# « Premier League – Rapports » (remote rclone "gdrive", accès limité aux
# fichiers créés par rclone : scope drive.file). --checksum : renvoie un PDF
# seulement si son contenu a changé (rapport corrigé).
# Tout est dans une fonction : bash lit le script en entier avant que
# git pull puisse le modifier.
main() {
  set -euo pipefail
  # cron n'a qu'un PATH minimal : on ajoute les emplacements habituels de rclone
  export PATH="/usr/local/bin:/usr/bin:/bin:/snap/bin:$PATH"
  cd "$(dirname "$(readlink -f "$0")")"
  command -v rclone >/dev/null || { echo "[sync] $(date -u +%FT%TZ) rclone introuvable"; exit 1; }
  git pull -q --rebase
  rclone copy reports "gdrive:Premier League – Rapports" --include "*.pdf" --checksum
  echo "[sync] $(date -u +%FT%TZ) ok"
}
main "$@"
exit
