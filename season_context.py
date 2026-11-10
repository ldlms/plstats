"""Contexte saison : habitudes des équipes, forme, classement au xG.

Tout est calculé avec les matchs joués JUSQU'À une date donnée (la fin de la journée
analysée), pour qu'un rapport de rattrapage ne « connaisse » pas la suite.
"""
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

import ws_analysis

SHOT_OK = {"Goal", "AttemptSaved", "Miss", "Post"}

# (clé, libellé, unité, décimales, plus_haut_veut_dire)
HABITS = [
    ("possession", "Possession", "%", 0, None),
    ("xg_for", "xG créés", "", 2, None),
    ("xg_against", "xG concédés", "", 2, None),
    ("shots", "Tirs", "", 0, None),
    ("big_chances", "Grosses occasions", "", 0, None),
    ("touches_box", "Touches dans la surface adverse", "", 0, None),
    ("ppda", "PPDA (pressing)", "", 1, "moins de pressing"),
    ("def_height", "Hauteur des actions défensives", " m", 0, None),
    ("high_regains", "Ballons récupérés dans le camp adverse", "", 0, None),
    ("poss_height", "Hauteur du bloc avec le ballon", " m", 0, None),
    ("pass_acc", "Précision des passes dans le jeu", " %", 0, None),
    ("box_entries", "Passes dans la surface adverse", "", 0, None),
]


def goal_distribution(xgs):
    """Probabilités de 0..n buts quand chaque tir marque avec sa probabilité xG."""
    dist = [1.0]
    for p in xgs:
        p = min(max(p or 0, 0), 0.99)
        new = [0.0] * (len(dist) + 1)
        for k, v in enumerate(dist):
            new[k] += v * (1 - p)
            new[k + 1] += v * p
        dist = new
    return dist


def expected_points(xg_a, xg_b):
    da, db = goal_distribution(xg_a), goal_distribution(xg_b)
    win = sum(pa * pb for i, pa in enumerate(da) for j, pb in enumerate(db) if i > j)
    draw = sum(pa * db[i] for i, pa in enumerate(da) if i < len(db))
    return 3 * win + draw, 3 * (1 - win - draw) + draw


def num(v):
    try:
        return float(str(v).split()[0])
    except (ValueError, TypeError, IndexError):
        return None


