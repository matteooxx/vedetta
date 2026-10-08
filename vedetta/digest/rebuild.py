"""Rebuilding a run's digest from the database, after the fact.

The interface used to start runs that queued no digest. The postings were recorded
correctly, which is what makes the loss permanent by ordinary means: they are not
new any more, so no later run will mention them. 117 postings from one run and six
workable ones from another were sitting in the database, found, and unreported.

Everything the digest says about a run is still on disk - `posting.first_seen_run`
says which run saw a posting first, and the labels, places and skills were all
stored - so the report can be reassembled and sent late. Late is a great deal
better than never, and a recovery path for a digest that went missing is worth
having permanently: a lost digest is exactly the failure a reader cannot discover
by reading their digests.

One thing is reconstructed rather than recovered: a rule may override its
severity's weight, and that override is not stored on the label - only the rule
knows it. So the weights come from the rules file as it stands now. A rebuilt digest
therefore orders its postings by today's rules rather than by whatever the rules said
at the time, which for a digest a day late is the more useful of the two.

What cannot be recovered at all is `closed` - a count of postings that disappeared during
that run - because closures are recorded against the run that noticed them and
re-deriving the count would mean trusting the same reasoning twice. It is reported
as zero and the digest says the run was rebuilt, so nobody reads a rebuilt digest
as a live one.
"""
from __future__ import annotations

from ..labels.engine import Label, score


def _labels_for(conn, posting_id: int, overrides: dict) -> list[Label]:
    rows = conn.execute(
        "SELECT rule_id, kind, severity, value, explain, produced_by, confidence "
        "FROM label WHERE posting_id=? ORDER BY id", (posting_id,)).fetchall()
    return [Label(rule_id=r["rule_id"], kind=r["kind"], severity=r["severity"],
                  explain=r["explain"], value=r["value"],
                  produced_by=r["produced_by"], confidence=r["confidence"],
                  weight=overrides.get(r["rule_id"])) for r in rows]


def _skills_for(conn, posting_id: int) -> str | None:
    rows = conn.execute(
        "SELECT term, have FROM posting_skill WHERE posting_id=? ORDER BY term",
        (posting_id,)).fetchall()
    if not rows:
        return None
    have = [r["term"] for r in rows if r["have"]]
    missing = [r["term"] for r in rows if not r["have"]]
    parts = []
    if have:
        parts.append("yours: " + ", ".join(have))
    if missing:
        parts.append("theirs: " + ", ".join(missing))
    return " | ".join(parts) or None


def report_for(conn, config, run_id: int) -> dict:
    """Reassemble the report for a run that has already happened."""
    run = conn.execute("SELECT * FROM run WHERE id=?", (run_id,)).fetchone()
    if run is None:
        raise LookupError(f"no run {run_id}")

    weights = (config.settings.get("ranking") or {}).get("weights")
    # Per-rule weight overrides are not stored on a label, so they are read back
    # from the rules as they stand now. See the module docstring.
    overrides = {r["id"]: r.get("weight")
                 for r in ((config.rules or {}).get("rules") or [])
                 if r.get("id") and r.get("weight") is not None}
    postings = conn.execute(
        "SELECT p.*, e.display_name AS employer, e.channel AS channel "
        "FROM posting p JOIN employer e ON e.id = p.employer_id "
        "WHERE p.first_seen_run = ? ORDER BY e.display_name, p.title",
        (run_id,)).fetchall()

    rebuilt: list[dict] = []
    for row in postings:
        labels = _labels_for(conn, row["id"], overrides)
        # The platform that saw it, taken from the sighting rather than guessed.
        platform = conn.execute(
            "SELECT s.platform FROM sighting g JOIN source s ON s.id = g.source_id "
            "WHERE g.posting_id = ? LIMIT 1", (row["id"],)).fetchone()
        rebuilt.append({
            "posting_id": row["id"],
            "employer": row["employer"],
            "channel": row["channel"],
            "title": row["title"],
            "location": row["location"],
            "url": row["url"],
            "published_at": row["published_at"],
            "labels": [l.__dict__ for l in labels],
            "score": score(labels, weights),
            "platform": platform["platform"] if platform else "unknown",
            "skills": _skills_for(conn, row["id"]),
            "workable": bool(row["workable"]),
            # Stored as one "; "-joined string by run.label_posting, not as JSON.
            # Read back the wrong way this raised on the first real database and
            # parsed happily in a test that had written the row itself.
            "blocked_by": [part for part in
                           (row["blocked_by"] or "").split("; ") if part],
        })

    polls = conn.execute(
        "SELECT e.display_name AS employer, s.platform AS platform, "
        "       sp.outcome AS outcome, sp.item_count AS item_count "
        "FROM source_poll sp JOIN source s ON s.id = sp.source_id "
        "JOIN employer e ON e.id = s.employer_id WHERE sp.run_id = ? "
        "ORDER BY e.display_name", (run_id,)).fetchall()

    new = [p for p in rebuilt if p["workable"]]
    excluded = [p for p in rebuilt if not p["workable"]]
    new.sort(key=lambda p: (-p["score"], p["employer"], p["title"]))
    reasons: dict[str, int] = {}
    for posting in excluded:
        for reason in posting["blocked_by"]:
            reasons[reason] = reasons.get(reason, 0) + 1

    seeding = bool(run["seeding"])
    return {
        "run_id": run_id,
        "seeding": seeding,
        "rebuilt": True,
        "polls": [{"employer": p["employer"], "platform": p["platform"],
                   "outcome": p["outcome"], "count": p["item_count"] or 0,
                   "seeding": seeding} for p in polls],
        "new": [] if seeding else new,
        "seeded": rebuilt if seeding else [],
        "excluded": [] if seeding else excluded,
        "excluded_reasons": {} if seeding else dict(
            sorted(reasons.items(), key=lambda kv: -kv[1])),
        # Not recoverable, and said so rather than guessed. See the module docstring.
        "closed": 0,
        "sources": len(polls),
        "unwatched": [],
    }
