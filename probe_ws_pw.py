#!/usr/bin/env python3
"""Test WhoScored avec un vrai navigateur (Playwright/Chromium sans interface).

Ouvre la page Premier League, puis jusqu'à 3 pages de match, en laissant le
temps au défi Cloudflare de se résoudre. Dit si les données d'événements
(matchCentreData) sont lisibles.
"""
import json
import re

from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    ctx = browser.new_context(user_agent=UA, locale="en-GB", viewport={"width": 1366, "height": 900})
    page = ctx.new_page()

    page.goto("https://www.whoscored.com/regions/252/tournaments/2/england-premier-league",
              wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    print("Page PL :", page.title())
    html = page.content()
    ids = list(dict.fromkeys(re.findall(r"/[Mm]atches/(\d+)/", html)))
    print("Matchs trouvés :", len(ids))

    for mid in ids[:3]:
        page.goto(f"https://www.whoscored.com/matches/{mid}/live", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(10000)  # défi Cloudflare
        title = page.title()
        html = page.content()
        blocked = "just a moment" in title.lower() or "attention required" in title.lower()
        print(f"\nMatch {mid} : {title[:80]!r}  bloqué={blocked}")
        m = re.search(r"matchCentreData:\s*(\{.+?\})\s*,\s*\n", html, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
                ev = data.get("events", [])
                types = {}
                for e in ev:
                    t = (e.get("type") or {}).get("displayName")
                    types[t] = types.get(t, 0) + 1
                top = sorted(types.items(), key=lambda kv: -kv[1])[:6]
                print(f"  OK : {len(ev)} événements avec position x/y. Types : {top}")
                break
            except Exception as ex:
                print("  matchCentreData trouvé mais illisible :", repr(ex)[:120])
        else:
            print("  Pas de données d'événements sur cette page (match pas encore joué ?)")
    browser.close()