class SeasonContext:
    def __init__(self, season_dir: Path, until_date: str):
        """until_date : 'AAAA-MM-JJ' inclus (date du dernier match de la journée)."""
        self.rows = []          # une ligne par équipe et par match
        self.season_dir = Path(season_dir)
        self.until_date = until_date
        for f in sorted(Path(season_dir).glob("*.json")):
            if f.name.endswith("_heatmap.json") or f.name[:10] > until_date:
                continue
            d = json.loads(f.read_text())
            g, c = d["general"], d["content"]
            if not d["header"]["status"].get("finished"):
                continue
            teams = d["header"]["teams"]
            score = [teams[0].get("score"), teams[1].get("score")]
            stats = {}
            for grp in c.get("stats", {}).get("Periods", {}).get("All", {}).get("stats", []):
                for s_ in grp.get("stats", []):
                    if s_.get("key") and s_.get("stats") and len(s_["stats"]) == 2:
                        stats.setdefault(s_["key"], s_["stats"])
            home_id = g["homeTeam"]["id"]
            shots = c.get("shotmap", {}).get("shots", [])
            xg_shots = {
                "home": [s_["expectedGoals"] for s_ in shots if s_["teamId"] == home_id and not s_.get("isOwnGoal")],
                "away": [s_["expectedGoals"] for s_ in shots if s_["teamId"] != home_id and not s_.get("isOwnGoal")],
            }
            xp_h, xp_a = expected_points(xg_shots["home"], xg_shots["away"])
            ws = ws_analysis.load(f.parent, g["matchId"])
            wsa = {sd: ws_analysis.team_analysis(ws, sd) for sd in ("home", "away")} if ws else None
            wsm = {sd: wsa[sd]["metrics"] for sd in ("home", "away")} if ws else None
            # scénario : a mené / a été mené
            goals_ev = [e for e in c.get("matchFacts", {}).get("events", {}).get("events", []) if e.get("type") == "Goal"]
            goals_ev.sort(key=lambda e: (e.get("time", 0), e.get("overloadTime") or 0))
            sh = sa = 0
            led = {"home": False, "away": False}
            trailed = {"home": False, "away": False}
            for e in goals_ev:
                if e.get("isHome"):
                    sh += 1
                else:
                    sa += 1
                if sh > sa:
                    led["home"], trailed["away"] = True, True
                elif sa > sh:
                    led["away"], trailed["home"] = True, True
            zones = {sd: c.get("attackingZones", {}).get(sd, {}).get("total") for sd in ("home", "away")}
            for i, side in enumerate(("home", "away")):
                o = 1 - i
                gf, ga = score[i], score[o]

                def two(key):
                    v = stats.get(key)
                    return (num(v[i]), num(v[o])) if v else (None, None)

                row = {
                    "date": f.name[:10], "match_id": str(g["matchId"]), "round": g.get("matchRound"),
                    "team": g[f"{side}Team"]["name"], "opponent": g[f"{('away', 'home')[i]}Team"]["name"],
                    "venue": "D" if side == "home" else "E", "gf": gf, "ga": ga,
                    "result": "V" if gf > ga else "N" if gf == ga else "D",
                    "points": 3 if gf > ga else 1 if gf == ga else 0,
                    "xpts": round(xp_h if side == "home" else xp_a, 2),
                    "possession": two("BallPossesion")[0],
                    "xg_for": two("expected_goals")[0], "xg_against": two("expected_goals")[1],
                    "shots": two("total_shots")[0], "big_chances": two("big_chance")[0],
                    "touches_box": two("touches_opp_box")[0],
                }
                xg_for, xg_ag = two("expected_goals")
                shots_for, shots_ag = two("total_shots")
                xgot_for, xgot_ag = two("expected_goals_on_target")
                row.update({
                    "shots_against": shots_ag, "big_chances_against": two("big_chance")[1],
                    "touches_box_against": two("touches_opp_box")[1],
                    "xg_set_for": two("expected_goals_set_play")[0], "xg_set_against": two("expected_goals_set_play")[1],
                    "xg_per_shot": round(xg_for / shots_for, 3) if xg_for is not None and shots_for else None,
                    "finishing": round(gf - xg_for, 2) if xg_for is not None else None,
                    "gk_prevented": round(xgot_ag - ga, 2) if xgot_ag is not None else None,
                    "led": led[side], "trailed": trailed[side],
                    "zones_for": zones[side], "zones_against": zones[("away", "home")[i]],
                })
                if wsm:
                    mt = wsm[side]
                    mo = wsm[("away", "home")[i]]
                    row.update({"ppda": mt["ppda"], "def_height": mt["defensive_actions_avg_height_m"],
                                "high_regains": mt["high_regains"], "poss_height": mt["possession_block_height_m"],
                                "pass_acc": mt["pass_accuracy_open_play_pct"], "box_entries": mt["box_entries_total"],
                                "key_passes": mt["key_passes"], "fast_shots_for": mt["shots_after_regain_10s"],
                                "fast_shots_against": mo["shots_after_regain_10s"],
                                "box_entries_against": mo["box_entries_total"],
                                "_def_points": wsa[side]["def_points"]})
                self.rows.append(row)
        self.by_team = defaultdict(list)
        for r in self.rows:
            self.by_team[r["team"]].append(r)
        for t in self.by_team:
            self.by_team[t].sort(key=lambda r: r["date"])

    # -------------------------------------------------- habitudes
    def habits(self, team, match_id):
        """Les écarts les plus nets entre ce match et la moyenne des matchs précédents."""
        rows = self.by_team.get(team, [])
        cur = next((r for r in rows if r["match_id"] == match_id), None)
        if not cur:
            return {"n_prev": 0, "deviations": []}
        prev = [r for r in rows if r["date"] < cur["date"]]
        out = []
        for key, label, unit, dec, _ in HABITS:
            vals = [r[key] for r in prev if r.get(key) is not None]
            v = cur.get(key)
            if v is None or len(vals) < 3:
                continue
            mean = st.mean(vals)
            sd = st.pstdev(vals)
            floor = max(abs(mean) * 0.12, {"possession": 4, "pass_acc": 3}.get(key, 0.5 if dec == 0 else 0.15))
            z = (v - mean) / max(sd, floor)
            out.append({"key": key, "label": label, "unit": unit, "decimals": dec, "value": round(v, dec),
                        "season_avg": round(mean, dec), "n": len(vals), "z": round(z, 2)})
        out = [o for o in out if abs(o["z"]) >= 1.0]
        out.sort(key=lambda o: -abs(o["z"]))
        return {"n_prev": len(prev), "deviations": out[:4]}

    # -------------------------------------------------- forme
    def form(self, team, match_id, n=5):
        rows = self.by_team.get(team, [])
        idx = next((i for i, r in enumerate(rows) if r["match_id"] == match_id), len(rows) - 1)
        last = rows[max(0, idx - n + 1): idx + 1]
        return [{k: r[k] for k in ("date", "round", "opponent", "venue", "gf", "ga", "result", "xg_for", "xg_against")}
                for r in last]

    # -------------------------------------------------- classement
    def table(self):
        agg = defaultdict(lambda: {"played": 0, "points": 0, "xpts": 0.0, "gf": 0, "ga": 0, "xgf": 0.0, "xga": 0.0})
        for r in self.rows:
            a = agg[r["team"]]
            a["played"] += 1
            a["points"] += r["points"]
            a["xpts"] += r["xpts"]
            a["gf"] += r["gf"]
            a["ga"] += r["ga"]
            a["xgf"] += r["xg_for"] or 0
            a["xga"] += r["xg_against"] or 0
        rows = []
        for team, a in agg.items():
            rows.append({"team": team, **a, "xpts": round(a["xpts"], 1), "xgf": round(a["xgf"], 1),
                         "xga": round(a["xga"], 1), "gd": a["gf"] - a["ga"],
                         "diff": round(a["points"] - a["xpts"], 1)})
        rows.sort(key=lambda r: (-r["points"], -r["gd"], -r["gf"], r["team"]))
        for i, r in enumerate(rows, 1):
            r["rank"] = i
        by_x = sorted(rows, key=lambda r: -r["xpts"])
        for i, r in enumerate(by_x, 1):
            r["xrank"] = i
        return rows
