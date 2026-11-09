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

from profiles import Season, match_highlights  # noqa: E402

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
    if arg:
        return str(arg)
    latest = DATA / "latest.json"
    if latest.exists():
        rounds = [m.get("round") for m in json.loads(latest.read_text())["matches"]]
        rounds = [int(r) for r in rounds if str(r).isdigit()]
        if rounds:
            return str(max(rounds))
    rounds = [int(json.loads(f.read_text())["general"]["matchRound"]) for f in match_files()]
    return str(max(rounds))


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
        for p in m["players"][side]:
            if not p["starter"] or p["avg_x"] is None:
                continue
            x, y = p["avg_x"], p["avg_y"]
            if side == "away":
                x, y = L - x, W - y
            pitch.scatter(x, y, s=330, ax=ax, facecolor=color, edgecolor=SURFACE, linewidth=2, zorder=4)
            ax.text(x, y, str(p["number"]), ha="center", va="center", fontsize=10.5,
                    fontweight="bold", color="white", zorder=5)
    ax.text(L - 1, W + 4.2, f"{short(m['home'])} ({m['formation'][0]}) →", ha="right",
            va="center", fontsize=11.5, color=HOME, fontweight="bold")
    ax.text(1, W + 4.2, f"← {short(m['away'])} ({m['formation'][1]})", ha="left",
            va="center", fontsize=11.5, color=AWAY, fontweight="bold")
    save(fig, path)


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
    ax.text(0, W + 4.4, title, ha="left", va="center", fontsize=12.5, fontweight="bold", color=color)
    ax.text(L, W + 4.4, subtitle, ha="right", va="center", fontsize=10.5, color=MUTED)


def fig_team_heatmaps(m, path):
    pitch = new_pitch(pad_top=8, pad_bottom=1)
    fig, axes = plt.subplots(2, 1, figsize=(FW, FW * 1.42))
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
    fig = plt.figure(figsize=(FW, FW * 0.74 + 0.43 * n + 0.6))
    gs = fig.add_gridspec(2, 1, height_ratios=[FW * 0.74, 0.43 * n + 0.6], hspace=0.12)
    ax = fig.add_subplot(gs[0])
    pitch = new_pitch(pad_top=8, pad_bottom=1)
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
                f"Profil indicatif : seulement {prof['minutes']} min jouées cette saison")
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
def build_match(f, outdir, season):
    d, heat = load_match(f)
    g, c = d["general"], d["content"]
    home_id = g["homeTeam"]["id"]
    teams = d["header"]["teams"]
    players = team_players(c, heat, home_id)
    pstats = c.get("playerStats") or {}
    for side in ("home", "away"):
        for p in players[side]:
            p["profile"] = season.profile(p["id"])
            p["match_highlights"] = match_highlights(pstats.get(str(p["id"]), {}))
    shots = c.get("shotmap", {}).get("shots", [])
    lineup = c.get("lineup", {})

    def key_player(side):
        cands = [p for p in players[side] if not p["gk"] and p["rating"] and p["_pts"]]
        return max(cands, key=lambda p: p["rating"]) if cands else None

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
        "players": players,
        "key_players": {s: key_player(s) for s in ("home", "away")},
        "_shots": {"home": [s for s in shots if s["teamId"] == home_id and not s.get("isOwnGoal")],
                   "away": [s for s in shots if s["teamId"] != home_id and not s.get("isOwnGoal")]},
        "_momentum": c.get("momentum", {}).get("main", {}).get("data", []),
    }
    ft = m["final_third_actions"]
    tot = (ft["home"] + ft["away"]) or 1
    m["final_third_share_pct"] = [round(100 * ft["home"] / tot), round(100 * ft["away"] / tot)]

    figs = {}
    for name, fn in (("momentum", fig_momentum), ("shots", fig_shots), ("positions", fig_positions),
                     ("heatmaps", fig_team_heatmaps)):
        if name == "momentum" and not m["_momentum"]:
            continue
        p = outdir / f"{m['id']}_{name}.webp"
        fn(m, p)
        figs[name] = p.name
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int)
    ap.add_argument("--out", default="out")
    args = ap.parse_args()
    rnd = pick_round(args.round)

    files = [f for f in match_files() if json.loads(f.read_text())["general"].get("matchRound") == rnd]
    if not files:
        raise SystemExit(f"Aucun match pour la journée {rnd}")
    outdir = ROOT / args.out / f"J{rnd}"
    outdir.mkdir(parents=True, exist_ok=True)

    season = Season(files[0].parent)
    print(f"Base de comparaison : {season.matches} matchs, seuil {season.min_minutes} min")
    matches = []
    for f in files:
        print("→", f.name)
        matches.append(build_match(f, outdir, season))
    matches.sort(key=lambda m: (m["kickoff_utc"] or "", m["home"]))

    summary = {"round": int(rnd), "season": files[0].parent.name, "matches": matches,
               "profile_base": {"matches": season.matches, "min_minutes": season.min_minutes}}
    (outdir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"OK : {len(matches)} matchs -> {outdir}")


if __name__ == "__main__":
    main()
