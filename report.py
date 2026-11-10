#!/usr/bin/env python3
"""Graphes + résumé chiffré d'une journée de Premier League (données FotMob).

Usage :
  python report.py                 # dernière journée présente dans data/latest.json
  python report.py --round 10
Sorties : out/J<n>/<matchId>_{momentum,shots,positions,heatmaps,players}.webp
          out/J<n>/summary.json   (tous les chiffres utilisés par le rapport)
"""
import argparse
import json
import re
import statistics as st
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from mplsoccer import Pitch  # noqa: E402
from scipy.ndimage import gaussian_filter  # noqa: E402

from profiles import Season, flatten, match_highlights  # noqa: E402
import manifest  # noqa: E402
import ws_analysis  # noqa: E402
from season_context import SeasonContext  # noqa: E402
from team_profiles import TeamProfiles  # noqa: E402

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

# Thème sombre unique (validé : bleu/orange séparables en daltonisme)
SURFACE = "#141917"
PITCH = "#18201c"
LINE = "#3d4943"
TEXT = "#e8ece9"
MUTED = "#9aa59f"
HOME = "#3987e5"
AWAY = "#d95926"
HOME_TINT = "#d6e6fb"
AWAY_TINT = "#fbdccb"

plt.rcParams.update({
    "font.family": ["Inter", "DejaVu Sans"],
    "text.color": TEXT,
    "axes.labelcolor": MUTED,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "figure.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
})

CIRCLE = re.compile(r'cx="([\d.]+)" cy="([\d.]+)"')
L, W = 105.0, 68.0
FW = 6.6  # largeur des figures (pouces) : pensée pour un écran de téléphone

SHORT = {
    "Manchester United": "Man United", "Manchester City": "Man City",
    "Brighton & Hove Albion": "Brighton", "AFC Bournemouth": "Bournemouth",
    "Nottingham Forest": "Nott'm Forest", "Tottenham Hotspur": "Tottenham",
    "Newcastle United": "Newcastle", "Leeds United": "Leeds", "Ipswich Town": "Ipswich",
    "Coventry City": "Coventry", "Hull City": "Hull", "Wolverhampton Wanderers": "Wolves",
    "West Ham United": "West Ham", "Leicester City": "Leicester", "Sheffield United": "Sheffield Utd",
    "West Bromwich Albion": "West Brom", "Norwich City": "Norwich", "Luton Town": "Luton",
}


def short(name):
    return SHORT.get(name, name)


# ---------------------------------------------------------------- chargement
def match_files():
    for f in sorted(DATA.glob("matches/*/*.json")):
        if not f.name.endswith("_heatmap.json"):
            yield f


def pick_round(arg):
    """Journée demandée, sinon la plus récente (celle du dernier match joué)."""
    if arg:
        return str(arg)
    latest = max(match_files(), key=lambda f: f.name[:10])  # nom = AAAA-MM-JJ_...
    return str(json.loads(latest.read_text())["general"]["matchRound"])


