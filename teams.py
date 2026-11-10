#!/usr/bin/env python3
"""Page « Fiches équipes » : forces/faiblesses, style, zones d'occupation, couloirs,
comportement selon le score, domicile/extérieur. Données arrêtées au dernier match collecté.

Usage : python teams.py [--pdf]          -> out/teams/index.html (+ reports/<saison>/Fiches equipes.pdf)
        python teams.py --record-artifact <slug>
"""
import argparse
import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

import render  # noqa: E402
from render import CSS, TIP_JS, esc, fmt_num, img, make_pdf, MOIS  # noqa: E402
from report import AWAY, FW, HOME, L, MUTED, PITCH, SURFACE, TEXT, W, new_pitch, panel_title, save, short  # noqa: E402
from season_context import SeasonContext  # noqa: E402
from team_profiles import TeamProfiles  # noqa: E402

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def fig_zones(tp, team, path):
    cmap = LinearSegmentedColormap.from_list("div", [AWAY, PITCH, HOME])
    pitch = new_pitch(pad_top=12, pad_bottom=1)
    fig, axes = plt.subplots(2, 1, figsize=(FW, FW * 1.5))
    ok = False
    for ax, kind, title, sub in ((axes[0], "poss", "Où elle joue", "toutes ses actions (hors gardien) · attaque →"),
                                 (axes[1], "def", "Où elle défend", "tacles, interceptions, récupérations · attaque →")):
        diff = tp.occupation_diff(team, kind)
        if diff is not None:
            ok = True
            v = max(abs(diff).max(), 1e-6)
            ax.imshow(diff.T, origin="lower", extent=[0, L, 0, W], cmap=cmap, vmin=-v, vmax=v,
                      interpolation="bilinear", zorder=1, aspect="auto")
        pitch.draw(ax=ax)
        panel_title(ax, f"{title} par rapport à la moyenne", sub, TEXT)
    fig.subplots_adjust(hspace=0.12)
    if ok:
        save(fig, path)
        return True
    plt.close(fig)
    return False


def ordinal(n):
    return "1er" if n == 1 else f"{n}e"


