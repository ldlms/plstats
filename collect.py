#!/usr/bin/env python3
"""Collecte des matchs de Premier League depuis FotMob.

Pour chaque match terminé pas encore collecté :
  - data/matches/<saison>/<date>_<dom>-<ext>_<id>.json  (matchDetails allégé)
  - data/matches/<saison>/<date>_<dom>-<ext>_<id>_heatmap.<ext>  (si dispo)
Puis data/latest.json liste les matchs ajoutés lors de ce passage,
pour que l'analyse sache quoi traiter.

Usage :
  python collect.py            # matchs terminés des 10 derniers jours
  python collect.py --days 3
  python collect.py --all      # toute la saison (backfill)
"""
import argparse
import json
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from curl_cffi import requests

LEAGUE_ID = 47  # Premier League
BASE = "https://www.fotmob.com/api/data"
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

# Blocs volumineux ou inutiles pour l'analyse
DROP_CONTENT = {"liveticker", "superlive", "buzz", "highlightStories", "table", "h2h"}

session = requests.Session(impersonate="chrome")


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def get_json(url, tries=3):
    for i in range(tries):
        try:
            r = session.get(url, timeout=25)
            if r.status_code == 200:
                return r.json()
            log(f"HTTP {r.status_code} sur {url}")
        except Exception as e:  # réseau, JSON invalide…
            log(f"Erreur {e!r} sur {url}")
        time.sleep(5 * (i + 1))
    return None


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def parse_utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def season_label(dt):
    y = dt.year if dt.month >= 7 else dt.year - 1
    return f"{y}-{str(y + 1)[2:]}"


def already_collected(match_id):
    return any(DATA.glob(f"matches/*/*_{match_id}.json"))


def heatmap_candidates(url):
    """heatmapUrl est relatif (/api/data/heatmap/...?heatmapUrl=<url directe>)."""
    out = []
    if url.startswith("/"):
        out.append("https://www.fotmob.com" + url)
    elif url.startswith("http"):
        out.append(url)
    inner = parse_qs(urlparse(url).query).get("heatmapUrl")
    if inner:
        out.append(inner[0])
    return out


def download_heatmap(url, dest_stem):
    for u in heatmap_candidates(url):
        try:
            r = session.get(u, timeout=25)
            if r.status_code != 200:
                log(f"Heatmap HTTP {r.status_code} sur {u}")
                continue
            ctype = r.headers.get("content-type", "")
            ext = ("json" if "json" in ctype else "png" if "png" in ctype
                   else "jpg" if "jpeg" in ctype else "svg" if "svg" in ctype else "bin")
            path = dest_stem.with_name(dest_stem.name + f"_heatmap.{ext}")
            path.write_bytes(r.content)
            return path
        except Exception as e:
            log(f"Heatmap non récupérée ({u}) : {e!r}")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    league = get_json(f"{BASE}/leagues?id={LEAGUE_ID}")
    if not league:
        log("Impossible de récupérer le calendrier FotMob")
        sys.exit(1)
    matches = (league.get("fixtures") or league.get("matches") or {}).get("allMatches", [])
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=args.days)

    todo = []
    for m in matches:
        st = m.get("status", {})
        if not st.get("finished") or st.get("cancelled"):
            continue
        kickoff = parse_utc(st["utcTime"])
        if not args.all and kickoff < since:
            continue
        if already_collected(m["id"]):
            continue
        todo.append((kickoff, m))
    todo.sort(key=lambda x: x[0])
    log(f"{len(todo)} match(s) à collecter")

    added = []
    for kickoff, m in todo:
        mid = m["id"]
        details = get_json(f"{BASE}/matchDetails?matchId={mid}")
        if not details:
            log(f"Échec matchDetails {mid}, on réessaiera au prochain passage")
            continue

        content = details.get("content", {}) or {}
        heatmap_url = content.get("heatmapUrl")
        slim = {
            "source": "fotmob",
            "collected_at": now.isoformat(),
            "general": details.get("general"),
            "header": details.get("header"),
            "content": {k: v for k, v in content.items() if k not in DROP_CONTENT},
        }

        home, away = m["home"]["name"], m["away"]["name"]
        season_dir = DATA / "matches" / season_label(kickoff)
        season_dir.mkdir(parents=True, exist_ok=True)
        stem = season_dir / f"{kickoff:%Y-%m-%d}_{slug(home)}-{slug(away)}_{mid}"
        stem.with_suffix(".json").write_text(json.dumps(slim, ensure_ascii=False))

        heatmap_path = None
        if isinstance(heatmap_url, str) and heatmap_url:
            heatmap_path = download_heatmap(heatmap_url, stem)

        added.append({
            "id": mid,
            "round": m.get("round"),
            "kickoff_utc": m["status"].get("utcTime"),
            "home": home,
            "away": away,
            "score": m["status"].get("scoreStr"),
            "file": str(stem.with_suffix(".json").relative_to(ROOT)),
            "heatmap": str(heatmap_path.relative_to(ROOT)) if heatmap_path else None,
        })
        log(f"OK {home} {m['status'].get('scoreStr')} {away}")
        time.sleep(random.uniform(2, 4))

    if added:
        DATA.mkdir(exist_ok=True)
        (DATA / "latest.json").write_text(json.dumps(
            {"run_at": now.isoformat(), "matches": added}, ensure_ascii=False, indent=2))
    log(f"Terminé : {len(added)} match(s) ajouté(s)")


if __name__ == "__main__":
    main()
