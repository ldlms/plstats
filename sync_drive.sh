#!/usr/bin/env bash
# Envoie les rapports PDF du dépôt vers Google Drive, dans le dossier
# « Premier League – Rapports » (remote rclone "gdrive", accès limité aux
# fichiers créés par rclone : scope drive.file).
set -euo pipefail
cd "$(dirname "$0")"
git pull -q --rebase
rclone copy reports "gdrive:Premier League – Rapports" --include "*.pdf" --ignore-existing
