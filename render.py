#!/usr/bin/env python3
"""Assemble la page HTML d'une journée à partir de out/J<n>/summary.json,
des graphes .webp et de out/J<n>/analysis.json (texte rédigé par Claude).

Usage : python render.py --round 10   ->  out/J10/index.html (autonome, images intégrées)

analysis.json :
{
  "intro": ["paragraphe", ...],
  "matches": {
    "<matchId>": {"headline": "...", "paragraphs": ["...", "..."], "keys": ["...", "..."]}
  }
}
"""
import argparse

import manifest
import shutil
import subprocess
import base64
import html
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
PARIS = ZoneInfo("Europe/Paris")
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]

CSS = """
:root {
  /* Thème unique sombre : un soir de match. Bleu = domicile, orange = extérieur. */
  --bg: #0f1311;
  --surface: #141917;
  --card: #171e1a;
  --line: #29332d;
  --text: #e8ece9;
  --muted: #9aa59f;
  --home: #3987e5;
  --away: #d95926;
  --font-display: "Barlow Condensed", "Arial Narrow", sans-serif;
  --font-body: "Source Sans 3", "Segoe UI", system-ui, Inter, sans-serif;
  /* Mise en page : une colonne de lecture (~720px), cartes de match empilées. */
  color-scheme: dark;
}
* { box-sizing: border-box; }
html { background: var(--bg); }
body { margin: 0; background: var(--bg); color: var(--text); font-family: var(--font-body);
       font-size: 17px; line-height: 1.55; -webkit-text-size-adjust: 100%; }
.wrap { max-width: 760px; margin: 0 auto; padding: 28px 16px 64px; display: grid; gap: 28px; }
h1, h2, h3 { font-family: var(--font-display); font-weight: 700; line-height: 1.1; margin: 0;
             text-wrap: balance; letter-spacing: 0.01em; }
h1 { font-size: clamp(40px, 9vw, 60px); text-transform: uppercase; }
h2 { font-size: 26px; text-transform: uppercase; }
h3 { font-size: 22px; }
p { margin: 0; max-width: 66ch; }
a { color: inherit; }
.eyebrow { font-family: var(--font-display); text-transform: uppercase; letter-spacing: 0.12em;
           color: var(--muted); font-size: 15px; }
.lede { display: grid; gap: 12px; }
.muted { color: var(--muted); }
.num { font-variant-numeric: tabular-nums; }

/* Tableau des résultats */
.results { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
.results td { padding: 10px 6px; border-top: 1px solid var(--line); vertical-align: middle; }
.results tr:first-child td { border-top: 0; }
.results .t-home { text-align: right; width: 34%; }
.results .t-away { text-align: left; width: 34%; }
.results .t-score { text-align: center; font-family: var(--font-display); font-size: 22px;
                    font-weight: 700; white-space: nowrap; }
.results .t-score a { text-decoration: none; }
.results .t-xg { font-size: 13px; color: var(--muted); display: block; font-family: var(--font-body);
                 font-weight: 400; }
.chip { display: inline-block; font-size: 12px; line-height: 1; padding: 5px 8px; border-radius: 99px;
        border: 1px solid var(--line); color: var(--muted); white-space: nowrap; margin-top: 4px; }
.chip.upset { border-color: var(--text); color: var(--text); }
.win { font-weight: 700; }

.howto { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 16px;
         display: grid; gap: 8px; font-size: 15px; }
.howto dl { margin: 0; display: grid; gap: 6px; }
.howto dt { font-weight: 700; display: inline; }
.howto dd { display: inline; margin: 0; color: var(--muted); }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; vertical-align: 1px; }
.dot.home { background: var(--home); }
.dot.away { background: var(--away); }

/* Carte de match */
.match { background: var(--card); border: 1px solid var(--line); border-radius: 14px;
         padding: 20px 16px; display: grid; gap: 18px; scroll-margin-top: 12px; }
.board { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 10px; }
.board .team { font-family: var(--font-display); font-size: 21px; font-weight: 700; line-height: 1.1; }
.board .team.home { text-align: right; color: var(--home); }
.board .team.away { color: var(--away); }
.board .score { font-family: var(--font-display); font-size: 44px; font-weight: 700;
                font-variant-numeric: tabular-nums; letter-spacing: 0.04em; }
.meta { text-align: center; font-size: 14px; color: var(--muted); }
.scorers { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; font-size: 14px; }
.scorers ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; }
.scorers .home { text-align: right; }
.red { color: var(--text); font-size: 14px; text-align: center; }
.red::before { content: ""; display: inline-block; width: 9px; height: 12px; background: #d03b3b;
               border-radius: 2px; margin-right: 6px; vertical-align: -1px; }
.story { display: grid; gap: 10px; }
.keys { margin: 0; padding-left: 20px; display: grid; gap: 4px; }

/* Barres miroir */
.bars { display: grid; gap: 10px; }
.bar-row { display: grid; grid-template-columns: 3.2em 1fr 3.2em; gap: 8px; align-items: center;
           font-variant-numeric: tabular-nums; font-size: 15px; }
.bar-row .v-home { text-align: right; }
.bar-label { grid-column: 1 / -1; text-align: center; font-size: 13px; color: var(--muted);
             margin-bottom: -6px; }
.bar { display: flex; height: 8px; gap: 2px; }
.bar span { display: block; height: 100%; }
.bar .b-home { background: var(--home); border-radius: 4px 0 0 4px; }
.bar .b-away { background: var(--away); border-radius: 0 4px 4px 0; }

.figs { display: grid; gap: 22px; }
figure { margin: 0; display: grid; gap: 6px; align-content: start; }
figure img { width: 100%; height: auto; display: block; border-radius: 8px; }
figcaption { font-size: 14px; color: var(--muted); }
.legend { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; font-size: 13px; color: var(--muted); }
.legend.one { grid-template-columns: 1fr; }
.legend ol.cols { display: block; columns: 2; column-gap: 16px; }
.legend ol.cols li { break-inside: avoid; }
.legend ol { list-style: none; margin: 0; padding: 0; display: grid; gap: 1px; }
.legend b { color: var(--text); font-variant-numeric: tabular-nums; display: inline-block; min-width: 1.8em; }
.squad { border-top: 1px solid var(--line); padding-top: 12px; }
.squad summary { cursor: pointer; font-weight: 700; padding: 4px 0; }
.squad summary .muted { font-weight: 400; }
.plist { list-style: none; margin: 10px 0 0; padding: 0; display: grid; gap: 10px; }
.plist li { display: grid; gap: 2px; font-size: 15px; }
.plist .pname { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
.plist .pnum { font-variant-numeric: tabular-nums; color: var(--muted); min-width: 1.8em; }
.plist .prate { font-variant-numeric: tabular-nums; font-weight: 700; }
.plist .pline { color: var(--muted); font-size: 14px; padding-left: 2.3em; }
.tag { display: inline-block; font-size: 12.5px; padding: 2px 7px; border-radius: 99px; margin: 2px 4px 0 0;
       border: 1px solid var(--line); color: var(--text); }
.tag b { font-variant-numeric: tabular-nums; }
.top { font-size: 14px; color: var(--muted); text-align: right; }
footer { font-size: 13px; color: var(--muted); }
:focus-visible { outline: 2px solid var(--text); outline-offset: 2px; }
.mu-l { font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin-top: 6px; }
.tag.good { border-color: #3c7d55; } .tag.bad { border-color: #8a4040; }
.ph { display: grid; gap: 8px; }
.ph-tabs { display: flex; gap: 6px; flex-wrap: wrap; }
.ph-tabs [role=tab] { font: inherit; font-size: 14px; padding: 6px 12px; border-radius: 99px; cursor: pointer;
                      border: 1px solid var(--line); background: transparent; color: var(--muted); }
.ph-tabs [role=tab][aria-selected=true] { background: var(--text); color: var(--bg); border-color: var(--text); font-weight: 700; }
.ph-panel { display: grid; gap: 6px; }
.ph-panel[hidden] { display: none; }
.ph-m { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 14px; color: var(--muted); }
.ph-m b { color: var(--text); font-variant-numeric: tabular-nums; }
.ph-chg { font-size: 13.5px; }
.sst td:nth-child(n+3), .sst th:nth-child(n+3) { text-align: right; }
.comp { display: grid; gap: 3px; font-size: 14.5px; margin-top: 4px; }
.comp .in { color: var(--text); }
.subs { display: grid; gap: 4px; }
.subs-t { text-align: center; font-size: 13px; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; }
.subs .scorers { font-size: 13.5px; }
.subs .in { color: var(--text); display: block; } .subs .out { color: var(--muted); display: block; }
.subs li + li { margin-top: 4px; }
.subs-l { font-size: 13px; color: var(--muted); margin-top: 6px; }
.subs-l b { color: var(--text); }
.gks { display: grid; gap: 8px; background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
       padding: 12px 14px; }
.gks h4 { margin: 0; font-family: var(--font-display); font-size: 18px; text-transform: uppercase; }
.gks ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; font-size: 15px; }
.gk-stats { color: var(--muted); font-size: 14px; padding-left: 16px; }
.gk-stats b { color: var(--text); font-variant-numeric: tabular-nums; }
.gks p { font-size: 13px; }
.habits { display: grid; gap: 12px; background: var(--surface); border: 1px solid var(--line);
          border-radius: 10px; padding: 12px 14px; }
.habits h4 { margin: 0; font-family: var(--font-display); font-size: 18px; text-transform: uppercase; }
.hab-t { font-weight: 700; font-size: 15px; }
.hab { list-style: none; margin: 4px 0 0; padding: 0; display: grid; gap: 3px; font-size: 15px; }
.hab .arr { display: inline-block; width: 1.1em; color: var(--muted); font-size: 12px; }
.habits p { font-size: 14px; margin-top: 4px; }
details.more { border-top: 1px solid var(--line); padding-top: 12px; }
details.more > summary { cursor: pointer; font-weight: 700; padding: 6px 0; font-size: 16px; }
details.more > .figs { margin-top: 12px; }
.ivz { display: grid; gap: 6px; }
.ivz-t { display: flex; justify-content: space-between; font-family: var(--font-display); font-weight: 700;
         font-size: 17px; gap: 8px; }
.c-home { color: var(--home); } .c-away { color: var(--away); }
.ivz-svg { width: 100%; height: auto; display: block; border-radius: 8px; background: #18201c; }
.ivz-svg .pz { fill: #18201c; }
.ivz-svg .pl { fill: none; stroke: #3d4943; stroke-width: 0.3; }
.ivz-svg .pd { fill: #3d4943; }
.ivz-svg .ht { fill: transparent; stroke: transparent; }
.ivz-svg .hit { cursor: pointer; outline: none; }
.ivz-svg .hit:focus-visible circle:not(.ht) { stroke: var(--text); stroke-width: 0.5; }
.ivz-svg .s-home { fill: none; stroke: var(--home); stroke-width: 0.45; }
.ivz-svg .s-away { fill: none; stroke: var(--away); stroke-width: 0.45; }
.ivz-svg .s-home.goal { fill: var(--home); stroke: #141917; stroke-width: 0.5; }
.ivz-svg .s-away.goal { fill: var(--away); stroke: #141917; stroke-width: 0.5; }
.ivz-svg .lk-home { stroke: #d6e6fb; stroke-linecap: round; }
.ivz-svg .lk-away { stroke: #fbdccb; stroke-linecap: round; }
.ivz-svg .nd-home { fill: var(--home); stroke: #141917; stroke-width: 0.5; }
.ivz-svg .nd-away { fill: var(--away); stroke: #141917; stroke-width: 0.5; }
.ivz-svg .nd-home.sub, .ivz-svg .nd-away.sub { fill: #18201c; stroke-width: 0.6; }
.ivz-svg .nd-home.sub { stroke: var(--home); } .ivz-svg .nd-away.sub { stroke: var(--away); }
.ivz-svg .nt.sub.t-home { fill: var(--home); } .ivz-svg .nt.sub.t-away { fill: var(--away); }
.ivz-svg .dp-home { fill: var(--home); opacity: 0.4; }
.ivz-svg .dp-away { fill: var(--away); opacity: 0.4; }
.ivz-svg .nt { fill: #fff; font-size: 2.7px; font-weight: 700; text-anchor: middle; dominant-baseline: central;
               font-family: var(--font-body); pointer-events: none; }
.ivz-svg .avg { stroke: var(--text); stroke-width: 0.25; stroke-dasharray: 1 1; opacity: 0.6; }
.tip { position: absolute; z-index: 10; max-width: min(320px, calc(100vw - 16px)); background: var(--text); color: var(--bg);
       font-size: 14px; line-height: 1.35; padding: 7px 10px; border-radius: 8px; pointer-events: none;
       box-shadow: 0 4px 14px rgba(0,0,0,.4); }
.print-only { display: none; }
.tscroll { overflow-x: auto; }
.xgt { width: 100%; border-collapse: collapse; font-size: 15px; }
.xgt th { text-align: left; font-weight: 600; color: var(--muted); font-size: 13px; padding: 6px 6px;
          border-bottom: 1px solid var(--line); white-space: nowrap; }
.xgt td { padding: 6px 6px; border-bottom: 1px solid var(--line); white-space: nowrap; }
.xgt td.num, .xgt th:nth-child(n+3) { text-align: right; font-variant-numeric: tabular-nums; }
.xgt th:first-child, .xgt td:first-child { text-align: right; width: 2em; }
@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto; } }
@media print {
  .ivz, .tip, .ph { display: none !important; }
  .print-only { display: block; width: 100%; height: auto; border-radius: 8px; }
  html, body { -webkit-print-color-adjust: exact; print-color-adjust: exact; background: var(--bg); }
  .wrap { max-width: none; padding: 0 10px; }
  .figs { grid-template-columns: 1fr 1fr; gap: 14px; }
  .figs .wide { grid-column: 1 / -1; width: 70%; justify-self: center; }
  figcaption, .legend { font-size: 11px; }
  figure, .board, .bars, .story, .plist li { break-inside: avoid; }
  .match { break-before: page; }
  .top { display: none; }
}
@page { size: A4; margin: 10mm 8mm; background: #0f1311; }
@media (max-width: 420px) {
  body { font-size: 16px; }
  .board .team { font-size: 18px; }
  .board .score { font-size: 38px; }
}
"""


