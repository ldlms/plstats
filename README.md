# plstats

Collecte automatique des matchs de Premier League (FotMob) sur un VPS,
puis analyse et rapports générés par Claude à partir de `data/`.

## Organisation

- `collect.py` : récupère les matchs terminés pas encore collectés
  → `data/matches/<saison>/<date>_<dom>-<ext>_<id>.json` (+ heatmap si dispo)
  → `data/latest.json` : matchs ajoutés au dernier passage
- `run.sh` : collecte puis commit/push des nouvelles données (lancé par cron)

## Installation sur le VPS

```bash
sudo apt install -y python3.13-venv git
git clone github-plstats:ldlms/plstats.git ~/plstats
cd ~/plstats
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
git config user.name "plstats-vps" && git config user.email "plstats@vps"
./run.sh --days 10
```

Cron (tous les jours à 6h, heure du serveur) :

```
0 6 * * * /home/ubuntu/plstats/run.sh >> /home/ubuntu/plstats/cron.log 2>&1
```
