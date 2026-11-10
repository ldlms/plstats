"""Fiches équipes : forces/faiblesses (rang parmi les 20), style, zones d'occupation,
couloirs, comportement selon le score, domicile/extérieur.

S'appuie sur SeasonContext (données arrêtées à une date) : aucune fuite vers la suite.
"""
import json
import re
import statistics as st
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter

L, W = 105.0, 68.0
CIRCLE = re.compile(r'cx="([\d.]+)" cy="([\d.]+)"')

# clé, libellé, catégorie, sens (high = plus c'est haut mieux c'est), décimales
PROFILE = [
    ("xg_for", "xG créés", "Attaque", "high", 2),
    ("big_chances", "Grosses occasions", "Attaque", "high", 1),
    ("xg_per_shot", "Qualité des tirs (xG par tir)", "Attaque", "high", 2),
    ("finishing", "Efficacité (buts − xG)", "Attaque", "high", 2),
    ("touches_box", "Touches dans la surface adverse", "Attaque", "high", 0),
    ("key_passes", "Passes menant à un tir", "Création", "high", 1),
    ("box_entries", "Passes dans la surface", "Création", "high", 1),
    ("fast_shots_for", "Contre-attaques (tirs < 10 s après récupération)", "Création", "high", 1),
    ("ppda", "Intensité du pressing (PPDA)", "Sans le ballon", "low", 1),
    ("high_regains", "Ballons récupérés dans le camp adverse", "Sans le ballon", "high", 1),
    ("xg_against", "xG concédés", "Défense", "low", 2),
    ("big_chances_against", "Grosses occasions concédées", "Défense", "low", 1),
    ("shots_against", "Tirs concédés", "Défense", "low", 1),
    ("fast_shots_against", "Contres subis", "Défense", "low", 1),
    ("xg_set_for", "xG sur coups de pied arrêtés", "Coups de pied arrêtés", "high", 2),
    ("xg_set_against", "xG concédés sur coups de pied arrêtés", "Coups de pied arrêtés", "low", 2),
    ("gk_prevented", "Buts évités par le gardien", "Gardien", "high", 2),
]
STYLE = [
    ("possession", "Possession", " %", 0),
    ("pass_acc", "Précision des passes dans le jeu", " %", 0),
    ("poss_height", "Hauteur du bloc avec le ballon", " m", 0),
    ("def_height", "Hauteur des actions défensives", " m", 0),
]
MIN_MATCHES = 3
BINS = (21, 14)  # cases de 5 m x ~4,9 m


def _grid(points):
    if not points:
        return None
    xs, ys = zip(*points)
    h, _, _ = np.histogram2d(xs, ys, bins=BINS, range=[[0, L], [0, W]])
    tot = h.sum()
    return h / tot if tot else None