def esc(s):
    return html.escape(str(s)) if s is not None else ""


def fmt_num(v, d=0):
    if v is None:
        return "–"
    return f"{v:.{d}f}".replace(".", ",")


def paris(dt_utc):
    return datetime.fromisoformat(dt_utc.replace("Z", "+00:00")).astimezone(PARIS)


def date_fr(dt):
    return f"{JOURS[dt.weekday()]} {dt.day} {MOIS[dt.month - 1]}"


def verdict(m):
    xg = m["stats"].get("xg") or [0, 0]
    d = (xg[0] or 0) - (xg[1] or 0)
    sh, sa = m["score"]
    res = (sh > sa) - (sh < sa)
    if abs(d) < 0.5:
        return "Serré au xG", False
    fav = 1 if d > 0 else -1
    if res == fav:
        return "Logique", False
    return "Contre le xG", True


def img(path):
    data = base64.b64encode(path.read_bytes()).decode()
    return f"data:image/webp;base64,{data}"


def bar_row(label, h, a, dh=0, da=0, suffix=""):
    if h is None or a is None:
        return ""
    tot = (h + a) or 1
    ph = 100 * h / tot
    return (f'<div class="bar-row"><div class="bar-label">{esc(label)}</div>'
            f'<span class="v-home">{fmt_num(h, dh)}{suffix}</span>'
            f'<div class="bar" role="img" aria-label="{esc(label)} : {fmt_num(h, dh)} contre {fmt_num(a, da)}">'
            f'<span class="b-home" style="width:{ph:.1f}%"></span>'
            f'<span class="b-away" style="width:{100 - ph:.1f}%"></span></div>'
            f'<span class="v-away">{fmt_num(a, da)}{suffix}</span></div>')


