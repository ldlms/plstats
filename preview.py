#!/usr/bin/env python3
"""Aperçu de la prochaine journée : clés du match (forces contre faiblesses), projection,
forme, style, joueurs à suivre. Données arrêtées au dernier match joué.

Usage :
  python preview.py --due            # journée à préparer (premier match dans < 96 h, pas d'aperçu récent), ou AUCUNE
  python preview.py --round 11 [--pdf]
  python preview.py --record-artifact 11 <slug>
  Test sur une journée passée : python preview.py --round 10 --until 2026-11-05
Sorties : out/P<n>/summary.json, out/P<n>/index.html, reports/<saison>/PL <saison> - Apercu journee NN.pdf
Texte optionnel (rédigé par Claude) : out/P<n>/analysis.json
  {"intro": ["..."], "matches": {"<fixtureId>": {"headline": "...", "paragraph": "..."}}}
"""
import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import render
from render import CSS, MOIS, JOURS, TIP_JS, esc, fmt_num, make_pdf
from profiles import Season
from report import short
from season_context import SeasonContext
from team_profiles import TeamProfiles

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PARIS = ZoneInfo("Europe/Paris")

# (clé attaque, sens, clé défense adverse, sens, libellé attaque, libellé défense, thème)
PAIRS = [
    ("xg_for", "high", "xg_against", "low", "xG créés", "xG concédés", "Attaque contre défense"),
    ("big_chances", "high", "big_chances_against", "low", "grosses occasions", "grosses occasions concédées", "Grosses occasions"),
    ("fast_shots_for", "high", "fast_shots_against", "low", "contre-attaques", "contres subis", "Contre-attaques"),
    ("xg_set_for", "high", "xg_set_against", "low", "xG sur coups de pied arrêtés", "xG concédés sur coups de pied arrêtés", "Coups de pied arrêtés"),
    ("box_entries", "high", "box_entries_against", "low", "passes dans la surface", "passes concédées dans sa surface", "Jeu dans la surface"),
]
LANE_FR = {"left": "à gauche", "center": "dans l'axe", "right": "à droite"}


def ordinal(n):
    return "1er" if n == 1 else f"{n}e"


def poisson(lmb, k):
    return math.exp(-lmb) * lmb ** k / math.factorial(k)


def projection(tp, home, away):
    a, b = tp.avg[home], tp.avg[away]
    if None in (a["xg_for"], a["xg_against"], b["xg_for"], b["xg_against"]):
        return None
    lh = (a["xg_for"] + b["xg_against"]) / 2 * 1.06
    la = (b["xg_for"] + a["xg_against"]) / 2 * 0.94
    ph = [poisson(lh, k) for k in range(11)]
    pa = [poisson(la, k) for k in range(11)]
    win = sum(ph[i] * pa[j] for i in range(11) for j in range(11) if i > j)
    draw = sum(ph[i] * pa[i] for i in range(11))
    best = max(((i, j) for i in range(6) for j in range(6)), key=lambda ij: ph[ij[0]] * pa[ij[1]])
    return {"xg_home": round(lh, 2), "xg_away": round(la, 2), "home": round(100 * win), "draw": round(100 * draw),
            "away": round(100 * (1 - win - draw)), "likely_score": list(best)}


def keys_of_match(tp, ctx_rec, home, away):
    """Confrontations nettes : force d'une équipe contre faiblesse de l'autre (ou l'inverse : verrou)."""
    out = []
    for att, ad, dfn, dd, la, ld, theme in PAIRS:
        for A, B in ((home, away), (away, home)):
            ra = tp.rank_any(A, att, ad)
            rb = tp.rank_any(B, dfn, dd)
            if not ra or not rb:
                continue
            if ra <= 6 and rb >= 14:
                out.append({"type": "avantage", "theme": theme, "team": A, "opponent": B, "score": rb - ra,
                            "text": f"{short(A)} est {ordinal(ra)} en {la}, {short(B)} {ordinal(rb)} en {ld}."})
            elif ra >= 15 and rb <= 5:
                out.append({"type": "verrou", "theme": theme, "team": A, "opponent": B, "score": ra - rb - 2,
                            "text": f"{short(A)} n'est que {ordinal(ra)} en {la}, face à {short(B)}, {ordinal(rb)} en {ld}."})
    # couloirs : là où l'un attaque le plus et où l'autre se fait le plus attaquer
    for A, B in ((home, away), (away, home)):
        za, zb = ctx_rec[A]["zones_for"], ctx_rec[B]["zones_against"]
        if not za or not zb:
            continue
        lane = max(za, key=za.get)
        if za[lane] >= 38 and zb[lane] >= 38:
            out.append({"type": "couloir", "theme": "Couloir", "team": A, "opponent": B, "score": (za[lane] + zb[lane] - 72) / 2,
                        "text": f"{short(A)} attaque surtout {LANE_FR[lane]} ({za[lane]} % de ses attaques) et "
                                f"{short(B)} se fait souvent attaquer de ce côté ({zb[lane]} %)."})
    out.sort(key=lambda k: -k["score"])
    return out[:4]