def team_section(tp, team, table_row, outdir):
    p = tp.profile(team)
    rec = tp.record(team)
    sid = "t-" + slug(team)
    tags_f = "".join(f'<span class="tag good">{esc(r["label"])} <b>{ordinal(r["rank"])}</b></span>' for r in p["forces"]) \
        or '<span class="muted">aucun critère dans le top 4</span>'
    tags_w = "".join(f'<span class="tag bad">{esc(r["label"])} <b>{ordinal(r["rank"])}</b></span>' for r in p["faiblesses"]) \
        or '<span class="muted">aucun critère dans les 4 derniers</span>'
    form = "".join(f'<span class="fm fm-{r["result"]}" {render.tipattr(f"{r["result"]} {r["gf"]}-{r["ga"]} contre {r["opponent"]} ({r["venue"]})")}>{r["result"]}</span>'
                   for r in rec["form"])
    tr = table_row
    diff = tr["diff"]
    head = (f'<span class="num">{ordinal(tr["rank"])}</span> · <b>{tr["points"]} pts</b> · xPts {fmt_num(tr["xpts"], 1)} '
            f'({"+" if diff > 0 else "−" if diff < 0 else ""}{fmt_num(abs(diff), 1)}, {ordinal(tr["xrank"])} au xG)')

    # profil en barres, par catégorie
    cats = []
    for cat in dict.fromkeys(r["category"] for r in p["rows"]):
        items = []
        for r in [x for x in p["rows"] if x["category"] == cat]:
            if r["rank"] is None:
                items.append(f'<div class="pr"><div class="pr-l">{esc(r["label"])}</div><div class="pr-v muted">pas assez de matchs</div></div>')
                continue
            cls = "good" if r["rank"] <= 4 else "bad" if r["rank"] >= r["of"] - 3 else ""
            items.append(f'<div class="pr"><div class="pr-l">{esc(r["label"])} <span class="muted">· {fmt_num(r["value"], r["decimals"])} par match</span></div>'
                         f'<div class="pr-bar"><span class="{cls}" style="width:{max(r["pct"], 2)}%"></span></div>'
                         f'<div class="pr-v"><b>{ordinal(r["rank"])}</b>/{r["of"]}</div></div>')
        cats.append(f'<div class="pcat"><h5>{esc(cat)}</h5>{"".join(items)}</div>')
    style = " · ".join(f'{esc(s_["label"])} <b>{fmt_num(s_["value"], s_["decimals"])}{esc(s_["unit"])}</b> '
                       f'<span class="muted">({ordinal(s_["rank"])})</span>' for s_ in p["style"])

    # zones
    zimg = ""
    zp = outdir / f"zones_{slug(team)}.webp"
    if fig_zones(tp, team, zp):
        zimg = (f'<figure><img src="{img(zp)}" alt="Zones d\'occupation de {esc(team)} par rapport à la moyenne" loading="lazy">'
                f'<figcaption>Bleu : l\'équipe y fait plus d\'actions que la moyenne de la ligue ; orange : moins. '
                f'Toujours dans le sens de son attaque (vers la droite).</figcaption></figure>')
    facts = tp.occupation_facts(team)
    zl = []
    if "poss" in facts:
        lanes = facts["poss"]["lanes"]
        zl.append("Avec le ballon, par couloir : " + ", ".join(
            f'{k} <b>{v["team"]} %</b> <span class="muted">({v["league"]})</span>' for k, v in lanes.items()))
    if "def" in facts:
        th = facts["def"]["thirds"]
        zl.append("Actions défensives par tiers : " + ", ".join(
            f'{k} <b>{v["team"]} %</b> <span class="muted">({v["league"]})</span>' for k, v in th.items()))
    if rec["zones_for"]:
        z = rec["zones_for"]
        zl.append(f'Ses attaques : gauche <b>{z["left"]} %</b>, axe <b>{z["center"]} %</b>, droite <b>{z["right"]} %</b>')
    if rec["zones_against"]:
        z = rec["zones_against"]
        zl.append(f'Les attaques qu\'elle subit : gauche <b>{z["left"]} %</b>, axe <b>{z["center"]} %</b>, droite <b>{z["right"]} %</b>')
    zones_txt = "".join(f"<li>{x}</li>" for x in zl)

    # scénario et domicile/extérieur
    h, a = rec["home"], rec["away"]
    scen = (f'<li>A mené dans <b>{rec["led_matches"]}</b> match{"s" if rec["led_matches"] > 1 else ""} : '
            f'<b>{rec["points_dropped_from_lead"]}</b> point{"s" if rec["points_dropped_from_lead"] > 1 else ""} perdu{"s" if rec["points_dropped_from_lead"] > 1 else ""} ensuite.</li>'
            f'<li>A été menée dans <b>{rec["trailed_matches"]}</b> match{"s" if rec["trailed_matches"] > 1 else ""} : '
            f'<b>{rec["points_won_from_behind"]}</b> point{"s" if rec["points_won_from_behind"] > 1 else ""} récupéré{"s" if rec["points_won_from_behind"] > 1 else ""}.</li>')
    venue = (f'<table class="ven"><thead><tr><th></th><th>J</th><th>V-N-D</th><th>Pts</th><th>xPts</th><th>Buts</th></tr></thead><tbody>'
             f'<tr><td>Domicile</td><td>{h["played"]}</td><td>{h["w"]}-{h["d"]}-{h["l"]}</td><td><b>{h["pts"]}</b></td><td>{fmt_num(h["xpts"], 1)}</td><td>{h["gf"]}-{h["ga"]}</td></tr>'
             f'<tr><td>Extérieur</td><td>{a["played"]}</td><td>{a["w"]}-{a["d"]}-{a["l"]}</td><td><b>{a["pts"]}</b></td><td>{fmt_num(a["xpts"], 1)}</td><td>{a["gf"]}-{a["ga"]}</td></tr>'
             f'</tbody></table>')

    return f"""<details class="team" id="{sid}">
<summary><div class="tname">{esc(team)}</div><div class="thead">{head}</div><div class="tform">{form}</div>
<div class="ttags"><div><span class="lbl">Forces</span>{tags_f}</div><div><span class="lbl">Faiblesses</span>{tags_w}</div></div></summary>
<div class="tbody">
  <div class="tstyle"><span class="lbl">Style</span> {style}</div>
  <div class="pcats">{''.join(cats)}</div>
  <h4>Zones d'occupation</h4>
  {zimg}
  <ul class="zl">{zones_txt}</ul>
  <h4>Selon le score et le terrain</h4>
  <ul class="zl">{scen}</ul>
  <div class="tscroll">{venue}</div>
</div>
</details>"""