def goal_line(g):
    tag = " (pén.)" if g["penalty"] else " (csc)" if g["own_goal"] else ""
    return f"<li><span class=\"num\">{esc(g['minute'])}</span> {esc(g['scorer'])}{tag}</li>"


def squad_block(m, side):
    ps = [p for p in m["players"][side] if p.get("minutes")]
    ps.sort(key=lambda p: (not p["starter"], -(p.get("rating") or 0)))
    items = []
    for p in ps:
        prof = p.get("profile") or {}
        if prof.get("strengths"):
            tags = "".join(f'<span class="tag">{esc(t["label"])} <b>{t["pct"]}</b></span>' for t in prof["strengths"])
        elif prof and not prof.get("qualified"):
            tags = (f'<span class="muted">Trop tôt pour un profil ({prof.get("apps")} match'
                    f'{"s" if (prof.get("apps") or 0) > 1 else ""}, {prof.get("minutes")} min).</span>')
        else:
            tags = '<span class="muted">Pas de point fort qui ressort nettement cette saison.</span>'
        hl = p.get("match_highlights") or []
        rate = f'<span class="prate">{fmt_num(p["rating"], 1)}</span>' if p.get("rating") else ""
        if not p["starter"]:
            sub = f' <span class="muted">(entré {esc(p.get("sub_in") or "")})</span>'
        elif p.get("sub_out"):
            sub = f' <span class="muted">(sorti {esc(p["sub_out"])})</span>'
        else:
            sub = ""
        items.append(
            f'<li><div class="pname"><span class="pnum">{esc(p["number"])}</span><span>{esc(p["name"])}{sub}</span>'
            f'{rate}<span class="muted">{int(p["minutes"])} min</span></div>'
            + (f'<div class="pline">Ce match : {esc(", ".join(hl))}</div>' if hl else "")
            + f'<div class="pline">{tags}</div></li>')
    color = "home" if side == "home" else "away"
    return (f'<details class="squad"><summary><span class="dot {color}"></span> {esc(m[side])} : '
            f'points forts des joueurs <span class="muted">({len(ps)})</span></summary>'
            f'<ul class="plist">{"".join(items)}</ul></details>')


# ------------------------------------------------------------------ SVG interactifs
PW, PH = 105.0, 68.0


def svg_pitch():
    a = (9.15 ** 2 - 5.5 ** 2) ** 0.5
    return (
        '<rect x="0" y="0" width="105" height="68" class="pz"/>'
        '<g class="pl">'
        '<rect x="0" y="0" width="105" height="68"/>'
        '<line x1="52.5" y1="0" x2="52.5" y2="68"/>'
        '<circle cx="52.5" cy="34" r="9.15"/>'
        '<rect x="0" y="13.84" width="16.5" height="40.32"/><rect x="88.5" y="13.84" width="16.5" height="40.32"/>'
        '<rect x="0" y="24.84" width="5.5" height="18.32"/><rect x="99.5" y="24.84" width="5.5" height="18.32"/>'
        f'<path d="M16.5 {34 - a:.2f} A9.15 9.15 0 0 1 16.5 {34 + a:.2f}"/>'
        f'<path d="M88.5 {34 - a:.2f} A9.15 9.15 0 0 0 88.5 {34 + a:.2f}"/>'
        '</g><circle cx="11" cy="34" r="0.35" class="pd"/><circle cx="94" cy="34" r="0.35" class="pd"/>'
        '<circle cx="52.5" cy="34" r="0.35" class="pd"/>'
    )


def svg_wrap(inner, label):
    return (f'<svg class="ivz-svg" viewBox="-1 -1 107 70" role="img" aria-label="{esc(label)}">'
            f'{svg_pitch()}{inner}</svg>')


def tipattr(text):
    return f'data-tip="{esc(text)}" tabindex="0"'


def svg_shots(m):
    out = []
    for sh in sorted(m.get("shots_data", []), key=lambda s: s["kind"] == "but"):
        x, y = sh["x"], sh["y"]                       # y vers le haut, attaque vers la droite
        cx, cy = (x, PH - y) if sh["side"] == "home" else (PW - x, y)
        r = 0.8 + 4.0 * (sh["xg"] ** 0.5)
        team = m["home_short"] if sh["side"] == "home" else m["away_short"]
        sit = {"Penalty": "penalty", "FromCorner": "corner", "SetPiece": "coup de pied arrêté",
               "FreeKick": "coup franc", "FastBreak": "contre-attaque"}.get(sh["situation"], "")
        tip = f"{sh['player']} ({team}) · {sh['minute']} · xG {fmt_num(sh['xg'], 2)} · {sh['kind']}" + (f" · {sit}" if sit else "")
        cls = f"s-{sh['side']}" + (" goal" if sh["kind"] == "but" else "")
        out.append(f'<g class="hit" {tipattr(tip)}><circle cx="{cx:.1f}" cy="{cy:.1f}" r="{max(r, 2.6):.2f}" class="ht"/>'
                   f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.2f}" class="{cls}"/></g>')
    return svg_wrap("".join(out), f"Carte des tirs {m['home']} contre {m['away']}")


def svg_possession(m, side):
    stc = m["structure"][side]
    nodes = {n["name"]: n for n in stc["possession_shape"]}
    links = stc.get("pass_links", [])
    nmax = max([l["n"] for l in links] + [1])
    tmax = max([n["n"] for n in nodes.values()] + [1])
    out = []
    h = stc.get("possession_block_height_m")
    if h:
        out.append(f'<g {tipattr(f"Hauteur moyenne du bloc avec le ballon : {fmt_num(h, 0)} m de son but")}>'
                   f'<line x1="{h:.1f}" y1="0" x2="{h:.1f}" y2="68" class="avg"/>'
                   f'<rect x="{h - 1.2:.1f}" y="0" width="2.4" height="68" class="ht"/></g>')
    for l in sorted(links, key=lambda l: l["n"]):
        a, b = nodes.get(l["a"]), nodes.get(l["b"])
        if not a or not b:
            continue
        w = 0.25 + 1.4 * l["n"] / nmax
        op = 0.25 + 0.6 * l["n"] / nmax
        out.append(f'<g class="hit" {tipattr(f"{a["name"]} ↔ {b["name"]} : {l["n"]} passes")}>'
                   f'<line x1="{a["x"]}" y1="{PH - a["y"]:.1f}" x2="{b["x"]}" y2="{PH - b["y"]:.1f}" class="ht" stroke-width="3"/>'
                   f'<line x1="{a["x"]}" y1="{PH - a["y"]:.1f}" x2="{b["x"]}" y2="{PH - b["y"]:.1f}" class="lk-{side}" '
                   f'stroke-width="{w:.2f}" stroke-opacity="{op:.2f}"/></g>')
    for n in sorted(nodes.values(), key=lambda n: not n.get("sub")):
        r = 2.0 + 1.6 * n["n"] / tmax
        sub = " sub" if n.get("sub") else ""
        lab = " (remplaçant)" if n.get("sub") else ""
        out.append(f'<g class="hit" {tipattr(f"{n["name"]}{lab} · {n["n"]} ballons joués (passes données ou reçues)")}>'
                   f'<circle cx="{n["x"]}" cy="{PH - n["y"]:.1f}" r="{r:.2f}" class="nd-{side}{sub}"/>'
                   f'<text x="{n["x"]}" y="{PH - n["y"]:.1f}" class="nt{sub} t-{side}">{esc(n["number"])}</text></g>')
    return svg_wrap("".join(out), f"{m[side]} avec le ballon")


