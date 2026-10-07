"""Signals derived from what has already been collected.

Nothing here fetches anything. Every figure is a query over `sighting`, `posting` and
`source_poll` — tables that exist because the watch has to be auditable, and which
turn out to answer questions the operator was answering from memory.

Three signals, each of which is invisible in a list of postings:

**Who is actually hiring.** An employer that went from four open roles to nineteen in
a month is a different prospect from one that has had the same six for a year.

**Reposts.** A role that closed and came back under a new identifier — pointed, when
it is one the reader was rejected for.

**Staleness.** A posting open for months is usually a pipeline, whatever it calls
itself.

All three are reported as observations. None of them hides a posting or changes a
score: they are context for a human, which is the whole posture of this project.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

STALE_DAYS = 90


def _today() -> date:
    return datetime.now(timezone.utc).date()


# --------------------------------------------------------------- employer activity

def employer_activity(conn, weeks: int = 8) -> list[dict]:
    """Open postings per employer now, and how that has moved.

    Counted from `first_seen_run` against the run's own timestamp rather than from
    `published_at`: the platforms disagree about what a publication date means, and
    several do not supply one, but the run clock is ours and is consistent.
    """
    since = (_today() - timedelta(weeks=weeks)).isoformat()
    rows = conn.execute(
        """
        SELECT e.id, e.key, e.display_name,
               sum(CASE WHEN p.closed_run IS NULL THEN 1 ELSE 0 END) AS open_now,
               sum(CASE WHEN p.closed_run IS NULL AND p.workable = 1 THEN 1 ELSE 0 END)
                 AS open_workable,
               sum(CASE WHEN r.started_at >= ? THEN 1 ELSE 0 END) AS appeared,
               sum(CASE WHEN p.closed_run IS NOT NULL AND c.started_at >= ? THEN 1 ELSE 0 END)
                 AS closed
        FROM posting p
        JOIN employer e ON e.id = p.employer_id
        JOIN run r ON r.id = p.first_seen_run
        LEFT JOIN run c ON c.id = p.closed_run
        GROUP BY e.id
        ORDER BY appeared DESC, open_workable DESC, e.display_name
        """,
        (since, since),
    ).fetchall()

    out = []
    for row in rows:
        item = dict(row)
        # Net movement over the window. Positive means the board grew.
        item["net"] = (item["appeared"] or 0) - (item["closed"] or 0)
        out.append(item)
    return out


def activity_window(weeks: int = 8) -> dict:
    return {"weeks": weeks,
            "since": (_today() - timedelta(weeks=weeks)).isoformat()}


# ------------------------------------------------------------------------ reposts

def reposts(conn, limit: int = 40) -> list[dict]:
    """Postings that look like a role coming back after closing.

    Matched on employer plus normalised title, which is the same conservative
    normalisation reconciliation uses — gender tags and bracketed suffixes stripped,
    nothing clever. A pair is only reported when the new one was first seen *after*
    the old one closed, so two concurrent listings of the same role are a duplicate
    (already flagged elsewhere) rather than a repost.

    The interesting case is a role the reader was rejected for reappearing, so the
    old posting's triage state is carried along.
    """
    rows = conn.execute(
        """
        SELECT new.id AS posting_id, new.title, new.location, new.url,
               e.display_name AS employer,
               old.id AS previous_id,
               oldrun.started_at AS closed_at,
               newrun.started_at AS reappeared_at,
               (SELECT state FROM triage t WHERE t.posting_id = old.id) AS previous_triage
        FROM posting new
        JOIN posting old
          ON old.employer_id = new.employer_id
         AND old.title_norm = new.title_norm
         AND old.id <> new.id
         AND old.closed_run IS NOT NULL
        JOIN run oldrun ON oldrun.id = old.closed_run
        JOIN run newrun ON newrun.id = new.first_seen_run
        JOIN employer e ON e.id = new.employer_id
        WHERE new.closed_run IS NULL
          AND newrun.started_at > oldrun.started_at
        ORDER BY newrun.started_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------- staleness

def stale(conn, days: int = STALE_DAYS, limit: int = 60) -> list[dict]:
    """Postings open far longer than a vacancy normally lasts.

    Reported, never hidden: a long-open posting may be a pipeline, a hard-to-fill
    role, or an employer that forgets to close things. The reader can tell those
    apart and the program cannot.
    """
    cutoff = (_today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """
        SELECT p.id AS posting_id, p.title, p.location, p.url, p.is_pipeline,
               p.workable, e.display_name AS employer,
               r.started_at AS first_seen_at,
               (SELECT state FROM triage t WHERE t.posting_id = p.id) AS triage
        FROM posting p
        JOIN employer e ON e.id = p.employer_id
        JOIN run r ON r.id = p.first_seen_run
        WHERE p.closed_run IS NULL
          AND r.started_at < ?
        ORDER BY r.started_at
        LIMIT ?
        """,
        (cutoff, limit),
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["days_open"] = _days_since(item["first_seen_at"])
        out.append(item)
    return out


def _days_since(stamp: str | None) -> int | None:
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when).days


# ------------------------------------------------------------------------ summary

def summary(conn, weeks: int = 8, stale_days: int = STALE_DAYS) -> dict:
    """Everything the insights page needs, in one call."""
    activity = employer_activity(conn, weeks)
    return {
        "window": activity_window(weeks),
        "activity": activity,
        "growing": [a for a in activity if a["net"] > 0][:12],
        "quiet": [a for a in activity
                  if a["appeared"] == 0 and a["open_now"] > 0][:12],
        "reposts": reposts(conn),
        "stale": stale(conn, stale_days),
        "stale_days": stale_days,
    }
