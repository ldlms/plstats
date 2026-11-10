"""Profils de joueurs sur la saison : stats par 90 minutes et centiles par poste.

Chaque joueur est comparé aux joueurs du même poste (FotMob usualPosition :
0 gardien, 1 défenseur, 2 milieu, 3 attaquant) qui ont assez joué.
"""
import json
from collections import defaultdict
from pathlib import Path

GROUP_LABEL = {0: "gardiens", 1: "défenseurs", 2: "milieux", 3: "attaquants"}


def flatten(player):
    out = {}
    for grp in player.get("stats", []):
        for v in grp.get("stats", {}).values():
            k = v.get("key")
            s = v.get("stat", {})
            if k and k not in out and s.get("value") is not None:
                out[k] = (s.get("value"), s.get("total"))
    return out


# (id, libellé, fonction(agg) -> valeur, unité, plus_haut_est_mieux, minimum de volume)
def per90(key):
    return lambda a: a["sum"][key] * 90 / a["minutes"]


def rate(key, min_att):
    def f(a):
        att = a["att"][key]
        return 100 * a["sum"][key] / att if att >= min_att else None
    return f


METRICS = {
    "npxg": ("Finition (xG hors penalty)", lambda a: (a["sum"]["npxg"]) * 90 / a["minutes"], "/90", True),
    "shots": ("Tirs", per90("total_shots"), "/90", True),
    "box": ("Présence dans la surface", per90("touches_opp_box"), "touches/90", True),
    "chances": ("Occasions créées", per90("chances_created"), "/90", True),
    "xa": ("Passes décisives attendues (xA)", per90("expected_assists"), "/90", True),
    "linebreak": ("Passes qui cassent les lignes", per90("line_breaking_passes"), "/90", True),
    "final3": ("Passes vers le dernier tiers", per90("passes_into_final_third"), "/90", True),
    "passpct": ("Précision de passe", rate("accurate_passes", 80), "%", True),
    "longpct": ("Précision longs ballons", rate("long_balls_accurate", 15), "%", True),
    "dribbles": ("Dribbles réussis", per90("dribbles_succeeded"), "/90", True),
    "tklint": ("Tacles + interceptions", lambda a: (a["sum"]["matchstats.headers.tackles"] + a["sum"]["interceptions"]) * 90 / a["minutes"], "/90", True),
    "recov": ("Ballons récupérés", per90("recoveries"), "/90", True),
    "groundpct": ("Duels au sol gagnés", rate("ground_duels_won", 12), "%", True),
    "aerial": ("Duels aériens gagnés", per90("aerials_won"), "/90", True),
    "clear": ("Dégagements", per90("clearances"), "/90", True),
    "notpast": ("Rarement dribblé", per90("dribbled_past"), "dribblé/90", False),
    "secure": ("Conservation du ballon", per90("dispossessed"), "pertes/90", False),
    "touches": ("Participation au jeu", per90("touches"), "touches/90", True),
    "distance": ("Volume de course", lambda a: a["sum"]["physical_metrics_distance_covered"] / 1000 * 90 / a["minutes"] if a["sum"]["physical_metrics_distance_covered"] else None, "km/90", True),
    "sprints": ("Sprints", lambda a: a["sum"]["physical_metrics_number_of_sprints"] * 90 / a["minutes"] if a["sum"]["physical_metrics_distance_covered"] else None, "/90", True),
    "saves": ("Arrêts", per90("saves"), "/90", True),
    "prevented": ("Buts évités", per90("goals_prevented"), "/90", True),
    "claims": ("Sorties aériennes", per90("keeper_high_claim"), "/90", True),
    "insidebox": ("Arrêts dans la surface", per90("saves_inside_box"), "/90", True),
    "sweeper": ("Sorties hors de la surface", per90("keeper_sweeper"), "/90", True),
}

