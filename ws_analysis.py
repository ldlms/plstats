"""Analyse des événements WhoScored (Opta) : structure avec et sans ballon.

Coordonnées WhoScored : x, y de 0 à 100, chaque équipe attaque vers x = 100,
y = 0 côté droit, y = 100 côté gauche. Converties en mètres (105 x 68), y vers le haut
(gauche en haut), comme les graphes FotMob.
"""
import json
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

L, W = 105.0, 68.0
SET_PIECES = {"CornerTaken", "FreekickTaken", "ThrowIn", "GoalKick", "IndirectFreekickTaken"}
ON_BALL = {"Pass", "BallTouch", "TakeOn", "Dispossessed", "SavedShot", "MissedShots", "Goal", "ShotOnPost"}
DEF_TYPES = {"Tackle", "Interception", "BallRecovery", "Clearance", "BlockedPass", "Challenge"}
PRESS_TYPES = {"Tackle", "Interception", "Challenge"}  # + fautes commises (PPDA)
NO_PLAYER = {"Start", "End", "FormationSet", "FormationChange", "SubstitutionOff", "SubstitutionOn",
             "CornerAwarded", "OffsideGiven", "OffsideProvoked", "Card"}


def m(x, y):
    return x * L / 100, y * W / 100


def load(season_dir: Path, fotmob_id):
    f = Path(season_dir).parent.parent / "whoscored" / Path(season_dir).name / f"{fotmob_id}_ws.json"
    return json.loads(f.read_text()) if f.exists() else None


def is_foul_committed(e):
    return e["type"] == "Foul" and e["outcome"] == "Unsuccessful"


def team_analysis(ws, side):
    team = ws[side]
    other = ws["away" if side == "home" else "home"]
    tid, oid = team["teamId"], other["teamId"]
    players = {p["playerId"]: p for p in team["players"]}
    starters = {pid for pid, p in players.items() if p.get("isFirstEleven")}
    gk = {pid for pid, p in players.items() if p.get("position") == "GK"}
    ev = [e for e in ws["events"] if e.get("x") is not None]

    # --- avec le ballon : passes réussies dans le jeu + réceptions
    seq = [e for e in ws["events"] if e.get("playerId") and e["type"] not in NO_PLAYER]
    touches = defaultdict(list)
    links = Counter()
    passes_ok = passes_all = 0
    for i, e in enumerate(seq):
        if e["teamId"] != tid or e["type"] != "Pass" or e.get("x") is None:
            continue
        if SET_PIECES & set(e.get("q") or []):
            continue
        passes_all += 1
        if e["outcome"] != "Successful":
            continue
        passes_ok += 1
        if e["playerId"] in starters:
            touches[e["playerId"]].append(m(e["x"], e["y"]))
        nxt = seq[i + 1] if i + 1 < len(seq) else None
        if nxt and nxt["teamId"] == tid and nxt["playerId"] != e["playerId"] and e.get("endX") is not None:
            r = nxt["playerId"]
            if r in starters:
                touches[r].append(m(e["endX"], e["endY"]))
            if e["playerId"] in starters and r in starters:
                links[tuple(sorted((e["playerId"], r)))] += 1

    nodes = []
    for pid in starters:
        pts = touches.get(pid, [])
        if len(pts) < 5:
            continue
        p = players[pid]
        nodes.append({"playerId": pid, "name": p["name"], "number": p.get("shirtNo"), "gk": pid in gk,
                      "x": round(st.mean(a for a, _ in pts), 1), "y": round(st.mean(b for _, b in pts), 1),
                      "n": len(pts)})
    by_id = {n["playerId"]: n for n in nodes}
    edges = [{"a": a, "b": b, "n": c} for (a, b), c in links.items() if c >= 3 and a in by_id and b in by_id]

    # --- sans le ballon : actions défensives
    def_events = [e for e in ev if e["teamId"] == tid and (e["type"] in DEF_TYPES or is_foul_committed(e))
                  and e["playerId"] not in gk]
    def_pts = [m(e["x"], e["y"]) for e in def_events]
    per_player = defaultdict(list)
    for e in def_events:
        if e["playerId"] in starters:
            per_player[e["playerId"]].append(m(e["x"], e["y"]))
    def_nodes = []
    for pid, pts in per_player.items():
        if len(pts) < 3:
            continue
        p = players[pid]
        def_nodes.append({"playerId": pid, "name": p["name"], "number": p.get("shirtNo"),
                          "x": round(st.mean(a for a, _ in pts), 1), "y": round(st.mean(b for _, b in pts), 1),
                          "n": len(pts)})

    # --- PPDA : passes adverses dans leurs 60 % / nos actions de pressing dans cette zone
    opp_passes = sum(1 for e in ev if e["teamId"] == oid and e["type"] == "Pass" and e["x"] < 60
                     and not (SET_PIECES & set(e.get("q") or [])))
    press = sum(1 for e in ev if e["teamId"] == tid and e["x"] > 40
                and (e["type"] in PRESS_TYPES or is_foul_committed(e)))
    high_regains = sum(1 for e in ev if e["teamId"] == tid and e["x"] > 50
                       and e["type"] in ("BallRecovery", "Interception")
                       or (e["teamId"] == tid and e["x"] > 50 and e["type"] == "Tackle" and e["outcome"] == "Successful"))

    def spread(ns):
        out = [n for n in ns if not n.get("gk")]
        if len(out) < 4:
            return None, None
        return (round(st.mean(n["x"] for n in out), 1),
                round(max(n["y"] for n in out) - min(n["y"] for n in out), 1))

    poss_h, poss_w = spread(nodes)
    def_h, def_w = spread(def_nodes)
    top_links = sorted(edges, key=lambda e: -e["n"])[:3]
    return {
        "team": team["name"],
        "nodes": nodes, "edges": edges, "def_points": def_pts, "def_nodes": def_nodes,
        "metrics": {
            "passes_open_play": passes_all,
            "pass_accuracy_open_play_pct": round(100 * passes_ok / passes_all) if passes_all else None,
            "possession_block_height_m": poss_h,
            "possession_width_m": poss_w,
            "defensive_block_height_m": def_h,
            "defensive_width_m": def_w,
            "defensive_actions": len(def_events),
            "defensive_actions_avg_height_m": round(st.mean(a for a, _ in def_pts), 1) if def_pts else None,
            "ppda": round(opp_passes / press, 1) if press else None,
            "high_regains": high_regains,
            "top_pass_links": [{"from": by_id[l["a"]]["name"], "to": by_id[l["b"]]["name"], "passes": l["n"]}
                               for l in top_links],
            "most_involved": max(nodes, key=lambda n: n["n"])["name"] if nodes else None,
        },
    }