def svg_defence(m, side):
    stc = m["structure"][side]
    out = []
    for x, y in stc.get("def_points", []):
        out.append(f'<circle cx="{x}" cy="{PH - y:.1f}" r="0.55" class="dp-{side}"/>')
    h = stc.get("defensive_actions_avg_height_m")
    if h:
        out.append(f'<g {tipattr(f"Hauteur moyenne des actions défensives : {fmt_num(h, 0)} m de son but")}>'
                   f'<line x1="{h:.1f}" y1="0" x2="{h:.1f}" y2="68" class="avg"/>'
                   f'<rect x="{h - 1.2:.1f}" y="0" width="2.4" height="68" class="ht"/></g>')
    for n in sorted(stc.get("defensive_shape", []), key=lambda n: not n.get("sub")):
        sub = " sub" if n.get("sub") else ""
        lab = " (remplaçant)" if n.get("sub") else ""
        out.append(f'<g class="hit" {tipattr(f"{n["name"]}{lab} · {n["n"]} actions défensives (position moyenne)")}>'
                   f'<circle cx="{n["x"]}" cy="{PH - n["y"]:.1f}" r="2.4" class="nd-{side}{sub}"/>'
                   f'<text x="{n["x"]}" y="{PH - n["y"]:.1f}" class="nt{sub} t-{side}">{esc(n["number"])}</text></g>')
    return svg_wrap("".join(out), f"{m[side]} sans le ballon")


def svg_net_from(shape, side, label):
    nodes = {n["name"]: n for n in shape["nodes"]}
    links = shape.get("edges", [])
    nmax = max([l["n"] for l in links] + [1])
    tmax = max([n["n"] for n in nodes.values()] + [1])
    out = []
    h = shape["metrics"].get("possession_block_height_m")
    if h:
        out.append(f'<g {tipattr(f"Hauteur moyenne du bloc avec le ballon : {fmt_num(h, 0)} m de son but")}>'
                   f'<line x1="{h:.1f}" y1="0" x2="{h:.1f}" y2="68" class="avg"/>'
                   f'<rect x="{h - 1.2:.1f}" y="0" width="2.4" height="68" class="ht"/></g>')
    for l in sorted(links, key=lambda l: l["n"]):
        a, b = nodes.get(l["a"]), nodes.get(l["b"])
        if not a or not b:
            continue
        w = 0.25 + 1.4 * l["n"] / nmax
        op = 0.25 + 0.6 * l["n"] / nmax
        out.append(f'<g class="hit" {tipattr(f"{a["name"]} ↔ {b["name"]} : {l["n"]} passes")}>'
                   f'<line x1="{a["x"]}" y1="{PH - a["y"]:.1f}" x2="{b["x"]}" y2="{PH - b["y"]:.1f}" class="ht" stroke-width="3"/>'
                   f'<line x1="{a["x"]}" y1="{PH - a["y"]:.1f}" x2="{b["x"]}" y2="{PH - b["y"]:.1f}" class="lk-{side}" '
                   f'stroke-width="{w:.2f}" stroke-opacity="{op:.2f}"/></g>')
    for n in sorted(nodes.values(), key=lambda n: not n.get("new")):
        r = 2.0 + 1.6 * n["n"] / tmax
        sub = " sub" if n.get("new") else ""
        lab = " (entré dans cette phase)" if n.get("new") else ""
        out.append(f'<g class="hit" {tipattr(f"{n["name"]}{lab} · {n["n"]} ballons joués")}>'
                   f'<circle cx="{n["x"]}" cy="{PH - n["y"]:.1f}" r="{r:.2f}" class="nd-{side}{sub}"/>'
                   f'<text x="{n["x"]}" y="{PH - n["y"]:.1f}" class="nt{sub} t-{side}">{esc(n["number"])}</text></g>')
    return svg_wrap("".join(out), label)


def svg_def_from(shape, side, label):
    out = [f'<circle cx="{x}" cy="{PH - y:.1f}" r="0.55" class="dp-{side}"/>' for x, y in shape.get("def_points", [])]
    h = shape["metrics"].get("defensive_actions_avg_height_m")
    if h:
        out.append(f'<g {tipattr(f"Hauteur moyenne des actions défensives : {fmt_num(h, 0)} m de son but")}>'
                   f'<line x1="{h:.1f}" y1="0" x2="{h:.1f}" y2="68" class="avg"/>'
                   f'<rect x="{h - 1.2:.1f}" y="0" width="2.4" height="68" class="ht"/></g>')
    for n in sorted(shape.get("def_nodes", []), key=lambda n: not n.get("new")):
        sub = " sub" if n.get("new") else ""
        lab = " (entré dans cette phase)" if n.get("new") else ""
        out.append(f'<g class="hit" {tipattr(f"{n["name"]}{lab} · {n["n"]} actions défensives")}>'
                   f'<circle cx="{n["x"]}" cy="{PH - n["y"]:.1f}" r="2.4" class="nd-{side}{sub}"/>'
                   f'<text x="{n["x"]}" y="{PH - n["y"]:.1f}" class="nt{sub} t-{side}">{esc(n["number"])}</text></g>')
    return svg_wrap("".join(out), label)


def phases_html(m, side, uid):
    ph = (m.get("phases") or {}).get(side)
    if not ph:
        return ""
    name = m[side + "_short"]
    tabs, panels = [], []
    for i, p in enumerate(ph):
        tid, pid = f"{uid}-t{i}", f"{uid}-p{i}"
        sel = "true" if i == 0 else "false"
        tabs.append(f'<button type="button" role="tab" id="{tid}" aria-controls="{pid}" aria-selected="{sel}" '
                    f'tabindex="{0 if i == 0 else -1}">{esc(p["label"])}</button>')
        mt = p["metrics"]
        chg = ""
        if p.get("entered"):
            chg = (f'<div class="ph-chg">▲ {esc(", ".join(p["entered"]))}<br>'
                   f'<span class="muted">▼ {esc(", ".join(p["left"]))}</span></div>')
        stats = (f'<div class="ph-m"><span><b>{esc(p["formation"] or "–")}</b></span>'
                 f'<span><b>{mt["pass_share_pct"] if mt["pass_share_pct"] is not None else "–"} %</b> des passes</span>'
                 f'<span>bloc <b>{fmt_num(mt["possession_block_height_m"], 0)} m</b></span>'
                 f'<span>actions déf. <b>{fmt_num(mt["defensive_actions_avg_height_m"], 0)} m</b></span>'
                 f'<span>xG <b>{fmt_num(mt.get("xg_for"), 2)}</b> pour · <b>{fmt_num(mt.get("xg_against"), 2)}</b> contre</span></div>')
        panels.append(f'<div class="ph-panel" role="tabpanel" id="{pid}" aria-labelledby="{tid}"{"" if i == 0 else " hidden"}>'
                      f'{chg}{stats}<div class="ivz-t"><span class="c-{side}">Avec le ballon</span></div>'
                      f'{svg_net_from(p, side, f"{name} avec le ballon, {p["label"]}")}'
                      f'<div class="ivz-t"><span class="c-{side}">Sans le ballon</span></div>'
                      f'{svg_def_from(p, side, f"{name} sans le ballon, {p["label"]}")}</div>')
    return (f'<div class="ph"><div class="ivz-t"><span class="c-{side}">{esc(name)} : placement par phase</span></div>'
            f'<div class="ph-tabs" role="tablist" aria-label="Phases du match">{"".join(tabs)}</div>{"".join(panels)}</div>')


