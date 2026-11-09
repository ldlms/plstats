#!/usr/bin/env python3
"""Diagnostic de la heatmap FotMob (à lancer sur le VPS)."""
import json
from urllib.parse import parse_qs, urlparse

from curl_cffi import requests

s = requests.Session(impersonate="chrome")


def shape(o, depth=0, max_depth=4):
    """Résumé de la structure d'un JSON (clés, types, tailles)."""
    pad = "  " * depth
    if depth > max_depth:
        return pad + "…"
    if isinstance(o, dict):
        lines = [f"{pad}dict({len(o)})"]
        for i, (k, v) in enumerate(o.items()):
            if i >= 8:
                lines.append(f"{pad}  … +{len(o) - 8} clés")
                break
            lines.append(f"{pad}  [{k!r}]")
            lines.append(shape(v, depth + 2, max_depth))
        return "\n".join(lines)
    if isinstance(o, list):
        head = f"{pad}list({len(o)})"
        return head + ("\n" + shape(o[0], depth + 1, max_depth) if o else "")
    return f"{pad}{type(o).__name__}: {repr(o)[:80]}"


lg = s.get("https://www.fotmob.com/api/data/leagues?id=47", timeout=20).json()
ms = (lg.get("fixtures") or lg.get("matches") or {}).get("allMatches", [])
m = [x for x in ms if x.get("status", {}).get("finished")][-1]
d = s.get(f"https://www.fotmob.com/api/data/matchDetails?matchId={m['id']}", timeout=20).json()
hu = d["content"]["heatmapUrl"]
print("Match:", m["home"]["name"], "-", m["away"]["name"])

urls = ["https://www.fotmob.com" + hu]
inner = parse_qs(urlparse(hu).query).get("heatmapUrl")
if inner:
    urls.append(inner[0])

for u in urls:
    r = s.get(u, timeout=20)
    print("\n==>", u[:90])
    print("HTTP", r.status_code, "|", r.headers.get("content-type"), "|", len(r.content), "octets")
    if r.ok and "json" in (r.headers.get("content-type") or ""):
        data = r.json()
        print(shape(data))
        with open("heatmap_sample.json", "w") as f:
            json.dump(data, f)
        print("(copie complète dans heatmap_sample.json)")
        break
    elif r.ok:
        print("Début du contenu:", r.content[:120])