class TeamProfiles:
    def __init__(self, ctx):
        self.ctx = ctx
        self.teams = sorted(ctx.by_team)
        self.avg = {}
        self.n = {}
        for t in self.teams:
            rows = ctx.by_team[t]
            self.avg[t] = {}
            self.n[t] = {}
            for key, *_ in PROFILE + [(k, None, None, None, None) for k, *_ in STYLE]:
                vals = [r[key] for r in rows if r.get(key) is not None]
                self.n[t][key] = len(vals)
                self.avg[t][key] = st.mean(vals) if vals else None
        self._occupation()

    # -------------------------------------------------- rangs
    def rank(self, team, key, better):
        vals = {t: self.avg[t][key] for t in self.teams
                if self.avg[t][key] is not None and self.n[t][key] >= MIN_MATCHES}
        if team not in vals:
            return None, None
        order = sorted(vals, key=lambda t: -vals[t] if better == "high" else vals[t])
        r = order.index(team) + 1
        pct = round(100 * (len(order) - r) / (len(order) - 1)) if len(order) > 1 else 50
        return r, pct

    def profile(self, team):
        rows = []
        for key, label, cat, better, dec in PROFILE:
            r, pct = self.rank(team, key, better)
            rows.append({"key": key, "label": label, "category": cat, "value": None if self.avg[team][key] is None
                         else round(self.avg[team][key], dec), "decimals": dec, "rank": r, "pct": pct,
                         "of": len([t for t in self.teams if self.n[t][key] >= MIN_MATCHES])})
        ranked = [r for r in rows if r["rank"]]
        forces = sorted([r for r in ranked if r["rank"] <= 4], key=lambda r: r["rank"])[:3]
        faibl = sorted([r for r in ranked if r["of"] and r["rank"] >= r["of"] - 3], key=lambda r: -r["rank"])[:3]
        style = []
        for key, label, unit, dec in STYLE:
            vals = {t: self.avg[t][key] for t in self.teams if self.avg[t][key] is not None and self.n[t][key] >= MIN_MATCHES}
            if team in vals:
                order = sorted(vals, key=lambda t: -vals[t])
                style.append({"label": label, "value": round(vals[team], dec), "unit": unit, "decimals": dec,
                              "rank": order.index(team) + 1, "of": len(order)})
        return {"rows": rows, "forces": forces, "faiblesses": faibl, "style": style,
                "matches": len(self.ctx.by_team[team])}

    # -------------------------------------------------- scénario, domicile/extérieur, couloirs
    def record(self, team):
        rows = self.ctx.by_team[team]

        def split(rs):
            return {"played": len(rs), "w": sum(r["result"] == "V" for r in rs), "d": sum(r["result"] == "N" for r in rs),
                    "l": sum(r["result"] == "D" for r in rs), "pts": sum(r["points"] for r in rs),
                    "xpts": round(sum(r["xpts"] for r in rs), 1), "gf": sum(r["gf"] for r in rs),
                    "ga": sum(r["ga"] for r in rs)}
        led = [r for r in rows if r.get("led")]
        trailed = [r for r in rows if r.get("trailed")]

        def zones(key):
            zs = [r[key] for r in rows if r.get(key)]
            if not zs:
                return None
            return {k: round(st.mean(z.get(k, 0) for z in zs)) for k in ("left", "center", "right")}
        return {
            "home": split([r for r in rows if r["venue"] == "D"]),
            "away": split([r for r in rows if r["venue"] == "E"]),
            "led_matches": len(led), "points_dropped_from_lead": sum(3 - r["points"] for r in led),
            "led_not_won": sum(1 for r in led if r["points"] < 3),
            "trailed_matches": len(trailed), "points_won_from_behind": sum(r["points"] for r in trailed),
            "comebacks": sum(1 for r in trailed if r["points"] > 0),
            "form": [{"result": r["result"], "opponent": r["opponent"], "gf": r["gf"], "ga": r["ga"], "venue": r["venue"]}
                     for r in rows[-5:]],
            "zones_for": zones("zones_for"), "zones_against": zones("zones_against"),
        }

    # -------------------------------------------------- zones d'occupation
    def _occupation(self):
        """Grilles d'actions avec le ballon (heatmaps FotMob) et sans (actions défensives WhoScored)."""
        poss = defaultdict(list)
        defn = defaultdict(list)
        season_dir = self.ctx.season_dir
        for f in sorted(season_dir.glob("*.json")):
            if f.name.endswith("_heatmap.json") or f.name[:10] > self.ctx.until_date:
                continue
            hm = f.with_name(f.stem + "_heatmap.json")
            if not hm.exists():
                continue
            d = json.loads(f.read_text())
            g = d["general"]
            names = {str(g["homeTeam"]["id"]): g["homeTeam"]["name"], str(g["awayTeam"]["id"]): g["awayTeam"]["name"]}
            opta = {}
            for p in (d["content"].get("playerStats") or {}).values():
                if not p.get("isGoalkeeper"):
                    opta["p" + str(p.get("optaId", "")).lstrip("p")] = names.get(str(p.get("teamId")))
            pts = defaultdict(list)
            for key, svg in json.loads(hm.read_text()).get("players", {}).items():
                team = opta.get(key)
                if team:
                    pts[team] += [(float(a), W - float(b)) for a, b in CIRCLE.findall(svg)]
            for team, p in pts.items():
                gr = _grid(p)
                if gr is not None:
                    poss[team].append(gr)
        for r in self.ctx.rows:
            gr = _grid(r.get("_def_points"))
            if gr is not None:
                defn[r["team"]].append(gr)

        def build(src):
            team_avg = {t: np.mean(v, axis=0) for t, v in src.items() if len(v) >= MIN_MATCHES}
            if not team_avg:
                return {}, None
            league = np.mean(list(team_avg.values()), axis=0)
            return team_avg, league
        self.poss_grid, self.poss_league = build(poss)
        self.def_grid, self.def_league = build(defn)

    def occupation_diff(self, team, kind="poss"):
        grids, league = (self.poss_grid, self.poss_league) if kind == "poss" else (self.def_grid, self.def_league)
        if team not in grids or league is None:
            return None
        diff = gaussian_filter(grids[team] - league, 1.0)
        return diff / max(np.abs(league).max(), 1e-9)  # en part de la case la plus fréquentée de la ligue

    def occupation_facts(self, team):
        """Faits lisibles : part des actions dans chaque tiers et couloir, vs moyenne de la ligue."""
        out = {}
        for kind, grids, league in (("poss", self.poss_grid, self.poss_league), ("def", self.def_grid, self.def_league)):
            if team not in grids or league is None:
                continue
            g = grids[team]
            nx, ny = BINS

            def share(arr, xs, ys):
                return float(arr[xs, :][:, ys].sum())
            thirds = {"défensif": slice(0, 7), "milieu": slice(7, 14), "offensif": slice(14, 21)}
            lanes = {"droite": slice(0, 5), "axe": slice(5, 9), "gauche": slice(9, 14)}
            out[kind] = {
                "thirds": {k: {"team": round(100 * share(g, v, slice(0, ny))), "league": round(100 * share(league, v, slice(0, ny)))}
                           for k, v in thirds.items()},
                "lanes": {k: {"team": round(100 * share(g, slice(0, nx), v)), "league": round(100 * share(league, slice(0, nx), v))}
                          for k, v in lanes.items()},
            }
        return out