def score_states_html(m):
    ss = m.get("score_states")
    if not ss:
        return ""
    rows = []
    for side in ("home", "away"):
        for state in ("mène", "égalité", "menée"):
            x = ss[side].get(state)
            if not x:
                continue
            rows.append(f'<tr><td><span class="dot {side}"></span> {esc(m[side + "_short"])}</td><td>{state}</td>'
                        f'<td>{x["minutes"]}</td><td>{fmt_num(x["pass_share_pct"], 0)} %</td>'
                        f'<td>{fmt_num(x["onball_height_m"], 0)} m</td><td>{fmt_num(x["defensive_actions_avg_height_m"], 0)} m</td>'
                        f'<td>{fmt_num(x.get("xg_for_per90"), 1)}</td><td>{fmt_num(x.get("xg_against_per90"), 1)}</td></tr>')
    if not rows:
        return ""
    return (f'<figure><div class="ivz-t">Selon le score</div><div class="tscroll"><table class="xgt sst">'
            f'<thead><tr><th>Équipe</th><th>Score</th><th>Min</th><th>Passes</th><th>Haut. ballon</th>'
            f'<th>Haut. déf.</th><th>xG+ /90</th><th>xG− /90</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
            f'<figcaption>Comment chaque équipe a joué selon qu\'elle menait, était à égalité ou était menée : part des passes, '
            f'hauteur moyenne de ses passes et de ses actions défensives (en mètres depuis son but), occasions créées et concédées '
            f'ramenées à 90 minutes (xG+ : créés, xG− : concédés). Seuls les états d\'au moins 8 minutes sont affichés.</figcaption></figure>')


def composition_block(m):
    comp = m.get("composition")
    if not comp:
        return ""
    cols = []
    for side in ("home", "away"):
        c = comp[side]
        lines = [f'<div><b>{esc(c.get("formation") or "–")}</b>'
                 + (f' <span class="muted">({esc(c["coach"])})</span>' if c.get("coach") else "") + "</div>"]
        if c.get("previous_opponent"):
            pf = c.get("previous_formation")
            same = pf == c.get("formation")
            lines.append(f'<div class="muted">Match précédent contre {esc(c["previous_opponent"])} : '
                         f'{"même système" if same else "en " + esc(pf or "–")}</div>')
            n = len(c.get("changes_in") or [])
            if n:
                lines.append(f'<div>{n} changement{"s" if n > 1 else ""} dans le onze : '
                             f'<span class="in">▲ {esc(", ".join(c["changes_in"]))}</span> '
                             f'<span class="muted">▼ {esc(", ".join(c["changes_out"]))}</span></div>')
            else:
                lines.append('<div>Même onze qu\'au match précédent</div>')
        ph = (m.get("phases") or {}).get(side) or []
        forms = [p["formation"] for p in ph if p.get("formation")]
        if len(set(forms)) > 1:
            lines.append("<div>En cours de match : " + " → ".join(
                f'{esc(p["formation"])} <span class="muted">({esc(p["label"].split("–")[0])})</span>' for p in ph) + "</div>")
        cols.append(f'<div><div class="hab-t"><span class="dot {side}"></span> {esc(m[side + "_short"])}</div>'
                    f'<div class="comp">{"".join(lines)}</div></div>')
    return f'<div class="habits comp-b" aria-label="Composition"><h4>Composition</h4>{"".join(cols)}</div>'


TIP_JS = """
(function () {
  var tip = document.createElement('div');
  tip.className = 'tip'; tip.setAttribute('role', 'status'); tip.hidden = true;
  document.body.appendChild(tip);
  function show(el) {
    tip.textContent = el.getAttribute('data-tip'); tip.hidden = false;
    var r = el.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
    var x = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), document.documentElement.clientWidth - w - 8);
    var y = r.top - h - 8; if (y < 8) y = r.bottom + 8;
    tip.style.left = (x + window.scrollX) + 'px'; tip.style.top = (y + window.scrollY) + 'px';
  }
  function hide() { tip.hidden = true; }
  document.addEventListener('pointerover', function (e) {
    if (e.pointerType !== 'mouse') return; var t = e.target.closest('[data-tip]'); if (t) show(t);
  });
  document.addEventListener('pointerout', function (e) {
    if (e.pointerType === 'mouse' && e.target.closest('[data-tip]')) hide();
  });
  document.addEventListener('click', function (e) {
    var t = e.target.closest('[data-tip]'); if (t) show(t); else hide();
  });
  document.addEventListener('focusin', function (e) {
    var t = e.target.closest('[data-tip]'); if (t) show(t);
  });
  document.addEventListener('focusout', hide);
  window.addEventListener('scroll', hide, { passive: true });
  document.addEventListener('click', function (e) {
    var b = e.target.closest('.ph-tabs [role=tab]'); if (!b) return;
    var box = b.closest('.ph');
    box.querySelectorAll('[role=tab]').forEach(function (t) {
      var on = t === b; t.setAttribute('aria-selected', on); t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute('aria-controls')).hidden = !on;
    });
  });
  document.addEventListener('keydown', function (e) {
    var b = e.target.closest('.ph-tabs [role=tab]'); if (!b || (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft')) return;
    var tabs = Array.prototype.slice.call(b.parentNode.children), i = tabs.indexOf(b);
    var n = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length]; n.focus(); n.click();
  });
})();
"""


# ------------------------------------------------------------------ blocs HTML
def _ord(n):
    return "1er" if n == 1 else f"{n}e"


def matchup_block(m):
    mu = m.get("matchup")
    if not mu:
        return ""
    cols = []
    for side in ("home", "away"):
        x = mu[side]
        if x["matches"] < 3:
            body = '<p class="muted">Pas encore assez de matchs pour un profil.</p>'
        else:
            f = "".join(f'<span class="tag good">{esc(r["label"])} <b>{_ord(r["rank"])}</b></span>' for r in x["forces"]) \
                or '<span class="muted">rien dans le top 4</span>'
            w = "".join(f'<span class="tag bad">{esc(r["label"])} <b>{_ord(r["rank"])}</b></span>' for r in x["faiblesses"]) \
                or '<span class="muted">rien dans les 4 derniers</span>'
            body = f'<div class="mu-l">Forces</div><div>{f}</div><div class="mu-l">Faiblesses</div><div>{w}</div>'
        rank = f' <span class="muted">{_ord(x["rank"])}, {x["points"]} pts</span>' if x.get("rank") else ""
        cols.append(f'<div><div class="hab-t"><span class="dot {side}"></span> {esc(m[side + "_short"])}{rank}</div>{body}</div>')
    return ('<div class="habits mu" aria-label="Face-à-face"><h4>Face-à-face sur la saison</h4>'
            + "".join(cols) + '<p class="muted">Rangs parmi les 20 équipes, données jusqu\'à cette journée. '
            'Le détail est dans les fiches équipes.</p></div>')


def goalkeepers_block(m):
    gks = m.get("goalkeepers") or {}
    items = []
    for side in ("home", "away"):
        for g in gks.get(side, []):
            bits = [f'<b>{int(g["saves"])}</b> arrêt{"s" if g["saves"] > 1 else ""}',
                    f'<b>{int(g["goals_conceded"])}</b> encaissé{"s" if g["goals_conceded"] > 1 else ""}']
            if g.get("xgot_faced") is not None:
                bits.append(f'<b>{fmt_num(g["xgot_faced"], 2)}</b> xGOT subis')
            if g.get("goals_prevented") is not None:
                gp = g["goals_prevented"]
                bits.append(f'<b>{"+" if gp > 0 else "−" if gp < 0 else ""}{fmt_num(abs(gp), 2)}</b> but{"s" if abs(gp) >= 2 else ""} évité{"s" if abs(gp) >= 2 else ""}')
            if g.get("errors_led_to_goal"):
                bits.append(f'<b>{int(g["errors_led_to_goal"])}</b> erreur menant à un but')
            if g.get("high_claims"):
                bits.append(f'<b>{int(g["high_claims"])}</b> sortie{"s" if g["high_claims"] > 1 else ""} aérienne{"s" if g["high_claims"] > 1 else ""}')
            p_ok, p_all = g.get("passes") or [None, None]
            if p_all:
                bits.append(f'<b>{p_ok}/{p_all}</b> passes')
            mins = "" if g["minutes"] >= 89 else f' <span class="muted">({g["minutes"]} min)</span>'
            rate = f' <span class="prate">{fmt_num(g["rating"], 1)}</span>' if g.get("rating") else ""
            items.append(f'<li><div><span class="dot {side}"></span> <b>{esc(g["name"])}</b>{mins}{rate}</div>'
                         f'<div class="gk-stats">{" · ".join(bits)}</div></li>')
    if not items:
        return ""
    return ('<div class="gks" aria-label="Gardiens"><h4>Gardiens</h4><ul>' + "".join(items) + "</ul>"
            '<p class="muted">xGOT subis : danger des tirs cadrés affrontés. Buts évités = xGOT subis moins buts '
            'encaissés : positif, le gardien a sauvé plus que prévu.</p></div>')