def key_players(season, team, k=3):
    cands = []
    for pid, a in season.agg.items():
        if a.get("team_full", a.get("team")) != team or a["apps"] < 3 or a["minutes"] < season.min_minutes:
            continue
        rs = [h["rating"] for h in season.history.get(pid, []) if h.get("rating")]
        if len(rs) < 3:
            continue
        prof = season.profile(pid) or {}
        cands.append({"name": a["name"], "avg_rating": round(sum(rs) / len(rs), 2), "apps": a["apps"],
                      "last": rs[-1], "strengths": (prof.get("strengths") or [])[:2],
                      "group": prof.get("group_label")})
    cands.sort(key=lambda c: -c["avg_rating"])
    return cands[:k]


def load_fixtures(season):
    f = DATA / "fixtures" / f"{season}.json"
    return json.loads(f.read_text()) if f.exists() else []


def fixtures_from_matches(season_dir, rnd):
    """Pour tester sur une journée passée : on reconstruit ses affiches à partir des fichiers de match."""
    out = []
    for f in sorted(season_dir.glob("*.json")):
        if f.name.endswith("_heatmap.json"):
            continue
        d = json.loads(f.read_text())
        g = d["general"]
        if str(g.get("matchRound")) == str(rnd):
            out.append({"id": str(g["matchId"]), "round": rnd, "utc": d["header"]["status"]["utcTime"],
                        "home": g["homeTeam"]["name"], "away": g["awayTeam"]["name"], "finished": False})
    return sorted(out, key=lambda x: x["utc"])


def registry_path(season):
    return ROOT / "reports" / season / "previews.json"


def load_registry(season):
    p = registry_path(season)
    return json.loads(p.read_text()) if p.exists() else {}


def save_registry(season, data):
    p = registry_path(season)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1, ensure_ascii=False))


def utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def due_round(season, hours=96):
    now = datetime.now(timezone.utc)
    upcoming = [f for f in load_fixtures(season) if not f["finished"] and not f.get("cancelled") and utc(f["utc"]) > now]
    if not upcoming:
        return None
    rnd = str(min(upcoming, key=lambda f: f["utc"])["round"])
    first = min(utc(f["utc"]) for f in upcoming if str(f["round"]) == rnd)
    if first - now > timedelta(hours=hours):
        return None
    reg = load_registry(season).get(rnd, {})
    if reg.get("generated_at") and now - utc(reg["generated_at"]) < timedelta(hours=hours):
        return None
    return rnd


# ------------------------------------------------------------------ page
EXTRA_CSS = """
.proj { display: flex; height: 26px; border-radius: 6px; overflow: hidden; font-size: 13px; font-weight: 700; gap: 2px; }
.proj span { display: grid; place-items: center; color: #fff; min-width: 2.4em; }
.proj .ph { background: var(--home); } .proj .pd { background: #59625d; } .proj .pa { background: var(--away); }
.proj-l { display: flex; justify-content: space-between; font-size: 13px; color: var(--muted); }
.keysm { margin: 0; padding: 0; list-style: none; display: grid; gap: 8px; }
.keysm li { font-size: 15px; padding-left: 12px; border-left: 3px solid var(--line); }
.keysm li.avantage { border-color: #3c7d55; } .keysm li.verrou { border-color: #8a4040; } .keysm li.couloir { border-color: #6f7d75; }
.keysm .th { display: block; font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
.kp { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; font-size: 15px; }
.kp .muted { font-size: 13.5px; }
.fm { display: inline-grid; place-items: center; width: 24px; height: 24px; border-radius: 6px; font-size: 13px; font-weight: 700;
      border: 1px solid var(--line); cursor: pointer; margin-right: 3px; }
.fm-V { background: #23452f; } .fm-N { background: #3a3f3c; } .fm-D { background: #4a2626; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 480px) { .two { grid-template-columns: 1fr; } }
.fx td { padding: 8px 4px; border-top: 1px solid var(--line); font-size: 15px; }
.fx { width: 100%; border-collapse: collapse; }
.fx .when { color: var(--muted); font-size: 13px; white-space: nowrap; }
"""


