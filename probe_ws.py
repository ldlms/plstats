#!/usr/bin/env python3
"""Test d'accès à WhoScored (données d'événements Opta) depuis cette machine."""
import re

from curl_cffi import requests

s = requests.Session(impersonate="chrome")
H = {"Accept-Language": "en-GB,en;q=0.9"}


def show(label, r):
    t = r.text.lower()
    guard = "incapsula" if "incapsula" in t else "cloudflare" if "cloudflare" in t or "cf-chl" in t else "-"
    print(f"{label:28} HTTP {r.status_code}  {len(r.text):>8} car.  protection: {guard}")


try:
    r = s.get("https://www.whoscored.com/", headers=H, timeout=25)
    show("Accueil", r)
    r = s.get("https://www.whoscored.com/regions/252/tournaments/2/england-premier-league",
              headers=H, timeout=25)
    show("Page Premier League", r)
    ids = re.findall(r"/[Mm]atches/(\d+)/", r.text)
    print("Matchs trouvés sur la page :", len(set(ids)))
    if ids:
        mid = ids[0]
        r = s.get(f"https://www.whoscored.com/matches/{mid}/live", headers=H, timeout=25)
        show(f"Match {mid}", r)
        print("Données d'événements présentes :", "matchCentreData" in r.text)
except Exception as e:
    print("Erreur :", repr(e))