def habits_block(m):
    ctx = m.get("context")
    if not ctx:
        return ""
    cols = []
    for side in ("home", "away"):
        h = ctx[side]["habits"]
        name = m[f"{side}_short"]
        if h["n_prev"] < 3:
            body = f'<p class="muted">Pas encore assez de matchs pour comparer ({h["n_prev"]} avant celui-ci).</p>'
        elif not h["deviations"]:
            body = '<p class="muted">Rien d\'inhabituel : un match conforme à ses moyennes.</p>'
        else:
            items = []
            for d in h["deviations"]:
                arrow = "▲" if d["value"] > d["season_avg"] else "▼"
                items.append(f'<li><span class="arr">{arrow}</span> {esc(d["label"])} : '
                             f'<b>{fmt_num(d["value"], d["decimals"])}{esc(d["unit"])}</b> '
                             f'<span class="muted">(moyenne {fmt_num(d["season_avg"], d["decimals"])}{esc(d["unit"])})</span></li>')
            body = f'<ul class="hab">{"".join(items)}</ul>'
        cols.append(f'<div><div class="hab-t"><span class="dot {side}"></span> {esc(name)} '
                    f'<span class="muted">vs ses {h["n_prev"]} matchs précédents</span></div>{body}</div>')
    return f'<div class="habits" aria-label="Par rapport à leurs habitudes"><h4>Par rapport à leurs habitudes</h4>{"".join(cols)}</div>'


FIG_ALT = {
    "momentum": "Momentum du match", "form": "Forme sur 5 matchs", "goalkeepers": "Tirs cadrés subis par les gardiens", "positions": "Positions moyennes",
    "heatmaps": "Heatmaps des deux équipes", "shape_home": "Structure avec et sans ballon, domicile",
    "shape_away": "Structure avec et sans ballon, extérieur", "creation_home": "Création d'occasions, domicile",
    "creation_away": "Création d'occasions, extérieur", "player_home": "Fiche du joueur clé à domicile",
    "player_away": "Fiche du joueur clé à l'extérieur", "shots": "Carte des tirs",
}
FIG_CAP = {
    "momentum": "Qui pousse, minute par minute (modèle FotMob). Les triangles marquent les buts.",
    "goalkeepers": "La cage vue de face, avec chaque tir cadré subi par le gardien : plein = but, creux = arrêt, taille = danger du tir (xGOT).",
    "form": "Les 5 derniers matchs de chaque équipe, celui-ci compris : xG créés au-dessus, concédés en dessous. D = domicile, E = extérieur.",
    "positions": "Position moyenne des titulaires, calculée sur toutes leurs actions du match.",
    "heatmaps": "Zones où chaque équipe a eu ses actions (gardien exclu), les deux attaquant vers la droite.",
    "creation_home": "Chaque flèche est une passe qui a mené à un tir ; en blanc, les passes décisives.",
    "creation_away": "Même lecture pour l'équipe à l'extérieur, qui attaque elle aussi vers la droite.",
    "player_home": "Joueur le mieux noté : heatmap du match (point blanc = position moyenne), profil sur la saison (90 = meilleur que 90 % des joueurs du même poste), puis ses notes match par match.",
    "player_away": "Même lecture pour le joueur le mieux noté de l'équipe à l'extérieur.",
}


def static_fig(m, name, outdir, cap=None, extra="", wide=False):
    figs = m.get("figures", {})
    if name not in figs:
        return ""
    w = ' class="wide"' if wide else ""
    return (f'<figure{w}><img src="{img(outdir / figs[name])}" alt="{esc(FIG_ALT[name])} – {esc(m["home"])} '
            f'contre {esc(m["away"])}" loading="lazy"><figcaption>{cap or FIG_CAP.get(name, "")}</figcaption>{extra}</figure>')


FOR_PRINT = False


def dual_fig(m, name, outdir, svg_html, title, cap, extra=""):
    """Graphe interactif à l'écran, image dans le PDF."""
    figs = m.get("figures", {})
    pimg = (f'<img class="print-only" src="{img(outdir / figs[name])}" alt="{esc(FIG_ALT[name])}">'
            if FOR_PRINT and name in figs else "")
    return (f'<figure><div class="ivz"><div class="ivz-t">{title}</div>{svg_html}</div>{pimg}'
            f'<figcaption>{cap}</figcaption>{extra}</figure>')


def numbers_legend(m, side):
    ps = [p for p in m["players"][side] if p["starter"]]
    ps.sort(key=lambda p: int(p["number"]) if str(p["number"]).isdigit() else 99)
    items = "".join(f"<li><b>{esc(p['number'])}</b>{esc(p['name'])}"
                    + (f' <span class="muted">(sorti {esc(p["sub_out"])})</span>' if p.get("sub_out") else "")
                    + "</li>" for p in ps)
    subs = [p for p in m["players"][side] if not p["starter"] and p.get("minutes")]
    subs_html = ""
    if subs:
        subs_html = ('<div class="subs-l">Entrés en jeu (cercles creux) : ' + ", ".join(
            f'<b>{esc(p["number"])}</b> {esc(p["name"])} ({esc(p.get("sub_in") or "")})' for p in subs) + "</div>")
    return (f'<div class="legend one"><div><span class="dot {side}"></span> {esc(m[side])}'
            f'<ol class="cols">{items}</ol>{subs_html}</div></div>')


