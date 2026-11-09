#!/usr/bin/env python3
"""Diagnostic des sources de heatmaps / positions (à lancer sur le VPS)."""
from curl_cffi import requests

s = requests.Session(impersonate="chrome")
H = {"Referer": "https://www.sofascore.com/", "Origin": "https://www.sofascore.com"}

# 1) FotMob : que contient heatmapUrl, et les joueurs ont-ils des heatmaps ?
try:
    lg = s.get("https://www.fotmob.com/api/data/leagues?id=47", timeout=20).json()
    ms = (lg.get("fixtures") or lg.get("matches") or {}).get("allMatches", [])
    m = [x for x in ms if x.get("status", {}).get("finished")][-1]
    d = s.get(f"https://www.fotmob.com/api/data/matchDetails?matchId={m['id']}", timeout=20).json()
    c = d.get("content", {})
    print("FotMob match:", m["home"]["name"], "-", m["away"]["name"])
    print("FotMob heatmapUrl:", repr(c.get("heatmapUrl"))[:300])
    ps = c.get("playerStats") or {}
    if isinstance(ps, dict) and ps:
        p = next(iter(ps.values()))
        print("FotMob clés joueur:", list(p.keys()))
        hm = {k: v for k, v in p.items() if "heat" in k.lower() or "position" in k.lower()}
        print("FotMob champs heat/position joueur:", repr(hm)[:300])
    lu = c.get("lineup") or {}
    print("FotMob clés lineup:", list(lu.keys()) if isinstance(lu, dict) else type(lu))
except Exception as e:
    print("FotMob erreur:", repr(e))

# 2) SofaScore : ancien domaine api. et domaine www. avec en-têtes du site
for base in ("https://www.sofascore.com/api/v1", "https://api.sofascore.com/api/v1"):
    try:
        r = s.get(f"{base}/unique-tournament/17/seasons", headers=H, timeout=20)
        print(base, "->", r.status_code)
        if not r.ok:
            continue
        sid = r.json()["seasons"][0]["id"]
        ev = s.get(f"{base}/unique-tournament/17/season/{sid}/events/last/0",
                   headers=H, timeout=20).json()["events"]
        e = [x for x in ev if x["status"]["type"] == "finished"][-1]
        print("  match:", e["homeTeam"]["name"], "-", e["awayTeam"]["name"], e["id"])
        for ep in ("average-positions", f"heatmap/{e['homeTeam']['id']}", "shotmap"):
            print(f"  {ep}:", s.get(f"{base}/event/{e['id']}/{ep}", headers=H, timeout=20).status_code)
        break
    except Exception as ex:
        print(base, "erreur:", repr(ex))
