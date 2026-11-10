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


SHOT_TYPES = {"SavedShot", "MissedShots", "Goal", "ShotOnPost"}
RECOVERY = {"BallRecovery", "Interception"}


def channel(y):
    """Couloir à partir d'un y WhoScored (100 = gauche)."""
    return "gauche" if y > 66.7 else "droite" if y < 33.3 else "axe"


def in_box(x, y):
    return x >= 83 and 21.1 <= y <= 78.9


def tsec(e):
    return (e.get("min") or 0) * 60 + (e.get("sec") or 0)


def creation(ws, tid, players):
    """Passes clés, entrées dernier tiers / surface par couloir, tirs après récupération."""
    ev = ws["events"]
    key_passes = []
    ft = {"gauche": 0, "axe": 0, "droite": 0}
    box = {"gauche": 0, "axe": 0, "droite": 0}
    for i, e in enumerate(ev):
        if e["teamId"] != tid or e["type"] != "Pass" or e.get("x") is None or e.get("endX") is None:
            continue
        q = set(e.get("q") or [])
        if e["outcome"] == "Successful" and not (SET_PIECES & q):
            if e["x"] < 66.7 <= e["endX"]:
                ft[channel(e["endY"])] += 1
            if in_box(e["endX"], e["endY"]) and not in_box(e["x"], e["y"]):
                box[channel(e["y"])] += 1
        if q & {"KeyPass", "ShotAssist", "IntentionalGoalAssist"}:
            nxt = next((f for f in ev[i + 1:i + 12] if f["teamId"] == tid and f["type"] in SHOT_TYPES), None)
            key_passes.append({
                "x": round(e["x"] * L / 100, 1), "y": round(e["y"] * W / 100, 1),
                "endX": round(e["endX"] * L / 100, 1), "endY": round(e["endY"] * W / 100, 1),
                "assist": bool(nxt and nxt["type"] == "Goal"),
                "player": (players.get(e["playerId"]) or {}).get("name"),
                "set_piece": bool(SET_PIECES & q),
            })
    # tirs dans les 10 s qui suivent une récupération, sans passe adverse entre les deux
    fast = []
    used = set()  # un tir ne compte qu'une fois, même si plusieurs récupérations le précèdent
    for i, e in enumerate(ev):
        if e["teamId"] != tid or not (e["type"] in RECOVERY or (e["type"] == "Tackle" and e["outcome"] == "Successful")):
            continue
        t0 = tsec(e)
        for f in ev[i + 1:i + 25]:
            if f.get("period") != e.get("period") or tsec(f) - t0 > 10:
                break
            if f["teamId"] != tid and f["type"] == "Pass" and f["outcome"] == "Successful":
                break
            if f["teamId"] == tid and f["type"] in SHOT_TYPES:
                if f.get("id") in used:
                    break
                used.add(f.get("id"))
                fast.append({"min": f.get("min"), "goal": f["type"] == "Goal",
                             "player": (players.get(f["playerId"]) or {}).get("name"),
                             "recovered_at_m": round(e["x"] * L / 100, 1)})
                break
    return {
        "key_passes": key_passes,
        "final_third_entries": ft,
        "box_entries": box,
        "fast_shots": fast,
    }


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
        if e["playerId"] in players:
            touches[e["playerId"]].append(m(e["x"], e["y"]))
        nxt = seq[i + 1] if i + 1 < len(seq) else None
        if nxt and nxt["teamId"] == tid and nxt["playerId"] != e["playerId"] and e.get("endX") is not None:
            r = nxt["playerId"]
            if r in players:
                touches[r].append(m(e["endX"], e["endY"]))
            if e["playerId"] in players and r in players:
                links[tuple(sorted((e["playerId"], r)))] += 1

    nodes = []
    for pid in players:
        pts = touches.get(pid, [])
        if len(pts) < 5:
            continue
        p = players[pid]
        nodes.append({"playerId": pid, "name": p["name"], "number": p.get("shirtNo"), "gk": pid in gk,
                      "sub": pid not in starters, "sub_in": p.get("subbedInExpandedMinute"),
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
        if e["playerId"] in players:
            per_player[e["playerId"]].append(m(e["x"], e["y"]))
    def_nodes = []
    for pid, pts in per_player.items():
        if len(pts) < 3:
            continue
        p = players[pid]
        def_nodes.append({"playerId": pid, "name": p["name"], "number": p.get("shirtNo"),
                          "sub": pid not in starters,
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
        out = [n for n in ns if not n.get("gk") and not n.get("sub")]
        if len(out) < 4:
            return None, None
        return (round(st.mean(n["x"] for n in out), 1),
                round(max(n["y"] for n in out) - min(n["y"] for n in out), 1))

    poss_h, poss_w = spread(nodes)
    def_h, def_w = spread(def_nodes)
    top_links = sorted(edges, key=lambda e: -e["n"])[:3]
    cr = creation(ws, tid, players)
    return {
        "creation": cr,
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
            "subs_in_shape": [n["name"] for n in nodes if n["sub"]],
            "key_passes": len(cr["key_passes"]),
            "final_third_entries": cr["final_third_entries"],
            "box_entries": cr["box_entries"],
            "box_entries_total": sum(cr["box_entries"].values()),
            "shots_after_regain_10s": len(cr["fast_shots"]),
            "goals_after_regain_10s": sum(1 for f in cr["fast_shots"] if f["goal"]),
            "fast_shots": cr["fast_shots"],
        },
    }


# ====================================================================== phases et scénario
def fh_offset(ws):
    """Minutes de temps additionnel de la 1re mi-temps (WhoScored compte les minutes « étendues »)."""
    fh = [e.get("min") or 0 for e in ws["events"] if e.get("period") == "FirstHalf"]
    return max(0, max(fh, default=44) - 44)


def expanded(e, off):
    return (e.get("min") or 0) + (off if e.get("period") == "SecondHalf" else 0)


def display_minute(exp, off):
    """Minute étendue -> minute lisible (0', 45', 63', 90+2')."""
    if exp <= 45:
        return f"{exp}'"
    if exp <= 45 + off:
        return "45'"
    real = exp - off
    return f"{real}'" if real <= 90 else f"90+{real - 90}'"


def fotmob_expanded(minute, added, off):
    """Minute FotMob (+ temps additionnel) -> minute étendue WhoScored."""
    minute = minute or 0
    added = added or 0
    if minute <= 45:
        return minute + added
    return minute + off + added


def _phase_cuts(team, end, min_len=18, max_phases=3):
    """Coupures aux changements de composition, pondérées par leur importance
    (joueurs changés, +3 si le système change). Phases d'au moins 18 min, 3 au plus."""
    fms = sorted(team.get("formations", []), key=lambda f: f.get("startMinuteExpanded") or 0)
    cuts = []
    for prev, cur in zip(fms, fms[1:]):
        t = cur.get("startMinuteExpanded") or 0
        if t <= 0:
            continue
        a, b = set((prev.get("playerIds") or [])[:11]), set((cur.get("playerIds") or [])[:11])
        imp = len(a ^ b) / 2 + (3 if prev.get("formationName") != cur.get("formationName") else 0)
        if imp <= 0:
            continue
        if cuts and t - cuts[-1][0] < 8:
            cuts[-1][1] += imp
        else:
            cuts.append([t, imp])

    def segments(cs):
        b = [0] + [c[0] for c in cs] + [end]
        return [[b[i], b[i + 1]] for i in range(len(b) - 1)]

    while cuts:
        segs = segments(cuts)
        short = [i for i, sg in enumerate(segs) if sg[1] - sg[0] < min_len]
        if short:
            i = short[0]
            # coupures qui bordent la phase trop courte : on retire la moins importante
            cand = [k for k in (i - 1, i) if 0 <= k < len(cuts)]
            cuts.pop(min(cand, key=lambda k: cuts[k][1]))
            continue
        if len(segs) > max_phases:
            cuts.pop(min(range(len(cuts)), key=lambda k: cuts[k][1]))
            continue
        break
    return segments(cuts), fms


def _on_pitch(fms, start, end):
    """Joueurs présents au moins 40 % de la phase (11 au plus)."""
    t = defaultdict(float)
    for f in fms:
        a, b = max(start, f.get("startMinuteExpanded") or 0), min(end, f.get("endMinuteExpanded") or 0)
        if b > a:
            for pid in (f.get("playerIds") or [])[:11]:
                t[pid] += b - a
    keep = [pid for pid, v in t.items() if v >= 0.4 * (end - start)]
    return set(sorted(keep, key=lambda p: -t[p])[:11])


def _formation_label(fms, start, end):
    best, dur = None, -1
    for f in fms:
        a, b = max(start, f.get("startMinuteExpanded") or 0), min(end, f.get("endMinuteExpanded") or 0)
        if b - a > dur:
            best, dur = f.get("formationName"), b - a
    return "-".join(best) if best and best.isdigit() else best


def _shape_in_window(ws, side, lo, hi, on_pitch=None, min_touch=4, min_link=2):
    team = ws[side]
    other = ws["away" if side == "home" else "home"]
    tid, oid = team["teamId"], other["teamId"]
    players = {p["playerId"]: p for p in team["players"]}
    gk = {pid for pid, p in players.items() if p.get("position") == "GK"}
    off = fh_offset(ws)
    seq = [e for e in ws["events"] if e.get("playerId") and e["type"] not in NO_PLAYER]
    inwin = lambda e: lo <= expanded(e, off) < hi
    touches = defaultdict(list)
    links = Counter()
    team_passes = opp_passes = 0
    xs_onball = []
    for i, e in enumerate(seq):
        if not inwin(e) or e["type"] != "Pass" or e.get("x") is None or (SET_PIECES & set(e.get("q") or [])):
            continue
        if e["teamId"] == oid:
            opp_passes += 1
            continue
        if e["teamId"] != tid:
            continue
        team_passes += 1
        xs_onball.append(e["x"] * L / 100)
        if e["outcome"] != "Successful":
            continue
        ok = lambda pid: pid in players and (on_pitch is None or pid in on_pitch)
        if ok(e["playerId"]):
            touches[e["playerId"]].append(m(e["x"], e["y"]))
        nxt = seq[i + 1] if i + 1 < len(seq) else None
        if nxt and nxt["teamId"] == tid and nxt["playerId"] != e["playerId"] and e.get("endX") is not None:
            r = nxt["playerId"]
            if ok(r):
                touches[r].append(m(e["endX"], e["endY"]))
            if ok(e["playerId"]) and ok(r):
                links[tuple(sorted((e["playerId"], r)))] += 1
    nodes = []
    for pid, pts in touches.items():
        if len(pts) < min_touch:
            continue
        p = players[pid]
        nodes.append({"name": p["name"], "number": p.get("shirtNo"), "gk": pid in gk,
                      "x": round(st.mean(a for a, _ in pts), 1), "y": round(st.mean(b for _, b in pts), 1),
                      "n": len(pts), "pid": pid})
    by = {n["pid"]: n for n in nodes}
    edges = [{"a": by[a]["name"], "b": by[b]["name"], "n": c} for (a, b), c in links.items()
             if c >= min_link and a in by and b in by]
    dev = [e for e in ws["events"] if e.get("x") is not None and inwin(e) and e["teamId"] == tid
           and (e["type"] in DEF_TYPES or is_foul_committed(e)) and e["playerId"] not in gk]
    per = defaultdict(list)
    for e in dev:
        if e["playerId"] in players and (on_pitch is None or e["playerId"] in on_pitch):
            per[e["playerId"]].append(m(e["x"], e["y"]))
    dnodes = [{"name": players[pid]["name"], "number": players[pid].get("shirtNo"),
               "x": round(st.mean(a for a, _ in pts), 1), "y": round(st.mean(b for _, b in pts), 1), "n": len(pts)}
              for pid, pts in per.items() if len(pts) >= 2]
    field = [n for n in nodes if not n["gk"]]
    return {
        "nodes": [{k: v for k, v in n.items() if k != "pid"} for n in nodes], "edges": edges,
        "def_nodes": dnodes, "def_points": [[round(a, 1), round(b, 1)] for a, b in (m(e["x"], e["y"]) for e in dev)],
        "metrics": {
            "minutes": round(hi - lo),
            "pass_share_pct": round(100 * team_passes / (team_passes + opp_passes)) if team_passes + opp_passes else None,
            "possession_block_height_m": round(st.mean(n["x"] for n in field), 1) if len(field) >= 4 else None,
            "possession_width_m": round(max(n["y"] for n in field) - min(n["y"] for n in field), 1) if len(field) >= 4 else None,
            "onball_height_m": round(st.mean(xs_onball), 1) if xs_onball else None,
            "defensive_actions": len(dev),
            "defensive_actions_avg_height_m": round(st.mean(m(e["x"], e["y"])[0] for e in dev), 1) if dev else None,
        },
    }


def phases(ws, side, fotmob_shots=None, fotmob_home=True):
    """Le match découpé selon les changements de composition (2 ou 3 phases)."""
    team = ws[side]
    off = fh_offset(ws)
    end = max((expanded(e, off) for e in ws["events"]), default=95) + 1
    end = max(end, max((f.get("endMinuteExpanded") or 0 for f in team.get("formations", [])), default=0))
    segs, fms = _phase_cuts(team, end)
    players = {p["playerId"]: p for p in team["players"]}
    out = []
    prev = None
    for lo, hi in segs:
        on = _on_pitch(fms, lo, hi)
        sh = _shape_in_window(ws, side, lo, hi, on)
        if prev is not None:
            sh["entered"] = [players[p]["name"] for p in on - prev if p in players]
            sh["left"] = [players[p]["name"] for p in prev - on if p in players]
            for n in sh["nodes"]:
                n["new"] = n["name"] in sh["entered"]
            for n in sh["def_nodes"]:
                n["new"] = n["name"] in sh["entered"]
        else:
            sh["entered"], sh["left"] = [], []
        sh["from"], sh["to"] = lo, hi
        sh["label"] = f"{display_minute(lo, off)}–{'fin' if hi >= end else display_minute(hi, off)}"
        sh["formation"] = _formation_label(fms, lo, hi)
        if fotmob_shots is not None:
            sh["metrics"]["xg_for"] = round(sum(s["xg"] for s in fotmob_shots if s["side"] == side and lo <= s["exp"] < hi), 2)
            sh["metrics"]["xg_against"] = round(sum(s["xg"] for s in fotmob_shots if s["side"] != side and lo <= s["exp"] < hi), 2)
        out.append(sh)
        prev = on
    return out


def score_states(ws, side, goals_exp, fotmob_shots=None):
    """Comportement selon le score : mène / égalité / menée. goals_exp = [(minute étendue, 'home'|'away')]."""
    off = fh_offset(ws)
    end = max((expanded(e, off) for e in ws["events"]), default=95) + 1
    other = "away" if side == "home" else "home"
    pts = [0] + [g for g, _ in sorted(goals_exp)] + [end]
    score = {"home": 0, "away": 0}
    windows = defaultdict(list)
    for i in range(len(pts) - 1):
        if i > 0:
            score[sorted(goals_exp)[i - 1][1]] += 1
        d = score[side] - score[other]
        state = "mène" if d > 0 else "égalité" if d == 0 else "menée"
        if pts[i + 1] > pts[i]:
            windows[state].append((pts[i], pts[i + 1]))
    out = {}
    for state, wins in windows.items():
        mins = sum(b - a for a, b in wins)
        if mins < 8:
            continue
        agg = {"minutes": round(mins)}
        parts = [_shape_in_window(ws, side, a, b)["metrics"] for a, b in wins]
        w = [p["minutes"] or 1 for p in parts]

        def wavg(key):
            vals = [(p[key], wt) for p, wt in zip(parts, w) if p[key] is not None]
            return round(sum(v * wt for v, wt in vals) / sum(wt for _, wt in vals), 1) if vals else None
        agg["pass_share_pct"] = wavg("pass_share_pct")
        agg["onball_height_m"] = wavg("onball_height_m")
        agg["defensive_actions_avg_height_m"] = wavg("defensive_actions_avg_height_m")
        if fotmob_shots is not None:
            inw = lambda s: any(a <= s["exp"] < b for a, b in wins)
            agg["xg_for"] = round(sum(s["xg"] for s in fotmob_shots if s["side"] == side and inw(s)), 2)
            agg["xg_against"] = round(sum(s["xg"] for s in fotmob_shots if s["side"] != side and inw(s)), 2)
            agg["xg_for_per90"] = round(agg["xg_for"] * 90 / mins, 2)
            agg["xg_against_per90"] = round(agg["xg_against"] * 90 / mins, 2)
        out[state] = agg
    return out