BY_GROUP = {
    0: ["saves", "prevented", "insidebox", "claims", "sweeper", "passpct", "longpct", "linebreak"],
    1: ["tklint", "recov", "aerial", "groundpct", "clear", "notpast", "linebreak", "final3", "passpct", "distance"],
    2: ["linebreak", "final3", "chances", "xa", "passpct", "dribbles", "recov", "tklint", "groundpct", "distance"],
    3: ["npxg", "shots", "box", "chances", "xa", "dribbles", "final3", "groundpct", "recov", "sprints"],
}


class Season:
    def __init__(self, season_dir: Path, until_date: str = None):
        agg = defaultdict(lambda: {"minutes": 0, "apps": 0, "sum": defaultdict(float),
                                   "att": defaultdict(float), "groups": defaultdict(int)})
        self.matches = 0
        self.history = defaultdict(list)   # notes match par match
        for f in sorted(season_dir.glob("*.json")):
            if f.name.endswith("_heatmap.json") or (until_date and f.name[:10] > until_date):
                continue
            d = json.loads(f.read_text())
            self.matches += 1
            gen = d.get("general", {})
            teams_names = (gen.get("homeTeam", {}).get("name"), gen.get("awayTeam", {}).get("name"))
            for pid, p in (d.get("content", {}).get("playerStats") or {}).items():
                s = flatten(p)
                mins = (s.get("minutes_played") or (0, None))[0] or 0
                if mins <= 0:
                    continue
                a = agg[pid]
                a["name"] = p.get("name")
                a["team"] = p.get("teamName")
                rating = (s.get("rating_title") or (None, None))[0]
                opp = teams_names[1] if p.get("teamName") == teams_names[0] else teams_names[0]
                self.history[pid].append({"date": f.name[:10], "round": gen.get("matchRound"),
                                          "opponent": opp, "rating": rating, "minutes": mins})
                a["minutes"] += mins
                a["apps"] += 1
                grp = 0 if p.get("isGoalkeeper") else p.get("usualPosition")
                if grp is not None:
                    a["groups"][grp] += mins
                for k, (v, tot) in s.items():
                    if isinstance(v, (int, float)):
                        a["sum"][k] += v
                    if isinstance(tot, (int, float)):
                        a["att"][k] += tot
                np_ = s.get("expected_goals_non_penalty", s.get("expected_goals", (0, None)))[0] or 0
                a["sum"]["npxg"] += np_
        self.agg = dict(agg)
        for a in self.agg.values():
            a["group"] = max(a["groups"], key=a["groups"].get) if a["groups"] else None
        top = max((a["minutes"] for a in self.agg.values()), default=0)
        # seuil : ~35 % du temps de jeu maximal, plafonné à 450 min
        self.min_minutes = max(60, min(450, round(0.35 * top)))
        self._values = {}
        for pid, a in self.agg.items():
            if a["group"] is None:
                continue
            vals = {}
            for mid in BY_GROUP[a["group"]]:
                try:
                    vals[mid] = METRICS[mid][1](a)
                except (ZeroDivisionError, KeyError):
                    vals[mid] = None
            self._values[pid] = vals
        self._pools = defaultdict(lambda: defaultdict(list))
        for pid, vals in self._values.items():
            a = self.agg[pid]
            if a["minutes"] < self.min_minutes:
                continue
            for mid, v in vals.items():
                if v is not None:
                    self._pools[a["group"]][mid].append(v)

    def percentile(self, group, mid, v):
        pool = self._pools[group][mid]
        if v is None or len(pool) < 5:
            return None
        lower = sum(1 for x in pool if x < v)
        equal = sum(1 for x in pool if x == v)
        p = 100 * (lower + 0.5 * equal) / len(pool)
        return round(p if METRICS[mid][3] else 100 - p)

    def profile(self, player_id):
        pid = str(player_id)
        a = self.agg.get(pid)
        if not a or a["group"] is None:
            return None
        g = a["group"]
        rows = []
        for mid in BY_GROUP[g]:
            v = self._values[pid].get(mid)
            rows.append({"id": mid, "label": METRICS[mid][0], "unit": METRICS[mid][2],
                         "value": None if v is None else round(v, 2),
                         "pct": self.percentile(g, mid, v)})
        qualified = a["minutes"] >= self.min_minutes and a["apps"] >= 3
        strengths = sorted([r for r in rows if r["pct"] is not None and r["pct"] >= 80],
                           key=lambda r: -r["pct"])[:3] if qualified else []
        return {"group": g, "group_label": GROUP_LABEL[g], "minutes": a["minutes"], "apps": a["apps"],
                "history": self.history.get(pid, []),
                "similar": self.similar(pid) if qualified else [],
                "qualified": qualified, "pool_size": len(self._pools[g].get(BY_GROUP[g][0], [])),
                "rows": rows, "strengths": [{"label": r["label"], "pct": r["pct"]} for r in strengths]}


