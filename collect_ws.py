#!/usr/bin/env python3
"""Collecte des données d'événements WhoScored (Opta) pour les matchs FotMob déjà collectés.

Pour chaque match FotMob terminé sans fichier WhoScored, retrouve le match sur la page
Premier League de WhoScored (le lien contient « domicile-extérieur », unique dans une saison),
ouvre sa page avec un vrai navigateur (Playwright) et enregistre une version allégée :
  data/whoscored/<saison>/<fotmobId>_ws.json

Usage : python collect_ws.py            # tous les matchs de la saison sans données (30 max par passage)
        python collect_ws.py --days 10 --max 12
Les matchs anciens qui ne sont plus listés sur la page Premier League sont cherchés sur
les pages calendrier des équipes. Un match introuvable 3 fois de suite est abandonné
(data/whoscored/<saison>/_missing.json). Rythme volontairement lent.
"""
import argparse
import json
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PL_URL = "https://www.whoscored.com/regions/252/tournaments/2/england-premier-league"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# Noms courts utilisés par WhoScored dans ses liens
WS_ALIASES = {
    "manchester united": ["man-utd"], "manchester city": ["man-city"],
    "wolverhampton wanderers": ["wolves", "wolverhampton"], "brighton & hove albion": ["brighton"],
    "tottenham hotspur": ["tottenham", "spurs"], "afc bournemouth": ["bournemouth"],
    "nottingham forest": ["nottingham-forest", "nottm-forest"], "west bromwich albion": ["west-brom"],
    "sheffield united": ["sheff-utd", "sheffield-united"], "queens park rangers": ["qpr"],
}
SUFFIXES = ("united", "city", "town", "hotspur", "albion", "afc", "wanderers", "fc")


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), "[ws]", *a, flush=True)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower().replace("&", " ")).strip("-")


def candidates(name):
    n = name.lower()
    out = {slug(name)}
    out.update(WS_ALIASES.get(n, []))
    words = [w for w in slug(name).split("-") if w not in SUFFIXES]
    if words:
        out.add("-".join(words))
    return out


def missing_path(season):
    return DATA / "whoscored" / season / "_missing.json"


def load_missing(season):
    p = missing_path(season)
    return json.loads(p.read_text()) if p.exists() else {}


def fotmob_todo(days):
    since = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    todo = []
    for f in sorted(DATA.glob("matches/*/*.json")):
        if f.name.endswith("_heatmap.json"):
            continue
        d = json.loads(f.read_text())
        g = d["general"]
        st = d["header"]["status"]
        if not st.get("finished"):
            continue
        ko = datetime.fromisoformat(st["utcTime"].replace("Z", "+00:00"))
        if (since and ko < since) or datetime.now(timezone.utc) - ko < timedelta(hours=3):
            continue
        out = DATA / "whoscored" / f.parent.name / f"{g['matchId']}_ws.json"
        if out.exists() or load_missing(f.parent.name).get(str(g["matchId"]), 0) >= 3:
            continue
        todo.append({"fotmob_id": str(g["matchId"]), "home": g["homeTeam"]["name"],
                     "away": g["awayTeam"]["name"], "kickoff": ko, "out": out, "season": f.parent.name})
    return todo