def form_chips(rec):
    return "".join(
        f'<span class="fm fm-{r["result"]}" {render.tipattr(f"{r["result"]} {r["gf"]}-{r["ga"]} contre {r["opponent"]} ({r["venue"]})")}>{r["result"]}</span>'
        for r in rec["form"])


def match_card(x, txt):
    ko = utc(x["utc"]).astimezone(PARIS)
    h, a = x["home"], x["away"]
    th, ta = x["table"]["home"], x["table"]["away"]
    parts = [f'<section class="match" id="f{x["id"]}">',
             f'<div class="board"><div class="team home">{esc(h)}</div><div class="score" style="font-size:28px">–</div>'
             f'<div class="team away">{esc(a)}</div></div>',
             f'<div class="meta">{JOURS[ko.weekday()].capitalize()} {ko.day} {MOIS[ko.month - 1]}, {ko:%H:%M}'
             + (f' · {ordinal(th["rank"])} ({th["points"]} pts) contre {ordinal(ta["rank"])} ({ta["points"]} pts)' if th and ta else "")
             + "</div>"]
    if txt:
        parts.append(f'<div class="story"><h3>{esc(txt.get("headline", ""))}</h3><p>{esc(txt.get("paragraph", ""))}</p></div>')
    pr = x["projection"]
    if pr:
        parts.append(
            '<div style="display:grid;gap:6px"><div class="mu-l">Projection d\'après les xG de la saison</div>'
            f'<div class="proj" role="img" aria-label="Victoire {esc(short(h))} {pr["home"]} %, nul {pr["draw"]} %, victoire {esc(short(a))} {pr["away"]} %">'
            f'<span class="ph" style="flex:{max(pr["home"], 6)}">{pr["home"]} %</span><span class="pd" style="flex:{max(pr["draw"], 6)}">{pr["draw"]} %</span>'
            f'<span class="pa" style="flex:{max(pr["away"], 6)}">{pr["away"]} %</span></div>'
            f'<div class="proj-l"><span>{esc(short(h))}</span><span>nul</span><span>{esc(short(a))}</span></div>'
            f'<p class="muted" style="font-size:13.5px">xG attendus {fmt_num(pr["xg_home"], 1)} – {fmt_num(pr["xg_away"], 1)}. Indicatif : ne tient compte ni des absents ni de la forme du moment.</p></div>')
    if x["keys"]:
        lis = "".join(f'<li class="{k["type"]}"><span class="th">{esc(k["theme"])}'
                      f'{" · avantage " + esc(short(k["team"])) if k["type"] == "avantage" else ""}'
                      f'{" · point fort de " + esc(short(k["opponent"])) if k["type"] == "verrou" else ""}</span>{esc(k["text"])}</li>'
                      for k in x["keys"])
        parts.append(f'<div style="display:grid;gap:8px"><h4 style="margin:0;font-family:var(--font-display);font-size:18px;text-transform:uppercase">Les clés du match</h4><ul class="keysm">{lis}</ul></div>')
    parts.append(render.matchup_block({"matchup": x["matchup"], "home_short": short(h), "away_short": short(a)}))
    # style
    rows = []
    for key, label, dec, unit in (("possession", "Possession moyenne", 0, " %"), ("ppda", "PPDA (pressing, bas = intense)", 1, ""),
                                  ("def_height", "Hauteur des actions défensives (m)", 0, ""), ("xg_for", "xG créés par match", 2, ""),
                                  ("xg_against", "xG concédés par match", 2, "")):
        vh, va = x["style"]["home"].get(key), x["style"]["away"].get(key)
        if vh is not None and va is not None:
            rows.append(render.bar_row(label, round(vh, dec), round(va, dec), dec, dec, unit))
    if rows:
        parts.append('<div class="bars" aria-label="Comparaison sur la saison">' + "".join(rows) + "</div>")
    # forme et joueurs
    cols = []
    for side, team in (("home", h), ("away", a)):
        kp = "".join(f'<li><b>{esc(p["name"])}</b> <span class="muted">· moyenne {fmt_num(p["avg_rating"], 1)} sur {p["apps"]} matchs'
                     + ("".join(f' · {esc(s["label"].lower())} ({s["pct"]})' for s in p["strengths"])) + "</span></li>"
                     for p in x["players"][side])
        cols.append(f'<div><div class="hab-t"><span class="dot {side}"></span> {esc(short(team))}</div>'
                    f'<div style="margin:6px 0">{form_chips(x["record"][side])}</div>'
                    f'<div class="mu-l">Joueurs à suivre</div><ul class="kp">{kp or "<li class=muted>–</li>"}</ul></div>')
    parts.append(f'<div class="two">{"".join(cols)}</div>')
    parts.append('<div class="top"><a href="#affiches">Retour aux affiches ↑</a></div></section>')
    return "\n".join(parts)