EXTRA_CSS = """
.tindex { display: flex; flex-wrap: wrap; gap: 6px; }
.tindex a { font-size: 13px; padding: 4px 9px; border: 1px solid var(--line); border-radius: 99px; text-decoration: none; }
details.team { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px; scroll-margin-top: 12px; }
details.team > summary { cursor: pointer; list-style: none; display: grid; gap: 6px; }
details.team > summary::-webkit-details-marker { display: none; }
details.team > summary::after { content: "Voir la fiche complète ▾"; font-size: 13px; color: var(--muted); }
details.team[open] > summary::after { content: "Replier ▴"; }
.tname { font-family: var(--font-display); font-size: 26px; font-weight: 700; line-height: 1.05; }
.thead { font-size: 15px; font-variant-numeric: tabular-nums; }
.tform { display: flex; gap: 4px; }
.fm { display: inline-grid; place-items: center; width: 24px; height: 24px; border-radius: 6px; font-size: 13px; font-weight: 700;
      border: 1px solid var(--line); cursor: pointer; }
.fm-V { background: #23452f; } .fm-N { background: #3a3f3c; } .fm-D { background: #4a2626; }
.ttags { display: grid; gap: 4px; }
.lbl { display: inline-block; min-width: 6.2em; font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
.tag.good { border-color: #3c7d55; } .tag.bad { border-color: #8a4040; }
.tbody { display: grid; gap: 14px; margin-top: 14px; }
.tbody h4 { margin: 4px 0 0; font-family: var(--font-display); font-size: 18px; text-transform: uppercase; }
.tstyle { font-size: 15px; }
.pcats { display: grid; gap: 12px; }
.pcat h5 { margin: 0 0 6px; font-size: 13px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
.pr { display: grid; grid-template-columns: 1fr 3.4em; gap: 2px 10px; align-items: center; margin-bottom: 8px; }
.pr-l { grid-column: 1 / -1; font-size: 14.5px; }
.pr-bar { height: 8px; background: var(--line); border-radius: 4px; overflow: hidden; }
.pr-bar span { display: block; height: 100%; background: #6f7d75; border-radius: 4px; }
.pr-bar span.good { background: var(--home); } .pr-bar span.bad { background: var(--away); }
.pr-v { text-align: right; font-size: 14px; font-variant-numeric: tabular-nums; }
.zl { margin: 0; padding-left: 18px; display: grid; gap: 4px; font-size: 15px; }
.ven { border-collapse: collapse; font-size: 14.5px; font-variant-numeric: tabular-nums; }
.ven th, .ven td { padding: 5px 8px; border-bottom: 1px solid var(--line); text-align: right; white-space: nowrap; }
.ven th:first-child, .ven td:first-child { text-align: left; }
.ven th { color: var(--muted); font-weight: 600; font-size: 13px; }
@media print { details.team { break-before: page; } }
"""


