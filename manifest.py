"""Registre des rapports déjà produits : reports/<saison>/manifest.json

{"10": {"matches": ["5795505", ...], "generated_at": "...", "artifact": "<slug>"},
 "3":  {"skipped": true}}
"""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def path(season):
    return ROOT / "reports" / season / "manifest.json"


def load(season):
    p = path(season)
    return json.loads(p.read_text()) if p.exists() else {}


def save(season, data):
    p = path(season)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dict(sorted(data.items(), key=lambda kv: int(kv[0]))), indent=1))


def record_report(season, rnd, match_ids):
    data = load(season)
    entry = data.get(str(rnd), {})
    entry.pop("skipped", None)
    entry["matches"] = sorted(match_ids)
    entry["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data[str(rnd)] = entry
    save(season, data)


def record_artifact(season, rnd, slug, url=None):
    data = load(season)
    e = data.setdefault(str(rnd), {})
    e["artifact"] = slug
    if url:
        e["url"] = url
    save(season, data)


def artifact_url(season, rnd):
    return load(season).get(str(rnd), {}).get("url")


def pending(season, rounds_to_ids):
    """Journées sans rapport, ou dont des matchs ont été ajoutés depuis le rapport."""
    data = load(season)
    out = []
    for rnd, ids in sorted(rounds_to_ids.items(), key=lambda kv: int(kv[0])):
        e = data.get(str(rnd))
        if e is None:
            out.append(int(rnd))
        elif not e.get("skipped") and set(ids) - set(e.get("matches", [])):
            out.append(int(rnd))
    return out
