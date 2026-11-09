#!/usr/bin/env bash
# Envoie les rapports PDF du dépôt vers Google Drive (remote rclone "gdrive",
# dont la racine est le dossier « Premier League – Rapports »).
set -euo pipefail
cd "$(dirname "$0")"
git pull -q --rebase
rclone copy reports gdrive: --include "*.pdf" --ignore-existing