def num(v):
    """'438 (87%)' -> 438.0 ; '3.55' -> 3.55 ; 26 -> 26.0"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.match(r"\s*(-?[\d.]+)", str(v))
    return float(m.group(1)) if m else None


def pct(v):
    m = re.search(r"\((\d+)%\)", str(v))
    return int(m.group(1)) if m else None


def stat_table(period):
    out = {}
    for grp in period.get("stats", []):
        for s in grp.get("stats", []):
            if s.get("type") == "title" or not s.get("key"):
                continue
            out.setdefault(s["key"], s.get("stats"))
    return out


STAT_KEYS = {
    "possession": "BallPossesion",
    "xg": "expected_goals",
    "xg_open_play": "expected_goals_open_play",
    "xg_set_play": "expected_goals_set_play",
    "xg_non_penalty": "expected_goals_non_penalty",
    "xgot": "expected_goals_on_target",
    "shots": "total_shots",
    "shots_on_target": "ShotsOnTarget",
    "big_chances": "big_chance",
    "big_chances_missed": "big_chance_missed_title",
    "touches_opp_box": "touches_opp_box",
    "corners": "corners",
    "passes": "passes",
    "accurate_passes": "accurate_passes",
    "long_balls": "long_balls_accurate",
    "tackles": "matchstats.headers.tackles",
    "interceptions": "interceptions",
    "clearances": "clearances",
    "keeper_saves": "keeper_saves",
    "duels_won": "duel_won",
    "aerials_won": "aerials_won",
    "dribbles": "dribbles_succeeded",
    "fouls": "fouls",
    "distance_m": "physical_metrics_distance_covered",
    "sprints": "physical_metrics_number_of_sprints",
}


def stats_block(content, period="All"):
    periods = content.get("stats", {}).get("Periods", {})
    raw = stat_table(periods.get(period, {}))
    out = {}
    for name, key in STAT_KEYS.items():
        v = raw.get(key)
        if not v or len(v) != 2:
            continue
        out[name] = [num(v[0]), num(v[1])]
        p = [pct(v[0]), pct(v[1])]
        if any(x is not None for x in p):
            out[name + "_pct"] = p
    return out


def player_stat(p, label):
    for grp in p.get("stats", []):
        s = grp.get("stats", {}).get(label)
        if s:
            return s.get("stat", {}).get("value")
    return None


def minute_str(e):
    t = e.get("time")
    o = e.get("overloadTime")
    return f"{t}+{o}'" if o else f"{t}'"


# ---------------------------------------------------------------- analyse d'un match
def load_match(f):
    d = json.loads(f.read_text())
    hm_path = f.with_name(f.stem + "_heatmap.json")
    heat = json.loads(hm_path.read_text()) if hm_path.exists() else None
    return d, heat


def team_players(content, heat, home_id):
    """Joueurs ayant joué, avec position moyenne et points de heatmap."""
    lineup = content.get("lineup", {})
    ps = content.get("playerStats") or {}
    hp = (heat or {}).get("players", {})
    out = {"home": [], "away": []}
    for side_key, side in (("homeTeam", "home"), ("awayTeam", "away")):
        team = lineup.get(side_key, {})
        for starter, plist in ((True, team.get("starters", [])), (False, team.get("subs", []))):
            for p in plist:
                info = ps.get(str(p["id"]), {})
                minutes = player_stat(info, "Minutes played") or 0
                if not starter and not minutes:
                    continue
                svg = hp.get(f"p{info.get('optaId', '')}".replace("pp", "p"), "")
                pts = [(float(a), float(b)) for a, b in CIRCLE.findall(svg)]
                # SVG : y vers le bas, haut = flanc gauche -> on remet y vers le haut
                pts = [(x, W - y) for x, y in pts]
                perf = p.get("performance", {})
                out[side].append({
                    "id": p["id"],
                    "name": p["name"],
                    "short": p.get("lastName") or p["name"].split()[-1],
                    "number": p.get("shirtNumber"),
                    "starter": starter,
                    "gk": bool(info.get("isGoalkeeper")) or p.get("positionId") == 11,
                    "role": info.get("usualPosition"),  # 0 GK, 1 DEF, 2 MIL, 3 ATT
                    "minutes": minutes,
                    "rating": player_stat(info, "FotMob rating") or perf.get("rating"),
                    "goals": player_stat(info, "Goals") or 0,
                    "assists": player_stat(info, "Assists") or 0,
                    "xg": player_stat(info, "Expected goals (xG)"),
                    "xa": player_stat(info, "Expected assists (xA)"),
                    "chances_created": player_stat(info, "Chances created"),
                    "shots": player_stat(info, "Total shots"),
                    "distance_m": perf.get("totalDistanceCovered"),
                    "n_actions": len(pts),
                    "avg_x": round(st.mean(x for x, _ in pts), 1) if pts else None,
                    "avg_y": round(st.mean(y for _, y in pts), 1) if pts else None,
                    "_pts": pts,
                })
    return out


def shape_metrics(players):
    """Hauteur et largeur du bloc à partir des positions moyennes des titulaires."""
    field = [p for p in players if p["starter"] and not p["gk"] and p["avg_x"] is not None]
    defs = [p for p in field if p["role"] == 1]
    if not field:
        return {}
    ys = [p["avg_y"] for p in field]
    return {
        "block_height_m": round(st.mean(p["avg_x"] for p in field), 1),
        "def_line_m": round(st.mean(p["avg_x"] for p in defs), 1) if defs else None,
        "width_m": round(max(ys) - min(ys), 1),
        "most_advanced": max(field, key=lambda p: p["avg_x"])["name"],
    }


def final_third(players):
    return sum(1 for p in players for x, _ in p["_pts"] if x > 70)


def momentum_phases(data):
    phases = []
    for a in range(0, 90, 15):
        vals = [m["value"] for m in data if a <= m["minute"] < a + 15 or (a == 75 and m["minute"] >= 90)]
        if vals:
            avg = st.mean(vals)
            phases.append({"from": a, "to": a + 15, "avg": round(avg),
                           "dominant": "home" if avg > 15 else "away" if avg < -15 else "equal"})
    return phases


def goals_list(content, home_id):
    out = []
    for e in content.get("matchFacts", {}).get("events", {}).get("events", []):
        if e.get("type") != "Goal":
            continue
        assist = (e.get("assistStr") or "").replace("assist by ", "") or None
        sm = e.get("shotmapEvent") or {}
        out.append({
            "minute": minute_str(e),
            "sort": e.get("time", 0) + (e.get("overloadTime") or 0) / 100,
            "side": "home" if e.get("isHome") else "away",
            "scorer": e.get("nameStr") or (e.get("player") or {}).get("name"),
            "assist": assist,
            "penalty": (e.get("goalDescriptionKey") == "penalty"),
            "own_goal": bool(e.get("ownGoal")),
            "situation": sm.get("situation"),
            "xg": round(sm["expectedGoals"], 2) if sm.get("expectedGoals") is not None else None,
            "score_after": e.get("newScore"),
        })
    return out


def cards_list(content):
    out = []
    for e in content.get("matchFacts", {}).get("events", {}).get("events", []):
        if e.get("type") == "Card" and e.get("card") in ("Red", "YellowRed"):
            out.append({"minute": minute_str(e), "side": "home" if e.get("isHome") else "away",
                        "player": e.get("nameStr") or (e.get("player") or {}).get("name"),
                        "type": e.get("card")})
    return out


# ---------------------------------------------------------------- graphes
def new_pitch(**kw):
    return Pitch(pitch_type="custom", pitch_length=L, pitch_width=W, pitch_color=PITCH,
                 line_color=LINE, linewidth=1.2, line_zorder=2, **kw)


def save(fig, path):
    fig.savefig(path, dpi=150, bbox_inches="tight", pad_inches=0.15, format="webp",
                pil_kwargs={"quality": 82})
    plt.close(fig)


def place_labels(ax, items, fontsize):
    """Place des étiquettes [(x, y, texte)] sans chevauchement (glouton)."""
    placed = []
    unit = 0.62 * fontsize / 4.0          # largeur d'un caractère en mètres (approx.)
    h = fontsize / 3.3
    for x, y, txt in sorted(items, key=lambda t: t[0]):
        w = unit * len(txt)
        for dy in (2.4, -2.4 - h, 2.4 + h + 0.6, -3.0 - 2 * h, 3.6 + 2 * h, -3.6 - 3 * h):
            y0 = y + dy
            box = (x - w / 2, x + w / 2, y0, y0 + h)
            if box[2] < 0.5 or box[3] > W - 0.5:
                continue
            if all(box[1] < b[0] or box[0] > b[1] or box[3] < b[2] or box[2] > b[3] for b in placed):
                break
        placed.append(box)
        tx = min(max(x, w / 2 + 0.5), L - w / 2 - 0.5)
        if abs(dy) > 4:
            ax.plot([x, tx], [y, y0 + (0 if dy > 0 else h)], color=MUTED, lw=0.8, zorder=4)
        ax.text(tx, y0, txt, ha="center", va="bottom", fontsize=fontsize, color=TEXT, zorder=6,
                bbox=dict(boxstyle="round,pad=0.18", fc=PITCH, ec="none", alpha=0.85))


def fig_shots(m, path):
    pitch = new_pitch(pad_top=8, pad_bottom=1.5)
    fig, ax = pitch.draw(figsize=(FW, FW * 0.74))
    labels = []
    for side, color in (("home", HOME), ("away", AWAY)):
        for s in m["_shots"][side]:
            x, y = s["x"], W - s["y"]
            if side == "away":
                x, y = L - x, W - y
            size = 22 + 750 * (s["expectedGoals"] or 0)
            goal = s["eventType"] == "Goal"
            pitch.scatter(x, y, s=size, ax=ax, zorder=4 if goal else 3,
                          facecolor=color if goal else "none", edgecolor=SURFACE if goal else color,
                          linewidth=1.6 if goal else 1.3, alpha=1 if goal else 0.85)
            if goal:
                mins = f"{s['min']}+{s['minAdded']}'" if s.get("minAdded") else f"{s['min']}'"
                labels.append((x, y, f"{s['lastName'] or s['playerName']} {mins}"))
    place_labels(ax, labels, 10)
    h, a = short(m["home"]), short(m["away"])
    xg = m["stats"].get("xg", [0, 0])
    sh = m["stats"].get("shots", [0, 0])
    ax.text(L - 1, W + 4.2, f"{h} · {xg[0]:.2f} xG · {int(sh[0])} tirs →",
            ha="right", va="center", fontsize=11.5, color=HOME, fontweight="bold")
    ax.text(1, W + 4.2, f"← {a} · {xg[1]:.2f} xG · {int(sh[1])} tirs",
            ha="left", va="center", fontsize=11.5, color=AWAY, fontweight="bold")
    save(fig, path)


def fig_positions(m, path):
    pitch = new_pitch(pad_top=8, pad_bottom=1.5)
    fig, ax = pitch.draw(figsize=(FW, FW * 0.74))
    for side, color in (("home", HOME), ("away", AWAY)):
        for p in sorted(m["players"][side], key=lambda p: p["starter"]):
            if p["avg_x"] is None or (not p["starter"] and (p.get("minutes") or 0) < 15):
                continue
            x, y = p["avg_x"], p["avg_y"]
            if side == "away":
                x, y = L - x, W - y
            sub = not p["starter"]
            pitch.scatter(x, y, s=330, ax=ax, facecolor=PITCH if sub else color, edgecolor=color if sub else SURFACE,
                          linewidth=2, zorder=4)
            ax.text(x, y, str(p["number"]), ha="center", va="center", fontsize=10.5,
                    fontweight="bold", color=color if sub else "white", zorder=5)
    ax.text(L - 1, W + 4.2, f"{short(m['home'])} ({m['formation'][0]}) →", ha="right",
            va="center", fontsize=11.5, color=HOME, fontweight="bold")
    ax.text(1, W + 4.2, f"← {short(m['away'])} ({m['formation'][1]})", ha="left",
            va="center", fontsize=11.5, color=AWAY, fontweight="bold")
    save(fig, path)


def panel_title(ax, title, subtitle, color):
    ax.text(0, W + 8.2, title, ha="left", va="center", fontsize=12.5, fontweight="bold", color=color)
    ax.text(0, W + 3.6, subtitle, ha="left", va="center", fontsize=10.5, color=MUTED)


def heat_grid(pts, sigma=1.6):
    if not pts:
        return None
    xs, ys = zip(*pts)
    H, _, _ = np.histogram2d(xs, ys, bins=[42, 27], range=[[0, L], [0, W]])
    H = gaussian_filter(H, sigma)
    return H / H.max() if H.max() > 0 else H


def draw_heat(ax, pitch, pts, color, tint, title, subtitle):
    cmap = LinearSegmentedColormap.from_list("t", [PITCH, color, tint])
    H = heat_grid(pts)
    if H is not None:
        ax.imshow(H.T, origin="lower", extent=[0, L, 0, W], cmap=cmap, vmin=0.04, vmax=1,
                  interpolation="bilinear", zorder=1, aspect="auto")
    pitch.draw(ax=ax)
    panel_title(ax, title, subtitle, color)


def fig_team_heatmaps(m, path):
    pitch = new_pitch(pad_top=12, pad_bottom=1)
    fig, axes = plt.subplots(2, 1, figsize=(FW, FW * 1.5))
    for ax, side, color, tint in ((axes[0], "home", HOME, HOME_TINT), (axes[1], "away", AWAY, AWAY_TINT)):
        pts = [pt for p in m["players"][side] if not p["gk"] for pt in p["_pts"]]
        draw_heat(ax, pitch, pts, color, tint, short(m[side]), f"{len(pts)} actions · attaque →")
    fig.subplots_adjust(hspace=0.12)
    save(fig, path)


def fig_player(m, side, path):
    p = m["key_players"][side]
    color, tint = (HOME, HOME_TINT) if side == "home" else (AWAY, AWAY_TINT)
    prof = p.get("profile") or {}
    rows = prof.get("rows", [])
    n = max(len(rows), 1)
    hist = [h for h in prof.get("history", []) if h.get("rating")]
    hh = 1.9 if len(hist) >= 2 else 0
    fig = plt.figure(figsize=(FW, FW * 0.78 + 0.43 * n + 0.6 + hh))
    gs = fig.add_gridspec(3 if hh else 2, 1,
                          height_ratios=[FW * 0.78, 0.43 * n + 0.6] + ([hh] if hh else []), hspace=0.12)
    ax = fig.add_subplot(gs[0])
    pitch = new_pitch(pad_top=12, pad_bottom=1)
    draw_heat(ax, pitch, p["_pts"], color, tint, f"{p['name']} ({short(m[side])})",
              f"note {p['rating']:.1f} · attaque →")
    if p["avg_x"] is not None:
        pitch.scatter(p["avg_x"], p["avg_y"], s=90, ax=ax, facecolor=TEXT, edgecolor=SURFACE,
                      linewidth=2, zorder=5)
    bx = fig.add_subplot(gs[1])
    bx.set_facecolor(SURFACE)
    bx.set_xlim(0, 112)
    bx.set_ylim(n - 0.3, -1.25)
    bx.axis("off")
    if prof:
        head = (f"Profil sur la saison : centile parmi {prof['pool_size']} {prof['group_label']}"
                if prof["qualified"] else
                f"Profil indicatif : trop tôt dans la saison ({prof['apps']} match{'s' if prof['apps'] > 1 else ''}, {prof['minutes']} min)")
        bx.text(0, -0.95, head, fontsize=10.5, color=MUTED, va="center")
    for i, r in enumerate(rows):
        bx.barh(i + 0.18, 100, height=0.3, color=LINE, alpha=0.6, zorder=1)
        if r["pct"] is not None:
            strong = r["pct"] >= 80
            bx.barh(i + 0.18, max(r["pct"], 1.5), height=0.3, color=color, alpha=1 if strong else 0.55, zorder=2)
        if r["value"] is None:
            val = "–"
        elif r["unit"] == "%":
            val = f"{r['value']:.0f}"
        else:
            val = f"{r['value']:.2f}".rstrip("0").rstrip(".").replace(".", ",")
        bx.text(0, i - 0.22, f"{r['label']}  ·  {val} {r['unit']}", fontsize=10, color=TEXT, va="center")
        bx.text(103, i + 0.18, "–" if r["pct"] is None else str(r["pct"]), fontsize=11,
                fontweight="bold", color=TEXT if (r["pct"] or 0) >= 80 else MUTED, va="center")
    if hh:
        cx = fig.add_subplot(gs[2])
        cx.set_facecolor(SURFACE)
        xs = list(range(len(hist)))
        ys = [h["rating"] for h in hist]
        cx.plot(xs, ys, color=color, lw=2, zorder=2)
        cx.scatter(xs[:-1], ys[:-1], s=22, color=color, zorder=3)
        cx.scatter([xs[-1]], [ys[-1]], s=60, color=TEXT, edgecolor=SURFACE, zorder=4)
        cx.axhline(st.mean(ys), color=LINE, lw=1, ls=(0, (3, 3)))
        cx.set_ylim(min(ys + [6]) - 0.4, max(ys + [8]) + 0.6)
        cx.set_xticks(xs)
        cx.set_xticklabels([f"J{h['round']}" for h in hist], fontsize=8.5)
        cx.tick_params(length=0, labelsize=8.5)
        for sp in cx.spines.values():
            sp.set_visible(False)
        cx.text(0, 1.08, f"Notes sur la saison (moyenne {st.mean(ys):.1f})".replace(".", ","),
                transform=cx.transAxes, fontsize=10.5, color=MUTED, va="bottom")
        if prof.get("similar"):
            names = ", ".join(f"{x['name']} ({short(x['team'])})" for x in prof["similar"])
            cx.text(0, -0.42, f"Profils proches : {names}", transform=cx.transAxes, fontsize=9.5,
                    color=TEXT, va="top", wrap=True)
    save(fig, path)


def fig_team_shape(m, side, ta, path):
    """Deux terrains : avec le ballon (réseau de passes) / sans le ballon (actions défensives)."""
    color, tint = (HOME, HOME_TINT) if side == "home" else (AWAY, AWAY_TINT)
    mt = ta["metrics"]
    pitch = new_pitch(pad_top=12, pad_bottom=1)
    fig, axes = plt.subplots(2, 1, figsize=(FW, FW * 1.5))
    # Avec le ballon
    ax = axes[0]
    pitch.draw(ax=ax)
    by_id = {n["playerId"]: n for n in ta["nodes"]}
    nmax = max((e["n"] for e in ta["edges"]), default=1)
    for e in sorted(ta["edges"], key=lambda e: e["n"]):
        a, b = by_id[e["a"]], by_id[e["b"]]
        w = 0.8 + 5.2 * e["n"] / nmax
        ax.plot([a["x"], b["x"]], [a["y"], b["y"]], color=tint, lw=w, alpha=0.25 + 0.55 * e["n"] / nmax,
                zorder=3, solid_capstyle="round")
    tmax = max((n["n"] for n in ta["nodes"]), default=1)
    for n in sorted(ta["nodes"], key=lambda n: not n.get("sub")):
        size = 150 + 330 * n["n"] / tmax
        sub = n.get("sub")
        pitch.scatter(n["x"], n["y"], s=size, ax=ax, facecolor=PITCH if sub else color,
                      edgecolor=color if sub else SURFACE, linewidth=2, zorder=4)
        ax.text(n["x"], n["y"], str(n["number"]), ha="center", va="center", fontsize=10, fontweight="bold",
                color=color if sub else "white", zorder=5)
    if mt["possession_block_height_m"]:
        ax.plot([mt["possession_block_height_m"]] * 2, [0, W], color=TEXT, lw=1, ls=(0, (4, 4)), alpha=0.6, zorder=2)
    sub = f"bloc à {mt['possession_block_height_m']:.0f} m de son but · largeur {mt['possession_width_m']:.0f} m" \
        if mt["possession_block_height_m"] else ""
    panel_title(ax, f"{short(m[side])} avec le ballon", f"{sub} · attaque →", color)
    # Sans le ballon
    ax = axes[1]
    pitch.draw(ax=ax)
    if ta["def_points"]:
        xs, ys = zip(*ta["def_points"])
        pitch.scatter(xs, ys, s=22, ax=ax, facecolor=color, edgecolor="none", alpha=0.35, zorder=3)
    for n in sorted(ta["def_nodes"], key=lambda n: not n.get("sub")):
        sub = n.get("sub")
        pitch.scatter(n["x"], n["y"], s=300, ax=ax, facecolor=PITCH if sub else color,
                      edgecolor=color if sub else SURFACE, linewidth=2, zorder=4)
        ax.text(n["x"], n["y"], str(n["number"]), ha="center", va="center", fontsize=10, fontweight="bold",
                color=color if sub else "white", zorder=5)
    h = mt["defensive_actions_avg_height_m"]
    if h:
        ax.plot([h, h], [0, W], color=TEXT, lw=1, ls=(0, (4, 4)), alpha=0.6, zorder=2)
    ppda = f" · PPDA {mt['ppda']:.1f}".replace(".", ",") if mt["ppda"] else ""
    hh = f"actions défensives à {h:.0f} m de son but en moyenne" if h else "actions défensives"
    panel_title(ax, f"{short(m[side])} sans le ballon", f"{hh}{ppda}", color)
    fig.subplots_adjust(hspace=0.12)
    save(fig, path)


def fig_form(m, path):
    """Forme : xG créés (haut) et concédés (bas) sur les 5 derniers matchs, pour chaque équipe."""
    fig, axes = plt.subplots(2, 1, figsize=(FW, FW * 1.0))
    for ax, side, color in ((axes[0], "home", HOME), (axes[1], "away", AWAY)):
        rows = m["context"][side]["form"]
        ax.set_facecolor(SURFACE)
        xs = list(range(len(rows)))
        xf = [r["xg_for"] or 0 for r in rows]
        xa = [-(r["xg_against"] or 0) for r in rows]
        ax.bar(xs, xf, width=0.55, color=color, zorder=2)
        ax.bar(xs, xa, width=0.55, color=MUTED, alpha=0.55, zorder=2)
        ax.axhline(0, color=LINE, lw=1)
        top = max([abs(v) for v in xf + xa] + [1.5])
        ax.set_ylim(-top - 0.9, top + 0.6)
        for x, r in zip(xs, rows):
            ax.text(x, (r["xg_for"] or 0) + 0.12, f"{r['xg_for']:.1f}".replace(".", ","), ha="center",
                    va="bottom", fontsize=11, color=TEXT)
            ax.text(x, -(r["xg_against"] or 0) - 0.12, f"{r['xg_against']:.1f}".replace(".", ","),
                    ha="center", va="top", fontsize=11, color=MUTED)
        ax.set_xticks(xs)
        ax.set_xticklabels([f"{short(r['opponent'])[:11]}\n{r['result']} {r['gf']}-{r['ga']} ({r['venue']})"
                            for r in rows], fontsize=10.5)
        ax.tick_params(length=0)
        ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.set_xlim(-0.6, max(len(rows), 1) - 0.4)
        ax.text(0, 1.04, f"{short(m[side])} : 5 derniers matchs", transform=ax.transAxes, fontsize=12,
                fontweight="bold", color=color, ha="left", va="bottom")
        ax.text(1, 1.04, "xG créés ↑  xG concédés ↓", transform=ax.transAxes, fontsize=9.5,
                color=MUTED, ha="right", va="bottom")
    fig.subplots_adjust(hspace=0.55)
    save(fig, path)


def fig_creation(m, side, cr, path):
    """Passes qui ont mené à un tir (blanc : passe décisive), en jeu et sur coups de pied arrêtés."""
    color = HOME if side == "home" else AWAY
    pitch = new_pitch(pad_top=12, pad_bottom=1)
    fig, ax = pitch.draw(figsize=(FW, FW * 0.78))
    for kp in sorted(cr["key_passes"], key=lambda k: k["assist"]):
        c = TEXT if kp["assist"] else color
        pitch.arrows(kp["x"], kp["y"], kp["endX"], kp["endY"], ax=ax, color=c, width=1.6 if kp["assist"] else 1.2,
                     headwidth=5, headlength=5, alpha=0.95 if kp["assist"] else 0.7, zorder=3)
        pitch.scatter(kp["x"], kp["y"], s=14, ax=ax, color=c, zorder=4)
    n = len(cr["key_passes"])
    na = sum(1 for k in cr["key_passes"] if k["assist"])
    b = cr["box_entries"]
    panel_title(ax, f"{short(m[side])} : comment les occasions ont été créées",
                f"{n} passes menant à un tir dont {na} décisive{'s' if na > 1 else ''} · "
                f"passes dans la surface G {b['gauche']} / axe {b['axe']} / D {b['droite']}", color)
    save(fig, path)


def fig_team_of_round(xi, rnd, path):
    pitch = new_pitch(pad_top=10, pad_bottom=1)
    fig, ax = pitch.draw(figsize=(FW, FW * 0.78))
    for p in xi:
        pitch.scatter(p["px"], p["py"], s=360, ax=ax, facecolor=HOME, edgecolor=SURFACE, linewidth=2, zorder=4)
        ax.text(p["px"], p["py"], f"{p['rating']:.1f}".replace(".", ","), ha="center", va="center",
                fontsize=9, fontweight="bold", color="white", zorder=5)
        ax.text(p["px"], p["py"] - 5.2, p["short"], ha="center", va="top", fontsize=9.5, color=TEXT, zorder=5,
                bbox=dict(boxstyle="round,pad=0.15", fc=PITCH, ec="none", alpha=0.8))
        ax.text(p["px"], p["py"] - 8.6, short(p["team"]), ha="center", va="top", fontsize=8, color=MUTED, zorder=5)
    panel_title(ax, f"Équipe type de la journée {rnd}", "les meilleures notes FotMob par poste (60 min jouées au moins)", HOME)
    save(fig, path)


def fig_goalkeepers(m, path):
    """La cage vue de face : tirs cadrés subis par chaque gardien (plein = but, creux = arrêt)."""
    fig, axes = plt.subplots(2, 1, figsize=(FW, FW * 0.95))
    for ax, side in ((axes[0], "home"), (axes[1], "away")):
        color = HOME if side == "home" else AWAY
        opp = "away" if side == "home" else "home"
        ax.set_facecolor(SURFACE)
        ax.set_xlim(-1.4, 7.32 + 1.4)
        ax.set_ylim(-0.25, 2.44 + 1.05)
        ax.set_aspect("equal")
        ax.axis("off")
        ax.plot([0, 0, 7.32, 7.32], [0, 2.44, 2.44, 0], color=TEXT, lw=3, solid_capstyle="round", zorder=2)
        ax.plot([-1.2, 8.52], [0, 0], color=LINE, lw=1.5, zorder=1)
        for x in np.arange(0.61, 7.32, 0.61):
            ax.plot([x, x], [0, 2.44], color=LINE, lw=0.5, zorder=1)
        for y in np.arange(0.4, 2.44, 0.4):
            ax.plot([0, 7.32], [y, y], color=LINE, lw=0.5, zorder=1)
        on = [s_ for s_ in m["_shots"][opp] if s_.get("isOnTarget") and not s_.get("isBlocked")
              and s_.get("goalCrossedY") is not None]
        for s_ in sorted(on, key=lambda s_: s_["eventType"] == "Goal"):
            gx = min(max(s_["goalCrossedY"] - 30.34, 0.1), 7.22)
            gz = min(max(s_.get("goalCrossedZ") or 0.1, 0.12), 2.34)
            xgot = s_.get("expectedGoalsOnTarget") or 0
            goal = s_["eventType"] == "Goal"
            ax.scatter(gx, gz, s=50 + 900 * xgot, facecolor=color if goal else "none",
                       edgecolor=SURFACE if goal else color, linewidth=1.8, zorder=4 if goal else 3)
        gks = m["goalkeepers"][side]
        g = max(gks, key=lambda x: x["minutes"]) if gks else None
        name = g["name"] if g else short(m[side])
        ax.text(-1.4, 2.44 + 0.82, f"{name} ({short(m[side])})", fontsize=12, fontweight="bold", color=color, va="center")
        if g:
            gp = g["goals_prevented"]
            gps = (f" · {gp:+.2f} buts évités".replace(".", ",").replace("-", "−")) if gp is not None else ""
            xg = f" · {g['xgot_faced']:.2f} xGOT subis".replace(".", ",") if g["xgot_faced"] is not None else ""
            ax.text(-1.4, 2.44 + 0.42, f"{int(g['saves'])} arrêts · {int(g['goals_conceded'])} encaissés{xg}{gps}",
                    fontsize=10, color=MUTED, va="center")
    fig.subplots_adjust(hspace=0.15)
    save(fig, path)


def fig_momentum(m, path):
    data = m["_momentum"]
    fig, ax = plt.subplots(figsize=(FW, FW * 0.46))
    ax.set_facecolor(SURFACE)
    xs = [d["minute"] for d in data]
    vs = [d["value"] for d in data]
    ax.bar(xs, [max(v, 0) for v in vs], width=0.82, color=HOME, zorder=2)
    ax.bar(xs, [min(v, 0) for v in vs], width=0.82, color=AWAY, zorder=2)
    ax.axhline(0, color=LINE, lw=1, zorder=1)
    ax.axvline(45.5, color=LINE, lw=1, ls=(0, (3, 3)), zorder=1)
    last = {"home": [], "away": []}
    for g in m["goals"]:
        x = min(g["sort"], 90.6)
        up = g["side"] == "home"
        level = sum(1 for px in last[g["side"]] if abs(px - x) < 6)
        last[g["side"]].append(x)
        y = 108 if up else -108
        ax.plot([x], [y], marker="v" if up else "^", ms=6, color=HOME if up else AWAY, zorder=3, clip_on=False)
        ty = (124 + 17 * level) if up else -(124 + 17 * level)
        ax.text(x, ty, g["minute"], ha="center", va="center", fontsize=9.5, color=TEXT, clip_on=False)
    ax.set_xlim(-0.5, 92)
    ax.set_ylim(-150, 150)
    ax.set_yticks([])
    ax.set_xticks([0, 15, 30, 45, 60, 75, 90])
    ax.set_xticklabels(["0'", "15'", "30'", "45'", "60'", "75'", "90'"], fontsize=10)
    ax.tick_params(length=0)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.text(0, 1.06, f"▲ {short(m['home'])} domine", transform=ax.transAxes, fontsize=11,
            color=HOME, fontweight="bold", ha="left", va="bottom")
    ax.text(1, 1.06, f"{short(m['away'])} domine ▼", transform=ax.transAxes, fontsize=11,
            color=AWAY, fontweight="bold", ha="right", va="bottom")
    save(fig, path)


# ---------------------------------------------------------------- assemblage
def build_match(f, outdir, season, ctx):
    d, heat = load_match(f)
    g, c = d["general"], d["content"]
    home_id = g["homeTeam"]["id"]
    teams = d["header"]["teams"]
    players = team_players(c, heat, home_id)
    pstats = c.get("playerStats") or {}
    subs = []
    for e in c.get("matchFacts", {}).get("events", {}).get("events", []):
        if e.get("type") == "Substitution" and len(e.get("swap") or []) == 2:
            pin, pout = e["swap"]
            subs.append({"minute": minute_str(e), "sort": e.get("time", 0) + (e.get("overloadTime") or 0) / 100,
                         "side": "home" if e.get("isHome") else "away", "in": pin.get("name"), "out": pout.get("name"),
                         "in_id": str(pin.get("id")), "out_id": str(pout.get("id")),
                         "injury": bool(e.get("injuredPlayerOut"))})
    subs.sort(key=lambda x: x["sort"])
    for side in ("home", "away"):
        for p in players[side]:
            p["profile"] = season.profile(p["id"])
            p["match_highlights"] = match_highlights(pstats.get(str(p["id"]), {}))
            p["sub_in"] = next((x["minute"] for x in subs if x["in_id"] == str(p["id"])), None)
            p["sub_out"] = next((x["minute"] for x in subs if x["out_id"] == str(p["id"])), None)
    shots = c.get("shotmap", {}).get("shots", [])
    lineup = c.get("lineup", {})

    def key_player(side):
        cands = [p for p in players[side] if not p["gk"] and p["rating"] and p["_pts"]]
        return max(cands, key=lambda p: p["rating"]) if cands else None

    ws = ws_analysis.load(f.parent, g["matchId"])
    struct = {s_: ws_analysis.team_analysis(ws, s_) for s_ in ("home", "away")} if ws else None
    def gk_line(side):
        out = []
        for p in players[side]:
            if not p["gk"] or not p.get("minutes"):
                continue
            fs = flatten(pstats.get(str(p["id"]), {}))

            def v(k):
                return (fs.get(k) or (None, None))[0]
            acc = fs.get("accurate_passes") or (None, None)
            lb = fs.get("long_balls_accurate") or (None, None)
            out.append({"name": p["name"], "minutes": p["minutes"], "rating": p.get("rating"),
                        "saves": v("saves") or 0, "goals_conceded": v("goals_conceded") or 0,
                        "xgot_faced": v("expected_goals_on_target_faced"), "goals_prevented": v("goals_prevented"),
                        "errors_led_to_goal": v("errors_led_to_goal") or 0, "high_claims": v("keeper_high_claim") or 0,
                        "sweeper": v("keeper_sweeper") or 0, "punches": v("punches") or 0,
                        "passes": [acc[0], acc[1]], "long_balls": [lb[0], lb[1]]})
        return out

    potm = c.get("matchFacts", {}).get("playerOfTheMatch") or {}
    m = {
        "id": str(g["matchId"]),
        "round": g.get("matchRound"),
        "kickoff_utc": d["header"]["status"].get("utcTime"),
        "home": g["homeTeam"]["name"],
        "away": g["awayTeam"]["name"],
        "home_short": short(g["homeTeam"]["name"]),
        "away_short": short(g["awayTeam"]["name"]),
        "score": [teams[0].get("score"), teams[1].get("score")],
        "formation": [lineup.get("homeTeam", {}).get("formation"), lineup.get("awayTeam", {}).get("formation")],
        "coaches": [(lineup.get("homeTeam", {}).get("coach") or {}).get("name"),
                    (lineup.get("awayTeam", {}).get("coach") or {}).get("name")],
        "stats": stats_block(c, "All"),
        "stats_first_half": stats_block(c, "FirstHalf"),
        "stats_second_half": stats_block(c, "SecondHalf"),
        "goals": sorted(goals_list(c, home_id), key=lambda x: x["sort"]),
        "substitutions": [{k: v for k, v in x.items() if not k.endswith("_id")} for x in subs],
        "goalkeepers": {s_: gk_line(s_) for s_ in ("home", "away")},
        "red_cards": cards_list(c),
        "attacking_zones": {s: c.get("attackingZones", {}).get(s, {}).get("total") for s in ("home", "away")},
        "momentum_phases": momentum_phases(c.get("momentum", {}).get("main", {}).get("data", [])),
        "shape": {s: shape_metrics(players[s]) for s in ("home", "away")},
        "final_third_actions": {s: final_third(players[s]) for s in ("home", "away")},
        "player_of_the_match": {
            "name": (potm.get("name") or {}).get("fullName"),
            "team": potm.get("teamName"),
            "rating": (potm.get("rating") or {}).get("num"),
        },
        "insights_en": [i.get("text") for i in c.get("matchFacts", {}).get("insights", [])],
        "structure": {s_: struct[s_]["metrics"] | {
            "possession_shape": [{k: n.get(k) for k in ("name", "number", "x", "y", "n", "sub")} for n in struct[s_]["nodes"]],
            "defensive_shape": [{k: n.get(k) for k in ("name", "number", "x", "y", "n", "sub")} for n in struct[s_]["def_nodes"]],
        } for s_ in ("home", "away")} if struct else None,
        "players": players,
        "key_players": {s: key_player(s) for s in ("home", "away")},
        "_shots": {"home": [s for s in shots if s["teamId"] == home_id and not s.get("isOwnGoal")],
                   "away": [s for s in shots if s["teamId"] != home_id and not s.get("isOwnGoal")]},
        "_momentum": c.get("momentum", {}).get("main", {}).get("data", []),
    }
    m["context"] = {s_: {"habits": ctx.habits(m[s_], m["id"]), "form": ctx.form(m[s_], m["id"])}
                    for s_ in ("home", "away")}
    # données pour les graphes interactifs de la page
    m["shots_data"] = []
    for s_ in ("home", "away"):
        for sh in m["_shots"][s_]:
            kind = "but" if sh["eventType"] == "Goal" else "contré" if sh.get("isBlocked") else \
                "cadré" if sh.get("isOnTarget") else "poteau" if sh["eventType"] == "Post" else "non cadré"
            mins = f"{sh['min']}+{sh['minAdded']}'" if sh.get("minAdded") else f"{sh['min']}'"
            m["shots_data"].append({"side": s_, "x": round(sh["x"], 1), "y": round(W - sh["y"], 1),
                                    "xg": round(sh["expectedGoals"] or 0, 2), "player": sh.get("playerName"),
                                    "minute": mins, "kind": kind, "situation": sh.get("situation")})
    if struct:
        for s_ in ("home", "away"):
            by = {n["playerId"]: n for n in struct[s_]["nodes"]}
            m["structure"][s_]["pass_links"] = [{"a": by[e["a"]]["name"], "b": by[e["b"]]["name"], "n": e["n"]}
                                                for e in struct[s_]["edges"]]
            m["structure"][s_]["def_points"] = [[round(a, 1), round(b, 1)] for a, b in struct[s_]["def_points"]]
    ft = m["final_third_actions"]
    tot = (ft["home"] + ft["away"]) or 1
    m["final_third_share_pct"] = [round(100 * ft["home"] / tot), round(100 * ft["away"] / tot)]

    figs = {}
    for name, fn in (("momentum", fig_momentum), ("shots", fig_shots), ("positions", fig_positions),
                     ("heatmaps", fig_team_heatmaps)):
        if name == "momentum" and not m["_momentum"]:
            continue
        if name == "positions" and struct:
            for side in ("home", "away"):
                p = outdir / f"{m['id']}_shape_{side}.webp"
                fig_team_shape(m, side, struct[side], p)
                figs[f"shape_{side}"] = p.name
                p = outdir / f"{m['id']}_creation_{side}.webp"
                fig_creation(m, side, struct[side]["creation"], p)
                figs[f"creation_{side}"] = p.name
            continue
        p = outdir / f"{m['id']}_{name}.webp"
        fn(m, p)
        figs[name] = p.name
    if any(m["goalkeepers"][s_] for s_ in ("home", "away")):
        p = outdir / f"{m['id']}_goalkeepers.webp"
        fig_goalkeepers(m, p)
        figs["goalkeepers"] = p.name
    if all(len(m["context"][s_]["form"]) >= 2 for s_ in ("home", "away")):
        p = outdir / f"{m['id']}_form.webp"
        fig_form(m, p)
        figs["form"] = p.name
    for side in ("home", "away"):
        if m["key_players"][side]:
            p = outdir / f"{m['id']}_player_{side}.webp"
            fig_player(m, side, p)
            figs[f"player_{side}"] = p.name
    m["figures"] = figs

    # Nettoyage pour le JSON : on retire les points bruts
    def clean(p):
        return {k: v for k, v in p.items() if not k.startswith("_")} if p else None
    m["players"] = {s: [clean(p) for p in m["players"][s]] for s in ("home", "away")}
    m["key_players"] = {s: clean(m["key_players"][s]) for s in ("home", "away")}
    return {k: v for k, v in m.items() if not k.startswith("_")}


def team_of_round(matches):
    """4-3-3 des meilleures notes (60 min mini), placé selon la position moyenne des joueurs."""
    pool = {0: [], 1: [], 2: [], 3: []}
    for m in matches:
        for side in ("home", "away"):
            for p in m["players"][side]:
                if (p.get("minutes") or 0) >= 60 and p.get("rating") and p.get("role") in pool:
                    role = 0 if p["gk"] else p["role"]
                    pool[role].append({"name": p["name"], "short": p["short"], "team": m[side],
                                       "rating": p["rating"], "avg_y": p.get("avg_y") or 34, "role": role,
                                       "match_id": m["id"]})
    need = {0: 1, 1: 4, 2: 3, 3: 3}
    xs = {0: 7, 1: 28, 2: 54, 3: 83}
    xi = []
    for role, k in need.items():
        best = sorted(pool[role], key=lambda p: -p["rating"])[:k]
        if len(best) < k:
            return None
        best.sort(key=lambda p: -p["avg_y"])          # gauche en haut
        for i, p in enumerate(best):
            p["px"] = xs[role]
            p["py"] = W / 2 if k == 1 else 8 + (W - 16) * (1 - i / (k - 1))
            xi.append(p)
    return xi


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int)
    ap.add_argument("--out", default="out")
    ap.add_argument("--pending", action="store_true",
                    help="liste les journées à traiter (sans rapport ou avec des matchs nouveaux)")
    ap.add_argument("--ready", action="store_true",
                    help="avec --pending : seulement les journées dont tous les matchs ont leurs données WhoScored")
    ap.add_argument("--limit", type=int, default=0, help="avec --pending : nombre max de journées")
    ap.add_argument("--record-artifact", nargs=2, metavar=("JOURNEE", "SLUG"),
                    help="note l'artefact publié pour une journée")
    args = ap.parse_args()

    latest = max(match_files(), key=lambda f: f.name[:10])
    season_name = latest.parent.name
    if args.pending:
        rounds = {}
        for f in latest.parent.glob("*.json"):
            if f.name.endswith("_heatmap.json"):
                continue
            g = json.loads(f.read_text())["general"]
            rounds.setdefault(str(g["matchRound"]), []).append(str(g["matchId"]))
        todo = manifest.pending(season_name, rounds)
        if args.ready:
            ws_dir = DATA / "whoscored" / season_name
            miss_f = ws_dir / "_missing.json"
            miss = json.loads(miss_f.read_text()) if miss_f.exists() else {}
            todo = [r for r in todo if all((ws_dir / f"{i}_ws.json").exists() or miss.get(i, 0) >= 3
                                           for i in rounds[str(r)])]
        if args.limit:
            todo = todo[:args.limit]
        print(" ".join(map(str, todo)) if todo else "AUCUNE")
        return
    if args.record_artifact:
        manifest.record_artifact(season_name, args.record_artifact[0], args.record_artifact[1])
        print("Artefact noté")
        return

    rnd = pick_round(args.round)

    files = [f for f in match_files() if json.loads(f.read_text())["general"].get("matchRound") == rnd]
    if not files:
        raise SystemExit(f"Aucun match pour la journée {rnd}")
    outdir = ROOT / args.out / f"J{rnd}"
    outdir.mkdir(parents=True, exist_ok=True)

    cutoff = max(f.name[:10] for f in files)
    season = Season(files[0].parent, until_date=cutoff)
    ctx = SeasonContext(files[0].parent, cutoff)
    print(f"Données jusqu'au {cutoff} : {season.matches} matchs, seuil profils {season.min_minutes} min")
    matches = []
    for f in files:
        print("→", f.name)
        matches.append(build_match(f, outdir, season, ctx))
    matches.sort(key=lambda m: (m["kickoff_utc"] or "", m["home"]))

    table = ctx.table()
    for r in table:
        r["short"] = short(r["team"])
    tp = TeamProfiles(ctx)
    by_t = {r["team"]: r for r in table}
    for m in matches:
        m["matchup"] = {}
        for side in ("home", "away"):
            pr = tp.profile(m[side])
            lite = lambda rows: [{"label": r["label"], "rank": r["rank"], "value": r["value"], "decimals": r["decimals"]} for r in rows]
            m["matchup"][side] = {"rank": by_t.get(m[side], {}).get("rank"), "points": by_t.get(m[side], {}).get("points"),
                                  "forces": lite(pr["forces"]), "faiblesses": lite(pr["faiblesses"]),
                                  "matches": pr["matches"]}
    xi = team_of_round(matches)
    if xi:
        fig_team_of_round(xi, rnd, outdir / "team_of_round.webp")
    summary = {"round": int(rnd), "season": files[0].parent.name, "matches": matches,
               "data_until": cutoff, "xg_table": table, "team_of_round": xi,
               "team_of_round_figure": "team_of_round.webp" if xi else None,
               "profile_base": {"matches": season.matches, "min_minutes": season.min_minutes}}
    (outdir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"OK : {len(matches)} matchs -> {outdir}")


if __name__ == "__main__":
    main()