def build(rnd, until=None, pdf=False, test=False):
    files = sorted(f for f in DATA.glob("matches/*/*.json") if not f.name.endswith("_heatmap.json"))
    season_dir = max(files, key=lambda f: f.name[:10]).parent
    season = season_dir.name
    fixtures = fixtures_from_matches(season_dir, rnd) if test else \
        [f for f in load_fixtures(season) if str(f["round"]) == str(rnd) and not f.get("cancelled")]
    if not fixtures:
        raise SystemExit(f"Aucune affiche pour la journée {rnd}")
    until = until or max(f.name[:10] for f in files if f.name[:10] < min(x["utc"] for x in fixtures)[:10])
    ctx = SeasonContext(season_dir, until)
    tp = TeamProfiles(ctx)
    seas = Season(season_dir, until_date=until)
    table = {r["team"]: r for r in ctx.table()}
    recs = {t: tp.record(t) for t in tp.teams}
    out = []
    for fx in fixtures:
        h, a = fx["home"], fx["away"]
        if h not in recs or a not in recs:
            continue

        def lite(rows):
            return [{"label": r["label"], "rank": r["rank"]} for r in rows]
        x = {"id": fx["id"], "utc": fx["utc"], "home": h, "away": a,
             "table": {"home": table.get(h), "away": table.get(a)},
             "projection": projection(tp, h, a),
             "keys": keys_of_match(tp, recs, h, a),
             "matchup": {s: {"rank": table.get(t, {}).get("rank"), "points": table.get(t, {}).get("points"),
                             "forces": lite(tp.profile(t)["forces"]), "faiblesses": lite(tp.profile(t)["faiblesses"]),
                             "matches": tp.profile(t)["matches"]} for s, t in (("home", h), ("away", a))},
             "style": {s: {k: tp.avg[t].get(k) for k in ("possession", "ppda", "def_height", "xg_for", "xg_against")}
                       for s, t in (("home", h), ("away", a))},
             "record": {"home": recs[h], "away": recs[a]},
             "players": {"home": key_players(seas, h), "away": key_players(seas, a)}}
        out.append(x)

    outdir = ROOT / "out" / f"P{rnd}"
    outdir.mkdir(parents=True, exist_ok=True)
    summary = {"round": int(rnd), "season": season, "data_until": until, "fixtures": out}
    (outdir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    archived = ROOT / "reports" / season / "analysis" / f"P{int(rnd):02d}.json"
    A = json.loads((outdir / "analysis.json").read_text()) if (outdir / "analysis.json").exists() else \
        (json.loads(archived.read_text()) if archived.exists() else {})

    rows = []
    for x in out:
        ko = utc(x["utc"]).astimezone(PARIS)
        pr = x["projection"] or {}
        rows.append(f'<tr><td class="when">{JOURS[ko.weekday()][:3]}. {ko:%H:%M}</td>'
                    f'<td><a href="#f{x["id"]}">{esc(short(x["home"]))} – {esc(short(x["away"]))}</a></td>'
                    f'<td class="num muted" style="text-align:right;white-space:nowrap">{pr.get("home", "–")} / {pr.get("draw", "–")} / {pr.get("away", "–")} %</td></tr>')
    days = sorted(utc(x["utc"]).astimezone(PARIS) for x in out)
    span = f"{days[0].day} – {days[-1].day} {MOIS[days[-1].month - 1]} {days[-1].year}" if days[0].month == days[-1].month \
        else f"{days[0].day} {MOIS[days[0].month - 1]} – {days[-1].day} {MOIS[days[-1].month - 1]} {days[-1].year}"
    yy, mm, dd = until.split("-")
    intro = "".join(f"<p>{esc(p)}</p>" for p in A.get("intro", []))
    title = f"Premier League, aperçu journée {rnd}"
    body = f"""<div class="wrap">
<header class="lede"><div class="eyebrow">Premier League {esc(season)} · {span}</div><h1>Aperçu journée {rnd}</h1>
{intro or '<p>Les affiches de la journée, vues à travers les forces et faiblesses de chaque équipe sur la saison.</p>'}
<p class="muted" style="font-size:14px">Données arrêtées au {int(dd)} {MOIS[int(mm) - 1]} {yy}.</p></header>
<section id="affiches" style="display:grid;gap:10px"><h2>Affiches</h2>
<table class="fx"><tbody>{''.join(rows)}</tbody></table>
<p class="muted" style="font-size:13.5px">Projection : victoire domicile / nul / victoire extérieur.</p></section>
<aside class="howto" aria-label="Comment lire"><strong>Comment lire</strong><dl>
<div><dt>Clés du match</dt> <dd>en vert, une force de l'un face à une faiblesse de l'autre (rang parmi les 20 sur la saison) ; en rouge, un point faible face à un point fort (« verrou ») ; en gris, un couloir où l'attaque de l'un rencontre la faiblesse de l'autre.</dd></div>
<div><dt>Projection</dt> <dd>probabilités tirées des xG moyens créés et concédés par chaque équipe (petit bonus à domicile). Indicatif : ignore les absents.</dd></div>
<div><dt>Joueurs à suivre</dt> <dd>les meilleures notes moyennes de la saison (3 matchs au moins), avec leurs points forts (centiles par poste).</dd></div>
</dl></aside>
{''.join(match_card(x, A.get('matches', {}).get(x['id'])) for x in out)}
<footer>Données FotMob et WhoScored (Opta). Aperçu généré automatiquement par Claude.</footer></div>"""
    page = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Source+Sans+3:wght@400;600;700&display=swap" rel="stylesheet">
<style>{CSS}{EXTRA_CSS}</style></head><body>{body}<script>{TIP_JS}</script></body></html>"""
    (outdir / "index.html").write_text(page)
    print(f"OK -> {outdir / 'index.html'} ({len(page) // 1024} Ko), {len(out)} affiches, données jusqu'au {until}")
    if pdf and not test:
        pdf_dir = ROOT / "reports" / season
        pdf_dir.mkdir(parents=True, exist_ok=True)
        make_pdf(page, outdir, pdf_dir / f"PL {season} - Apercu journee {int(rnd):02d}.pdf")
        if A:
            archived.parent.mkdir(parents=True, exist_ok=True)
            archived.write_text(json.dumps(A, ensure_ascii=False, indent=1))
        reg = load_registry(season)
        reg.setdefault(str(rnd), {})["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        save_registry(season, reg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--due", action="store_true")
    ap.add_argument("--round", type=int)
    ap.add_argument("--until", help="AAAA-MM-JJ (tests)")
    ap.add_argument("--test", action="store_true", help="affiches reconstruites depuis les matchs joués (journée passée)")
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--record-artifact", nargs=2, metavar=("JOURNEE", "SLUG"))
    args = ap.parse_args()
    files = sorted(f for f in DATA.glob("matches/*/*.json") if not f.name.endswith("_heatmap.json"))
    season = max(files, key=lambda f: f.name[:10]).parent.name
    if args.due:
        r = due_round(season)
        print(r or "AUCUNE")
        return
    if args.record_artifact:
        reg = load_registry(season)
        reg.setdefault(str(args.record_artifact[0]), {})["artifact"] = args.record_artifact[1]
        save_registry(season, reg)
        print("Artefact noté")
        return
    build(args.round, args.until, args.pdf, args.test)


if __name__ == "__main__":
    main()