def wait_challenge(page, max_s=30):
    for _ in range(max_s // 2):
        t = page.title().lower()
        if "just a moment" not in t and "attention required" not in t:
            return True
        page.wait_for_timeout(2000)
    return False


def slim(mcd, ws_id):
    def team(t):
        return {
            "teamId": t.get("teamId"), "name": t.get("name"),
            "players": [{k: p.get(k) for k in ("playerId", "name", "shirtNo", "position", "isFirstEleven",
                                               "subbedInExpandedMinute", "subbedOutExpandedMinute")}
                        for p in t.get("players", [])],
            "formations": [{k: fm.get(k) for k in ("formationName", "startMinuteExpanded", "endMinuteExpanded",
                                                   "playerIds", "jerseyNumbers", "formationPositions")}
                           for fm in t.get("formations", [])],
        }

    events = []
    for e in mcd.get("events", []):
        events.append({
            "id": e.get("id"), "min": e.get("minute"), "sec": e.get("second"),
            "period": (e.get("period") or {}).get("displayName"),
            "teamId": e.get("teamId"), "playerId": e.get("playerId"),
            "type": (e.get("type") or {}).get("displayName"),
            "outcome": (e.get("outcomeType") or {}).get("displayName"),
            "x": e.get("x"), "y": e.get("y"), "endX": e.get("endX"), "endY": e.get("endY"),
            "isTouch": e.get("isTouch"), "isShot": e.get("isShot"), "isGoal": e.get("isGoal"),
            "q": [((q.get("type") or {}).get("displayName")) for q in e.get("qualifiers", [])],
        })
    return {"source": "whoscored", "ws_id": ws_id, "startDate": mcd.get("startDate"),
            "score": mcd.get("score"), "home": team(mcd.get("home", {})), "away": team(mcd.get("away", {})),
            "events": events}


def extract(page):
    try:
        mcd = page.evaluate("() => (window.require && require.config && require.config.params"
                            " && require.config.params.args) ? require.config.params.args.matchCentreData : null")
        if mcd:
            return mcd
    except Exception:
        pass
    html = page.content()
    i = html.find("matchCentreData:")
    if i < 0:
        return None
    j = html.find("{", i)
    try:
        obj, _ = json.JSONDecoder().raw_decode(html[j:])
        return obj
    except ValueError:
        return None


MATCH_LINK = re.compile(r'/[Mm]atches/(\d+)/([A-Za-z]+)/england-premier-league-\d{4}-\d{4}-([a-z0-9-]+)')
TEAM_LINK = re.compile(r'/[Tt]eams/(\d+)/[Ss]how/([A-Za-z0-9-]+)')


def collect_links(html, links):
    for ws_id, _kind, rest in MATCH_LINK.findall(html):
        links.setdefault(rest.lower(), ws_id)


def find(m, links):
    wanted = {f"{h}-{a}" for h in candidates(m["home"]) for a in candidates(m["away"])}
    return next((links[k] for k in wanted if k in links), None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0, help="0 = toute la saison")
    ap.add_argument("--max", type=int, default=30, help="nombre max de pages de match par passage")
    args = ap.parse_args()

    todo = fotmob_todo(args.days)
    log(f"{len(todo)} match(s) sans données WhoScored")
    if not todo:
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=UA, locale="en-GB", viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        page.goto(PL_URL, wait_until="domcontentloaded", timeout=60000)
        wait_challenge(page)
        page.wait_for_timeout(3000)
        links = {}
        html = page.content()
        collect_links(html, links)
        log(f"{len(links)} match(s) listés sur la page Premier League")

        # Matchs anciens : pages calendrier des équipes concernées
        teams = {}
        for tid, tslug in TEAM_LINK.findall(html):
            teams.setdefault(tid, tslug)
        unmatched = [m for m in todo[:args.max] if not find(m, links)]
        if unmatched and teams:
            log(f"{len(unmatched)} match(s) non listés : recherche sur {len(teams)} pages d'équipe")
            for tid, tslug in teams.items():
                if all(find(m, links) for m in unmatched):
                    break
                try:
                    page.goto(f"https://www.whoscored.com/teams/{tid}/fixtures/{tslug}",
                              wait_until="domcontentloaded", timeout=60000)
                    if wait_challenge(page):
                        page.wait_for_timeout(2500)
                        collect_links(page.content(), links)
                except Exception as e:
                    log(f"Page équipe {tid} : {e!r}"[:160])
                time.sleep(random.uniform(3, 6))
            log(f"{len(links)} match(s) connus après les pages d'équipe")

        done = 0
        for m in todo:
            if done >= args.max:
                break
            ws_id = find(m, links)
            if not ws_id:
                log(f"Introuvable sur WhoScored : {m['home']} - {m['away']}")
                miss = load_missing(m["season"])
                miss[m["fotmob_id"]] = miss.get(m["fotmob_id"], 0) + 1
                missing_path(m["season"]).parent.mkdir(parents=True, exist_ok=True)
                missing_path(m["season"]).write_text(json.dumps(miss, indent=1))
                continue
            url = f"https://www.whoscored.com/matches/{ws_id}/live"
            mcd = None
            for attempt in range(2):
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                if wait_challenge(page):
                    page.wait_for_timeout(2500)
                    mcd = extract(page)
                if mcd:
                    break
                time.sleep(8)
            done += 1
            if not mcd or not mcd.get("events"):
                log(f"Échec {m['home']} - {m['away']} (ws {ws_id}), on réessaiera")
                continue
            data = slim(mcd, ws_id)
            data["fotmob_id"] = m["fotmob_id"]
            m["out"].parent.mkdir(parents=True, exist_ok=True)
            m["out"].write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
            log(f"OK {m['home']} - {m['away']} : {len(data['events'])} événements")
            time.sleep(random.uniform(6, 12))
        browser.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # ne jamais bloquer la collecte FotMob
        log("Erreur :", repr(e))
        sys.exit(0)
