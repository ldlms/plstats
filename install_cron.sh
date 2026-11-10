#!/usr/bin/env bash
# Installe (ou réinstalle) les deux tâches cron du projet sans toucher
# aux autres lignes de la crontab :
#   - collecte chaque nuit à 6 h (heure du serveur) ;
#   - copie des PDF vers Google Drive toutes les heures, à la 20e minute.
# Sans risque à relancer : les anciennes lignes du projet sont remplacées.
set -euo pipefail
DIR="$(dirname "$(readlink -f "$0")")"
LOG="$DIR/cron.log"
chmod +x "$DIR/run.sh" "$DIR/sync_drive.sh"
{
  crontab -l 2>/dev/null | grep -v -F "$DIR/run.sh" | grep -v -F "$DIR/sync_drive.sh" || true
  echo "0 6 * * * $DIR/run.sh >> $LOG 2>&1"
  echo "20 * * * * $DIR/sync_drive.sh >> $LOG 2>&1"
} | crontab -
echo "Tâches cron du projet :"
crontab -l | grep -F "$DIR"