def match_section(m, txt, outdir):
    st = m["stats"]
    sid = f"m{m['id']}"
    ko = paris(m["kickoff_utc"])
    parts = [f'<section class="match" id="{sid}" aria-labelledby="{sid}-t">']
    parts.append(
        f'<div class="board"><div class="team home" id="{sid}-t">{esc(m["home"])}</div>'
        f'<div class="score">{m["score"][0]}–{m["score"][1]}</div>'
        f'<div class="team away">{esc(m["away"])}</div></div>')
    coaches = m.get("coaches") or [None, None]
    parts.append(
        f'<div class="meta">{date_fr(ko).capitalize()}, {ko:%H:%M} · '
        f'{esc(m["formation"][0])} ({esc(coaches[0])}) contre {esc(m["formation"][1])} ({esc(coaches[1])})</div>')
    gh = "".join(goal_line(g) for g in m["goals"] if g["side"] == "home")
    ga = "".join(goal_line(g) for g in m["goals"] if g["side"] == "away")
    if gh or ga:
        parts.append(f'<div class="scorers"><ul class="home">{gh}</ul><ul class="away">{ga}</ul></div>')
    for r in m.get("red_cards", []):
        team = m["home"] if r["side"] == "home" else m["away"]
        parts.append(f'<div class="red">Carton rouge : {esc(r["player"])} ({esc(team)}), {esc(r["minute"])}</div>')
    if m.get("substitutions"):
        def sub_li(x):
            inj = ' <span class="muted">(blessure)</span>' if x["injury"] else ""
            return (f'<li><span class="in"><span class="num">{esc(x["minute"])}</span> ▲ {esc(x["in"])}</span>'
                    f'<span class="out">▼ {esc(x["out"])}{inj}</span></li>')
        sh = "".join(sub_li(x) for x in m["substitutions"] if x["side"] == "home")
        sa = "".join(sub_li(x) for x in m["substitutions"] if x["side"] == "away")
        parts.append(f'<div class="subs" aria-label="Remplacements"><div class="subs-t">Remplacements</div>'
                     f'<div class="scorers"><ul class="home">{sh}</ul><ul class="away">{sa}</ul></div></div>')

    if txt:
        story = [f'<h3>{esc(txt.get("headline", ""))}</h3>']
        story += [f"<p>{esc(p)}</p>" for p in txt.get("paragraphs", [])]
        if txt.get("keys"):
            story.append('<ul class="keys">' + "".join(f"<li>{esc(k)}</li>" for k in txt["keys"]) + "</ul>")
        parts.append('<div class="story">' + "".join(story) + "</div>")

    parts.append(composition_block(m))
    parts.append(habits_block(m))
    parts.append(matchup_block(m))

    rows = [
        bar_row("Possession", *(st.get("possession") or [None, None]), suffix=" %"),
        bar_row("Expected goals (xG)", *(st.get("xg") or [None, None]), 2, 2),
        bar_row("Tirs", *(st.get("shots") or [None, None])),
        bar_row("Tirs cadrés", *(st.get("shots_on_target") or [None, None])),
        bar_row("Grosses occasions", *(st.get("big_chances") or [None, None])),
        bar_row("Touches dans la surface adverse", *(st.get("touches_opp_box") or [None, None])),
    ]
    stc = m.get("structure")
    if stc:
        rows += [
            bar_row("Passes dans la surface adverse", stc["home"]["box_entries_total"], stc["away"]["box_entries_total"]),
            bar_row("Tirs dans les 10 s après une récupération", stc["home"]["shots_after_regain_10s"],
                    stc["away"]["shots_after_regain_10s"]),
            bar_row("Ballons récupérés dans le camp adverse", stc["home"]["high_regains"], stc["away"]["high_regains"]),
            bar_row("Hauteur des actions défensives (m depuis son but)",
                    stc["home"]["defensive_actions_avg_height_m"], stc["away"]["defensive_actions_avg_height_m"]),
        ]
        ph, pa = stc["home"]["ppda"], stc["away"]["ppda"]
        if ph and pa:
            rows.append(f'<p class="muted" style="font-size:14px;text-align:center;margin:0 auto">Pressing (PPDA) : '
                        f'{fmt_num(ph, 1)} pour {esc(m["home_short"])}, {fmt_num(pa, 1)} pour {esc(m["away_short"])}. '
                        f'Plus c’est bas, plus l’équipe presse.</p>')
    else:
        rows.append(bar_row("Part des actions dans le dernier tiers", *(m.get("final_third_share_pct") or [None, None]),
                            suffix=" %"))
    parts.append('<div class="bars" aria-label="Statistiques du match">' + "".join(rows) + "</div>")
    parts.append(goalkeepers_block(m))

    # Toujours visible : la carte des tirs (interactive)
    parts.append('<div class="figs">' + dual_fig(
        m, "shots", outdir, svg_shots(m),
        f'<span class="c-away">← {esc(m["away_short"])}</span><span class="c-home">{esc(m["home_short"])} →</span>',
        "Chaque cercle est un tir, sa taille suit le xG ; plein = but. Touchez un tir pour le détail.") + "</div>")

    # Le reste : dépliable
    more = [static_fig(m, "momentum", outdir, wide=True), static_fig(m, "form", outdir)]
    if stc and m.get("phases"):
        for side in ("home", "away"):
            figs_ = m.get("figures", {})
            pimg = (f'<img class="print-only" src="{img(outdir / figs_[f"phases_{side}"])}" alt="Placement par phase">'
                    if FOR_PRINT and f"phases_{side}" in figs_ else "")
            more.append(f'<figure>{phases_html(m, side, f"ph{m["id"]}{side[0]}")}{pimg}<figcaption>Le match découpé '
                        f'aux changements de composition : dans chaque phase, seuls les joueurs sur le terrain sont placés '
                        f'(cercles creux : entrés dans cette phase). Touchez une phase, un joueur ou un trait.</figcaption>'
                        f'{numbers_legend(m, side)}</figure>')
        more.append(score_states_html(m))
        for side in ("home", "away"):
            more.append(static_fig(m, f"creation_{side}", outdir))
    elif stc:
        for side in ("home", "away"):
            more.append(dual_fig(m, f"shape_{side}", outdir,
                                 f'{svg_possession(m, side)}<div class="ivz-t">{esc(m[side + "_short"])} sans le ballon</div>{svg_defence(m, side)}',
                                 f'<span class="c-{side}">{esc(m[side + "_short"])} avec le ballon</span>',
                                 "Avec le ballon : position moyenne de chaque titulaire quand il passe ou reçoit le ballon ; "
                                 "un trait relie deux joueurs qui se sont fait au moins 3 passes. Sans le ballon : chaque point "
                                 "est un tacle, une interception, une récupération ou un dégagement ; les numéros donnent la "
                                 "position moyenne de ces actions. Pointillés : hauteur moyenne. Touchez un joueur ou un trait.",
                                 numbers_legend(m, side)))
        for side in ("home", "away"):
            more.append(static_fig(m, f"creation_{side}", outdir))
    else:
        def lst(side):
            ps = [p for p in m["players"][side] if p["starter"]]
            ps.sort(key=lambda p: int(p["number"]) if str(p["number"]).isdigit() else 99)
            return "".join(f"<li><b>{esc(p['number'])}</b>{esc(p['name'])}</li>" for p in ps)
        extra = numbers_legend(m, "home") + numbers_legend(m, "away")
        more.append(static_fig(m, "positions", outdir, extra=extra))
    more += [static_fig(m, "goalkeepers", outdir), static_fig(m, "heatmaps", outdir),
             static_fig(m, "player_home", outdir), static_fig(m, "player_away", outdir)]
    more = [x for x in more if x]
    parts.append(f'<details class="more"><summary>Tous les graphes du match <span class="muted">({len(more)})</span></summary>'
                 f'<div class="figs">{"".join(more)}</div></details>')
    for side in ("home", "away"):
        parts.append(squad_block(m, side))
    parts.append('<div class="top"><a href="#resultats">Retour aux résultats ↑</a></div>')
    parts.append("</section>")
    return "\n".join(parts)


def xg_table_html(S):
    rows = S.get("xg_table") or []
    if not rows:
        return ""
    trs = []
    for r in rows:
        diff = r["diff"]
        sign = "+" if diff > 0 else "−" if diff < 0 else ""
        trs.append(f'<tr><td class="num">{r["rank"]}</td><td>{esc(r.get("short") or r["team"])}</td><td class="num">{r["played"]}</td>'
                   f'<td class="num"><b>{r["points"]}</b></td><td class="num">{fmt_num(r["xpts"], 1)}</td>'
                   f'<td class="num">{sign}{fmt_num(abs(diff), 1)}</td><td class="num muted">{r["xrank"]}</td></tr>')
    return f"""<section id="classement-xg" aria-labelledby="xg-t" style="display:grid;gap:10px">
  <h2 id="xg-t">Classement au xG</h2>
  <p class="muted" style="font-size:14px">Après la journée {S['round']}. xPts : points « mérités » d'après les occasions
  (chaque tir de chaque match simulé avec son xG). Écart : points réels moins xPts. Rang xG : place au classement des xPts.</p>
  <div class="tscroll"><table class="xgt"><thead><tr><th>#</th><th>Équipe</th><th>J</th><th>Pts</th><th>xPts</th>
  <th>Écart</th><th>Rang xG</th></tr></thead><tbody>{''.join(trs)}</tbody></table></div>
</section>"""


