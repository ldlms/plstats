#!/usr/bin/env python3
"""Collecte des données d'événements WhoScored (Opta) pour les matchs FotMob déjà collectés.

Pour chaque match FotMob terminé sans fichier WhoScored, retrouve le match sur la page
Premier League de WhoScored (le lien contient « domicile-extérieur », unique dans une saison),
ouvre sa page avec un vrai navigateur (Playwright) et enregistre une version allégée :
  data/whoscored/<saison>/<fotmobId>_ws.json

Usage : python collect_ws.py            # matchs des 10 derniers jours
        python collect_ws.py --days 30
Rythme volontairement lent (quelques secondes entre deux pages).
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


def fotmob_todo(days):
    since = datetime.now(timezone.utc) - timedelta(days=days)
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
        if ko < since or datetime.now(timezone.utc) - ko < timedelta(hours=3):
            continue
        out = DATA / "whoscored" / f.parent.name / f"{g['matchId']}_ws.json"
        if out.exists():
            continue
        todo.append({"fotmob_id": str(g["matchId"]), "home": g["homeTeam"]["name"],
                     "away": g["awayTeam"]["name"], "kickoff": ko, "out": out})
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--max", type=int, default=12, help="nombre max de pages de match par passage")
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
        for ws_id, kind, rest in re.findall(r'/[Mm]atches/(\d+)/([A-Za-z]+)/england-premier-league-\d{4}-\d{4}-([a-z0-9-]+)',
                                            page.content()):
            links.setdefault(rest, ws_id)
        log(f"{len(links)} match(s) listés sur WhoScored")

        done = 0
        for m in todo:
            if done >= args.max:
                break
            wanted = {f"{h}-{a}" for h in candidates(m["home"]) for a in candidates(m["away"])}
            ws_id = next((links[k] for k in wanted if k in links), None)
            if not ws_id:
                log(f"Introuvable sur WhoScored : {m['home']} - {m['away']}")
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