def _vector(season, pid):
    a = season.agg[pid]
    g = a["group"]
    return [season.percentile(g, mid, season._values[pid].get(mid)) or 50 for mid in BY_GROUP[g]]


def _similar(season, pid, k=3):
    a = season.agg.get(pid)
    if not a or a["group"] is None:
        return []
    me = _vector(season, pid)
    cands = []
    for other, b in season.agg.items():
        if other == pid or b["group"] != a["group"] or b["minutes"] < season.min_minutes:
            continue
        v = _vector(season, other)
        dist = sum((x - y) ** 2 for x, y in zip(me, v)) ** 0.5
        cands.append((dist, b["name"], b["team"]))
    cands.sort()
    return [{"name": n, "team": t, "distance": round(d, 1)} for d, n, t in cands[:k]]


Season.similar = lambda self, pid, k=3: _similar(self, pid, k)


def match_highlights(player):
    """Ce que le joueur a fait de marquant dans CE match (texte court)."""
    s = flatten(player)

    def v(k):
        return (s.get(k) or (0, None))[0] or 0

    out = []
    if player.get("isGoalkeeper"):
        out.append(f"{int(v('saves'))} arrêt" + ("s" if v("saves") > 1 else ""))
        if s.get("expected_goals_on_target_faced"):
            out.append(f"{v('expected_goals_on_target_faced'):.2f} xGOT subis".replace(".", ","))
        if s.get("goals_prevented"):
            gp = v("goals_prevented")
            out.append(f"{gp:+.2f} but{'s' if abs(gp) >= 2 else ''} évité{'s' if abs(gp) >= 2 else ''}".replace(".", ",").replace("-", "−"))
        if v("errors_led_to_goal"):
            out.append(f"{int(v('errors_led_to_goal'))} erreur menant à un but")
        if v("keeper_high_claim") >= 2:
            out.append(f"{int(v('keeper_high_claim'))} sorties aériennes")
        return out[:4]
    if v("goals"):
        out.append(f"{int(v('goals'))} but" + ("s" if v("goals") > 1 else ""))
    if v("assists"):
        out.append(f"{int(v('assists'))} passe" + ("s" if v("assists") > 1 else "") + " déc.")
    if v("expected_goals") >= 0.4 and not v("goals"):
        out.append(f"{v('expected_goals'):.2f} xG sans marquer".replace(".", ","))
    if v("chances_created") >= 3:
        out.append(f"{int(v('chances_created'))} occasions créées")
    if v("line_breaking_passes") >= 8:
        out.append(f"{int(v('line_breaking_passes'))} passes qui cassent les lignes")
    if v("dribbles_succeeded") >= 3:
        out.append(f"{int(v('dribbles_succeeded'))} dribbles réussis")
    ti = v("matchstats.headers.tackles") + v("interceptions")
    if ti >= 5:
        out.append(f"{int(ti)} tacles/interceptions")
    if v("recoveries") >= 8:
        out.append(f"{int(v('recoveries'))} ballons récupérés")
    if v("aerials_won") >= 5:
        out.append(f"{int(v('aerials_won'))} duels aériens gagnés")
    if v("saves") >= 4:
        out.append(f"{int(v('saves'))} arrêts")
    if v("dispossessed") >= 4:
        out.append(f"{int(v('dispossessed'))} pertes de balle")
    return out[:3]
