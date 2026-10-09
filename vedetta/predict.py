"""What a configuration change would do, worked out before it is saved.

Editing these files changes how every posting is judged, which is the most dangerous
kind of change here: it can fold away a posting the reader would have taken, and an
exclusion is silent by nature. So the editor offers a Check that answers the only
question worth asking first - **what would this do to the postings I already have?**

It earned its place before it had a button. The run that introduced region rules was
predicted against the live database first, and that prediction found five defects the
test suite had passed, including a two-letter region name matching as a substring
inside "Eusebio, Ceara, Brazil" and making a Brazilian posting acceptable. Tests check
the cases somebody thought of; a prediction checks the data the change will meet.

Nothing here writes anything.
"""
from __future__ import annotations

from collections import Counter

from .labels.engine import RuleEngine
from .profile import Profile

BUCKETS = ("preferred", "acceptable", "conditional", "excluded", "unknown")
WORKABLE = ("preferred", "acceptable", "conditional")
SAMPLE = 8


def _postings(conn):
    return conn.execute(
        "SELECT id, title, location FROM posting WHERE closed_run IS NULL").fetchall()


def profile_effect(conn, current: Profile, candidate: Profile) -> dict:
    """How the candidate profile judges the open postings, against the saved one.

    The table that matters is `lost`: postings that would stop being workable. That
    is the expensive direction, so they are listed individually with the rule that
    decided each one, rather than summarised into a number.
    """
    before: Counter = Counter()
    after: Counter = Counter()
    moves: Counter = Counter()
    lost: list[dict] = []
    gained: list[dict] = []

    rows = _postings(conn)
    for row in rows:
        old, old_hit = current.location_verdict(row["location"])
        new, new_hit = candidate.location_verdict(row["location"])
        before[old] += 1
        after[new] += 1
        if old == new:
            continue
        moves[f"{old} to {new}"] += 1
        move = {"title": row["title"], "location": row["location"],
                "was": old, "was_why": old_hit, "now": new, "now_why": new_hit}
        if old in WORKABLE and new not in WORKABLE:
            lost.append(move)
        elif old not in WORKABLE and new in WORKABLE:
            gained.append(move)

    return {
        "kind": "profile",
        "postings": len(rows),
        "before": {b: before[b] for b in BUCKETS},
        "after": {b: after[b] for b in BUCKETS},
        "moves": moves.most_common(),
        "lost": _trim(lost),
        "lost_total": len(lost),
        "gained": _trim(gained),
        "gained_total": len(gained),
    }


def _trim(moves: list[dict]) -> list[dict]:
    """A few examples, one per distinct location, newest reason first."""
    seen = set()
    out = []
    for move in moves:
        key = (str(move["location"])[:40], move["now_why"])
        if key in seen:
            continue
        seen.add(key)
        out.append(move)
        if len(out) >= SAMPLE:
            break
    return out


def rules_effect(conn, current: dict, candidate: dict) -> dict:
    """Which rules were added, removed or changed, and what the new ones match.

    Matched against TITLES only. A cluster rule is written against the title anyway,
    and reading every stored advert would turn a button press into a minute's wait -
    which is how a check stops being used.
    """
    old_rules = {r.get("id"): r for r in (current.get("rules") or []) if r.get("id")}
    new_rules = {r.get("id"): r for r in (candidate.get("rules") or []) if r.get("id")}

    added = [rid for rid in new_rules if rid not in old_rules]
    removed = [rid for rid in old_rules if rid not in new_rules]
    changed = [rid for rid in new_rules
               if rid in old_rules and new_rules[rid] != old_rules[rid]]

    titles = [row["title"] or "" for row in _postings(conn)]
    hits = []
    for rid in added + changed:
        engine = RuleEngine({"profile": candidate.get("profile") or {},
                             "rules": [new_rules[rid]]})
        n = sum(1 for title in titles if engine.apply(title, title=title))
        hits.append({"id": rid, "n": n,
                     "explain": new_rules[rid].get("explain") or rid,
                     "state": "new" if rid in added else "changed"})
    hits.sort(key=lambda h: -h["n"])

    return {
        "kind": "rules",
        "postings": len(titles),
        "added": added, "removed": removed, "changed": changed,
        "hits": hits,
    }


def settings_effect(current: dict, candidate: dict) -> dict:
    """Which settings differ, by key path. No postings are involved."""
    from .configstore import key_paths

    def flat(doc):
        out = {}
        for path in key_paths(doc):
            node = doc
            ok = True
            for step in path.split("."):
                if isinstance(node, dict) and step in node:
                    node = node[step]
                else:
                    ok = False
                    break
            if ok and not isinstance(node, (dict, list)):
                out[path] = node
        return out

    old, new = flat(current), flat(candidate)
    changes = []
    for path in sorted(set(old) | set(new)):
        if old.get(path) != new.get(path):
            changes.append({"key": path, "was": old.get(path), "now": new.get(path)})
    return {"kind": "settings", "changes": changes}