def build(pdf=False):
    files = sorted(f for f in DATA.glob("matches/*/*.json") if not f.name.endswith("_heatmap.json"))
    latest = max(files, key=lambda f: f.name[:10])
    season_dir = latest.parent
    cutoff = latest.name[:10]
    ctx = SeasonContext(season_dir, cutoff)
    tp = TeamProfiles(ctx)
    table = ctx.table()
    last_round = max(int(r["round"]) for r in ctx.rows if str(r["round"]).isdigit())
    outdir = ROOT / "out" / "teams"
    outdir.mkdir(parents=True, exist_ok=True)

    by_team = {r["team"]: r for r in table}
    order = [r["team"] for r in table]
    index = "".join(f'<a href="#t-{slug(t)}">{by_team[t]["rank"]}. {esc(short(t))}</a>' for t in order)
    sections = "".join(team_section(tp, t, by_team[t], outdir) for t in order)
    y, mth, d = cutoff.split("-")
    title = "Premier League, fiches équipes"
    body = f"""<div class="wrap">
<header class="lede">
  <div class="eyebrow">Premier League {esc(season_dir.name)} · après la journée {last_round}</div>
  <h1>Fiches équipes</h1>
  <p>Forces et faiblesses de chaque équipe sur la saison, comparées aux 19 autres, avec ses zones d'occupation
  et son comportement selon le score. Données arrêtées au {int(d)} {MOIS[int(mth) - 1]} {y}.</p>
</header>
<nav class="tindex" aria-label="Équipes">{index}</nav>
<aside class="howto" aria-label="Comment lire">
  <strong>Comment lire</strong>
  <dl>
    <div><dt>Rang</dt> <dd>1er = meilleur des 20 sur ce critère (moyenne par match). Pour les critères « concédés » ou le PPDA, 1er = celui qui en concède le moins ou presse le plus.</dd></div>
    <div><dt>Forces / faiblesses</dt> <dd>les critères où l'équipe est dans le top 4 (bleu) ou dans les 4 derniers (orange).</dd></div>
    <div><dt>Style</dt> <dd>ni bon ni mauvais en soi : possession, précision des passes, hauteur du bloc ; le rang va du plus haut au plus bas.</dd></div>
    <div><dt>Zones d'occupation</dt> <dd>là où l'équipe fait plus (bleu) ou moins (orange) d'actions que la moyenne de la ligue.</dd></div>
    <div><dt>Données</dt> <dd>pressing, contres, passes et zones défensives viennent de WhoScored ; il faut au moins 3 matchs couverts pour un rang.</dd></div>
  </dl>
</aside>
{sections}
<footer>Données FotMob et WhoScored (Opta). Fiches générées automatiquement chaque semaine par Claude.</footer>
</div>"""

    def page(for_print):
        b = body.replace('<details class="team"', '<details open class="team"') if for_print else body
        return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Source+Sans+3:wght@400;600;700&display=swap" rel="stylesheet">
<style>{CSS}{EXTRA_CSS}</style></head>
<body>{b}<script>{TIP_JS}</script></body></html>"""

    html = page(False)
    (outdir / "index.html").write_text(html)
    print(f"OK -> {outdir / 'index.html'} ({len(html) // 1024} Ko), données jusqu'au {cutoff}")
    if pdf:
        pdf_dir = ROOT / "reports" / season_dir.name
        pdf_dir.mkdir(parents=True, exist_ok=True)
        make_pdf(page(True), outdir, pdf_dir / f"PL {season_dir.name} - Fiches equipes.pdf")
    return season_dir.name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--record-artifact", metavar="SLUG")
    args = ap.parse_args()
    if args.record_artifact:
        files = sorted(f for f in DATA.glob("matches/*/*.json") if not f.name.endswith("_heatmap.json"))
        season = max(files, key=lambda f: f.name[:10]).parent.name
        p = ROOT / "reports" / season / "teams.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"artifact": args.record_artifact}, indent=1))
        print("Artefact noté :", args.record_artifact)
        return
    build(args.pdf)


if __name__ == "__main__":
    main()