def team_of_round_html(S, outdir):
    xi = S.get("team_of_round")
    figname = S.get("team_of_round_figure")
    if not xi or not figname:
        return ""
    lst = "".join(f'<li><b>{fmt_num(p["rating"], 1)}</b> {esc(p["name"])} <span class="muted">({esc(p["team"])})</span></li>'
                  for p in sorted(xi, key=lambda p: (p["role"], -p["py"])))
    return f"""<section id="equipe-type" aria-labelledby="xi-t" style="display:grid;gap:10px">
  <h2 id="xi-t">Équipe type de la journée</h2>
  <figure><img src="{img(outdir / figname)}" alt="Équipe type de la journée {S['round']}"><figcaption>Meilleure note FotMob
  à chaque poste (au moins 60 minutes jouées), en 4-3-3, placés selon leur position moyenne.</figcaption>
  <div class="legend one"><ol class="cols">{lst}</ol></div></figure>
</section>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--out", default="out")
    ap.add_argument("--pdf", action="store_true", help="produit aussi un PDF (Chrome headless)")
    args = ap.parse_args()
    outdir = ROOT / args.out / f"J{args.round}"
    S = json.loads((outdir / "summary.json").read_text())
    A = {}
    archived = ROOT / "reports" / S["season"] / "analysis" / f"J{args.round:02d}.json"
    if (outdir / "analysis.json").exists():
        A = json.loads((outdir / "analysis.json").read_text())
    elif archived.exists():  # texte déjà rédigé : on peut régénérer la page sans le réécrire
        A = json.loads(archived.read_text())
    ms = S["matches"]

    days = sorted(paris(m["kickoff_utc"]) for m in ms)
    if days[0].month == days[-1].month:
        span = f"{days[0].day} – {days[-1].day} {MOIS[days[-1].month - 1]} {days[-1].year}"
    else:
        span = f"{days[0].day} {MOIS[days[0].month - 1]} – {days[-1].day} {MOIS[days[-1].month - 1]} {days[-1].year}"
    title = f"Premier League, journée {S['round']}"

    rows = []
    for m in ms:
        v, upset = verdict(m)
        xg = m["stats"].get("xg") or [None, None]
        sh, sa = m["score"]
        rows.append(
            f'<tr><td class="t-home{" win" if sh > sa else ""}">{esc(m["home_short"])}</td>'
            f'<td class="t-score"><a href="#m{m["id"]}">{sh}–{sa}</a>'
            f'<span class="t-xg">xG {fmt_num(xg[0], 2)} – {fmt_num(xg[1], 2)}</span>'
            f'<span class="chip{" upset" if upset else ""}">{v}</span></td>'
            f'<td class="t-away{" win" if sa > sh else ""}">{esc(m["away_short"])}</td></tr>')

    intro = "".join(f"<p>{esc(p)}</p>" for p in A.get("intro", []))
    page = build_page(S, A, outdir, ms, rows, intro, span, title)
    (outdir / "index.html").write_text(page)
    print(f"OK -> {outdir / 'index.html'} ({len(page) // 1024} Ko)")
    if args.pdf:
        global FOR_PRINT
        FOR_PRINT = True
        printable = build_page(S, A, outdir, ms, rows, intro, span, title)
        FOR_PRINT = False
        pdf_dir = ROOT / "reports" / S["season"]
        pdf_dir.mkdir(parents=True, exist_ok=True)
        make_pdf(printable, outdir, pdf_dir / f"PL {S['season']} - Journee {S['round']:02d}.pdf")
        manifest.record_report(S["season"], S["round"], [m["id"] for m in ms])
        if A:
            archived.parent.mkdir(parents=True, exist_ok=True)
            archived.write_text(json.dumps(A, ensure_ascii=False, indent=1))


def build_page(S, A, outdir, ms, rows, intro, span, title):
    body = f"""<div class="wrap">
<header class="lede">
  <div class="eyebrow">Premier League {esc(S['season'])} · {span}</div>
  <h1>Journée {S['round']}</h1>
  {intro}
</header>
<section id="resultats" aria-labelledby="res-t" style="display:grid;gap:12px">
  <h2 id="res-t">Résultats</h2>
  <table class="results"><tbody>{''.join(rows)}</tbody></table>
  <p class="muted" style="font-size:14px">Touchez un score pour aller au match. « Contre le xG » : le résultat
  va à l'inverse des occasions créées.</p>
</section>
{xg_table_html(S)}
{team_of_round_html(S, outdir)}
<aside class="howto" aria-label="Comment lire">
  <strong>Comment lire</strong>
  <dl>
    <div><dt>Couleurs</dt> <dd><span class="dot home"></span> domicile, <span class="dot away"></span> extérieur.</dd></div>
    <div><dt>xG (expected goals)</dt> <dd>probabilité qu'un tir finisse au fond, d'après des milliers de tirs similaires. La somme donne le nombre de buts « mérités ».</dd></div>
    <div><dt>Grosse occasion</dt> <dd>situation où l'on attend un but (face au gardien, penalty, tir à bout portant).</dd></div>
    <div><dt>Momentum</dt> <dd>danger créé minute par minute (modèle FotMob) : au-dessus, l'équipe à domicile pousse ; en dessous, l'extérieur.</dd></div>
    <div><dt>Actions</dt> <dd>passes, duels, tirs, récupérations… chaque point de heatmap en est une.</dd></div>
    <div><dt>PPDA</dt> <dd>nombre de passes que l'adversaire peut faire dans sa propre moitié (ses 60 % de terrain) avant une action défensive : autour de 8, pressing très intense ; au-delà de 18, bloc bas qui attend.</dd></div>
    <div><dt>Avec / sans le ballon</dt> <dd>calculé à partir de chaque passe et chaque action défensive du match (données Opta via WhoScored).</dd></div>
    <div><dt>Cercles creux</dt> <dd>joueurs entrés en jeu (dans le placement par phase : entrés pendant cette phase).</dd></div>
    <div><dt>Phases</dt> <dd>le match découpé aux changements de composition qui comptent (plusieurs remplacements d'un coup, changement de système) ; chaque phase ne montre que les joueurs alors sur le terrain.</dd></div>
    <div><dt>Habitudes</dt> <dd>écarts les plus nets entre ce match et la moyenne des matchs précédents de l'équipe (données arrêtées à cette journée).</dd></div>
    <div><dt>Graphes interactifs</dt> <dd>touchez un tir, un joueur ou un trait pour voir le détail. « Tous les graphes du match » déplie le reste.</dd></div>
    <div><dt>Centile</dt> <dd>classement sur la saison, stats ramenées à 90 minutes, par rapport aux joueurs du même poste : 90 = meilleur que 90 % d'entre eux. Les étiquettes « points forts » listent les centiles de 80 et plus.</dd></div>
  </dl>
</aside>
{''.join(match_section(m, A.get('matches', {}).get(m['id']), outdir) for m in ms)}
<footer>Données FotMob et WhoScored (Opta), collectées automatiquement après chaque journée. Analyse et graphes générés par Claude.</footer>
</div>"""

    page = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Source+Sans+3:wght@400;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
{body}
<script>{TIP_JS}</script>
</body>
</html>"""
    return page


def make_pdf(page, outdir, pdf):
    chrome = next((c for c in ("google-chrome", "chromium", "chromium-browser") if shutil.which(c)), None)
    if not chrome:
        print("PDF ignoré : Chrome introuvable")
        return
    import io
    import re as _re
    from PIL import Image

    def to_jpeg(mt):
        raw = base64.b64decode(mt.group(1))
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=78, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

    printable = _re.sub(r"data:image/webp;base64,([A-Za-z0-9+/=]+)", to_jpeg, page)
    tmp = outdir / "_print.html"
    tmp.write_text(printable.replace('<details class="', '<details open class="'))
    subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                    "--virtual-time-budget=5000", f"--print-to-pdf={pdf}", tmp.as_uri()],
                   check=True, capture_output=True, timeout=180)
    tmp.unlink()
    print(f"OK -> {pdf} ({pdf.stat().st_size // 1024} Ko)")


if __name__ == "__main__":
    main()
