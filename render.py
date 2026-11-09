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
@media print {
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
            tags = f'<span class="muted">Trop peu de minutes cette saison ({prof.get("minutes")} min) pour un profil.</span>'
        else:
            tags = '<span class="muted">Pas de point fort qui ressort nettement cette saison.</span>'
        hl = p.get("match_highlights") or []
        rate = f'<span class="prate">{fmt_num(p["rating"], 1)}</span>' if p.get("rating") else ""
        sub = "" if p["starter"] else ' <span class="muted">(entré)</span>'
        items.append(
            f'<li><div class="pname"><span class="pnum">{esc(p["number"])}</span><span>{esc(p["name"])}{sub}</span>'
            f'{rate}<span class="muted">{int(p["minutes"])} min</span></div>'
            + (f'<div class="pline">Ce match : {esc(", ".join(hl))}</div>' if hl else "")
            + f'<div class="pline">{tags}</div></li>')
    color = "home" if side == "home" else "away"
    return (f'<details class="squad"><summary><span class="dot {color}"></span> {esc(m[side])} : '
            f'points forts des joueurs <span class="muted">({len(ps)})</span></summary>'
            f'<ul class="plist">{"".join(items)}</ul></details>')


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

    if txt:
        story = [f'<h3>{esc(txt.get("headline", ""))}</h3>']
        story += [f"<p>{esc(p)}</p>" for p in txt.get("paragraphs", [])]
        if txt.get("keys"):
            story.append('<ul class="keys">' + "".join(f"<li>{esc(k)}</li>" for k in txt["keys"]) + "</ul>")
        parts.append('<div class="story">' + "".join(story) + "</div>")

    rows = [
        bar_row("Possession", *(st.get("possession") or [None, None]), suffix=" %"),
        bar_row("Expected goals (xG)", *(st.get("xg") or [None, None]), 2, 2),
        bar_row("Tirs", *(st.get("shots") or [None, None])),
        bar_row("Tirs cadrés", *(st.get("shots_on_target") or [None, None])),
        bar_row("Grosses occasions", *(st.get("big_chances") or [None, None])),
        bar_row("Touches dans la surface adverse", *(st.get("touches_opp_box") or [None, None])),
        bar_row("Part des actions dans le dernier tiers", *(m.get("final_third_share_pct") or [None, None]),
                suffix=" %"),
    ]
    stc = m.get("structure")
    if stc:
        rows += [
            bar_row("Ballons récupérés dans le camp adverse", stc["home"]["high_regains"], stc["away"]["high_regains"]),
            bar_row("Hauteur des actions défensives (m depuis son but)",
                    stc["home"]["defensive_actions_avg_height_m"], stc["away"]["defensive_actions_avg_height_m"]),
        ]
        ph, pa = stc["home"]["ppda"], stc["away"]["ppda"]
        if ph and pa:
            rows.append(f'<p class="muted" style="font-size:14px;text-align:center;margin:0 auto">Pressing (PPDA) : '
                        f'{fmt_num(ph, 1)} pour {esc(m["home_short"])}, {fmt_num(pa, 1)} pour {esc(m["away_short"])}. '
                        f'Plus c’est bas, plus l’équipe presse.</p>')
    parts.append('<div class="bars" aria-label="Statistiques du match">' + "".join(rows) + "</div>")

    figs = m.get("figures", {})
    caps = {
        "momentum": "Qui pousse, minute par minute. Les triangles marquent les buts.",
        "shots": "Chaque cercle est un tir, sa taille suit le xG. Cercle plein : but.",
        "positions": "Position moyenne des titulaires, calculée sur toutes leurs actions du match.",
        "heatmaps": "Zones où chaque équipe a eu ses actions (gardien exclu), les deux attaquant vers la droite.",
        "shape_home": "En haut, avec le ballon : position moyenne de chaque titulaire quand il passe ou reçoit le ballon (dans le jeu). Un trait relie deux joueurs qui se sont fait au moins 3 passes, plus épais s'ils s'en sont fait beaucoup. En bas, sans le ballon : chaque point est un tacle, une interception, une récupération ou un dégagement ; les numéros marquent la position moyenne de ces actions par joueur. Pointillés : hauteur moyenne.",
        "shape_away": "Même lecture pour l'équipe à l'extérieur, qui attaque elle aussi vers la droite.",
        "player_home": "Joueur le mieux noté : heatmap du match (point blanc = position moyenne), puis profil sur la saison. 90 = meilleur que 90 % des joueurs du même poste.",
        "player_away": "Joueur le mieux noté : heatmap du match (point blanc = position moyenne), puis profil sur la saison. 90 = meilleur que 90 % des joueurs du même poste.",
    }
    figparts = []
    for name in ("momentum", "shots", "positions", "shape_home", "shape_away", "heatmaps", "player_home", "player_away"):
        if name not in figs:
            continue
        alt = {"momentum": "Momentum du match", "shots": "Carte des tirs", "positions": "Positions moyennes",
               "heatmaps": "Heatmaps des deux équipes",
               "shape_home": "Structure avec et sans ballon, équipe à domicile",
               "shape_away": "Structure avec et sans ballon, équipe à l'extérieur", "player_home": "Fiche du joueur clé à domicile",
               "player_away": "Fiche du joueur clé à l'extérieur"}[name]
        extra = ""
        if name in ("shape_home", "shape_away"):
            side = name.split("_")[1]
            ps = [p for p in m["players"][side] if p["starter"]]
            ps.sort(key=lambda p: int(p["number"]) if str(p["number"]).isdigit() else 99)
            items = "".join(f"<li><b>{esc(p['number'])}</b>{esc(p['name'])}</li>" for p in ps)
            extra = (f'<div class="legend one"><div><span class="dot {side}"></span> {esc(m[side])}'
                     f'<ol class="cols">{items}</ol></div></div>')
        if name == "positions":
            def lst(side):
                ps = [p for p in m["players"][side] if p["starter"]]
                ps.sort(key=lambda p: int(p["number"]) if str(p["number"]).isdigit() else 99)
                return "".join(f"<li><b>{esc(p['number'])}</b>{esc(p['name'])}</li>" for p in ps)
            extra = (f'<div class="legend"><div><span class="dot home"></span> {esc(m["home"])}'
                     f'<ol>{lst("home")}</ol></div><div><span class="dot away"></span> {esc(m["away"])}'
                     f'<ol>{lst("away")}</ol></div></div>')
        wide = ' class="wide"' if name == "momentum" else ""
        figparts.append(f'<figure{wide}><img src="{img(outdir / figs[name])}" alt="{esc(alt)} – {esc(m["home"])} '
                        f'contre {esc(m["away"])}" loading="lazy"><figcaption>{caps[name]}</figcaption>{extra}</figure>')
    parts.append('<div class="figs">' + "".join(figparts) + "</div>")
    for side in ("home", "away"):
        parts.append(squad_block(m, side))
    parts.append('<div class="top"><a href="#resultats">Retour aux résultats ↑</a></div>')
    parts.append("</section>")
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--out", default="out")
    ap.add_argument("--pdf", action="store_true", help="produit aussi un PDF (Chrome headless)")
    args = ap.parse_args()
    outdir = ROOT / args.out / f"J{args.round}"
    S = json.loads((outdir / "summary.json").read_text())
    A = {}
    if (outdir / "analysis.json").exists():
        A = json.loads((outdir / "analysis.json").read_text())
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
</body>
</html>"""
    (outdir / "index.html").write_text(page)
    print(f"OK -> {outdir / 'index.html'} ({len(page) // 1024} Ko)")
    if args.pdf:
        pdf_dir = ROOT / "reports" / S["season"]
        pdf_dir.mkdir(parents=True, exist_ok=True)
        make_pdf(page, outdir, pdf_dir / f"PL {S['season']} - Journee {S['round']:02d}.pdf")
        manifest.record_report(S["season"], S["round"], [m["id"] for m in ms])


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
    tmp.write_text(printable.replace('<details class="squad">', '<details class="squad" open>'))
    subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                    "--virtual-time-budget=5000", f"--print-to-pdf={pdf}", tmp.as_uri()],
                   check=True, capture_output=True, timeout=180)
    tmp.unlink()
    print(f"OK -> {pdf} ({pdf.stat().st_size // 1024} Ko)")


if __name__ == "__main__":
    main()
