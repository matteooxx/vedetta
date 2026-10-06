"""One run: poll every verified source, reconcile, label, and report.

The ordering of events follows docs/data-model.md. Three details are load-bearing
and are commented where they happen:

* a poll always writes a row, so silence cannot be mistaken for "nothing new";
* a posting missing from one source while a sibling source is healthy is a
  **source fault**, not a closure;
* the first run after a watchlist change seeds silently and sends nothing.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from .adapters.base import AdapterError, normalise
from .adapters.greenhouse import GreenhouseAdapter
from .labels.engine import RuleEngine, now_iso, score

ADAPTERS = {
    GreenhouseAdapter.platform: GreenhouseAdapter,
}


def start_run(conn, trigger: str, seeding: bool) -> int:
    cur = conn.execute(
        "INSERT INTO run (started_at, trigger, seeding) VALUES (?,?,?)",
        (now_iso(), trigger, int(seeding)),
    )
    conn.commit()
    return cur.lastrowid


def verified_sources(conn) -> list[dict]:
    """Only sources a human has confirmed.

    ``verified_on IS NULL`` means never polled. This is the schema enforcing the
    enrolment rule: two independent discovery sources each returned a different
    company than the one asked for, so automatic enrolment is not available.
    """
    rows = conn.execute(
        """SELECT s.*, e.key AS employer_key, e.display_name AS employer_name,
                  e.channel AS channel
           FROM source s JOIN employer e ON e.id = s.employer_id
           WHERE s.enabled = 1 AND e.enabled = 1 AND s.verified_on IS NOT NULL
           ORDER BY e.display_name, s.platform"""
    ).fetchall()
    return [dict(r) for r in rows]


def unwatched(conn) -> list[dict]:
    """Employers with no usable route.

    Reported in the digest. An employer we cannot watch must appear as 'unwatched',
    never as 'nothing new'.
    """
    rows = conn.execute(
        """SELECT e.display_name, e.careers_url
           FROM employer e
           WHERE e.enabled = 1
             AND NOT EXISTS (
               SELECT 1 FROM source s
               WHERE s.employer_id = e.id AND s.enabled = 1
                 AND s.verified_on IS NOT NULL)
           ORDER BY e.display_name"""
    ).fetchall()
    return [dict(r) for r in rows]


def poll(conn, run_id: int, source: dict) -> tuple[str, list]:
    platform = source["platform"]
    adapter_cls = ADAPTERS.get(platform)
    if adapter_cls is None:
        _record_poll(conn, run_id, source["id"], "error", None, None, 0,
                     f"no adapter for platform '{platform}'")
        return "error", []

    started = time.monotonic()
    try:
        items = adapter_cls().fetch(source)
    except AdapterError as exc:
        _record_poll(conn, run_id, source["id"], "error", exc.http_status, None,
                     int((time.monotonic() - started) * 1000), str(exc))
        _set_health(conn, source["id"], "error")
        return "error", []
    except Exception as exc:  # unexpected: still recorded, never swallowed
        _record_poll(conn, run_id, source["id"], "error", None, None,
                     int((time.monotonic() - started) * 1000),
                     f"{type(exc).__name__}: {exc}")
        _set_health(conn, source["id"], "error")
        return "error", []

    duration = int((time.monotonic() - started) * 1000)
    outcome = "ok" if items else "empty"
    _record_poll(conn, run_id, source["id"], outcome, 200, len(items), duration, None)
    _set_health(conn, source["id"], "ok" if items else "empty")
    return outcome, items


def _record_poll(conn, run_id, source_id, outcome, status, count, duration, error):
    conn.execute(
        """INSERT INTO source_poll (run_id, source_id, outcome, http_status,
                item_count, duration_ms, error)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(run_id, source_id) DO UPDATE SET
             outcome=excluded.outcome, http_status=excluded.http_status,
             item_count=excluded.item_count, duration_ms=excluded.duration_ms,
             error=excluded.error""",
        (run_id, source_id, outcome, status, count, duration, error),
    )
    conn.commit()


def _set_health(conn, source_id, health):
    conn.execute("UPDATE source SET health=? WHERE id=?", (health, source_id))
    conn.commit()


def reconcile(conn, run_id: int, source: dict, item) -> tuple[int, bool]:
    """Return (posting_id, is_new).

    Rules in strength order, per the data model. Rule 3 -- a similar but not
    identical title -- deliberately creates a second posting flagged as a suspected
    duplicate instead of merging: a duplicate costs a glance, a wrong merge hides a
    posting.
    """
    employer_id = source["employer_id"]

    # 1. same source, same platform key
    row = conn.execute(
        """SELECT posting_id FROM sighting
           WHERE source_id=? AND platform_key=? ORDER BY id DESC LIMIT 1""",
        (source["id"], item.platform_key),
    ).fetchone()
    if row:
        posting_id = row[0]
        conn.execute("UPDATE posting SET last_seen_run=?, closed_run=NULL WHERE id=?",
                     (run_id, posting_id))
        return posting_id, False

    title_norm = normalise(item.title)
    location_norm = normalise(item.location)

    # 2. another route to the same employer, identical normalised title and location
    row = conn.execute(
        """SELECT id FROM posting
           WHERE employer_id=? AND title_norm=? AND location_norm=? AND dup_of IS NULL
           ORDER BY id LIMIT 1""",
        (employer_id, title_norm, location_norm),
    ).fetchone()
    if row:
        posting_id = row[0]
        conn.execute("UPDATE posting SET last_seen_run=?, closed_run=NULL WHERE id=?",
                     (run_id, posting_id))
        return posting_id, False

    # 3. same title, different location -> keep both, flag the newcomer
    dup_of = None
    row = conn.execute(
        """SELECT id FROM posting
           WHERE employer_id=? AND title_norm=? AND dup_of IS NULL ORDER BY id LIMIT 1""",
        (employer_id, title_norm),
    ).fetchone()
    if row:
        dup_of = row[0]

    cur = conn.execute(
        """INSERT INTO posting (employer_id, title, title_norm, location, location_norm,
                url, published_at, first_seen_run, last_seen_run, dup_of, raw)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (employer_id, item.title, title_norm, item.location, location_norm, item.url,
         item.published_at, run_id, run_id, dup_of,
         json.dumps(item.raw, ensure_ascii=False)[:200000]),
    )
    return cur.lastrowid, True


def record_sighting(conn, run_id, source, posting_id, item):
    conn.execute(
        """INSERT OR IGNORE INTO sighting (run_id, source_id, posting_id, platform_key, content_hash)
           VALUES (?,?,?,?,?)""",
        (run_id, source["id"], posting_id, item.platform_key, item.content_hash()),
    )


def label_posting(conn, engine: RuleEngine, posting_id: int, text: str,
                  title: str | None = None) -> list:
    labels = engine.apply(text, title=title)
    stamp = now_iso()
    for label in labels:
        conn.execute(
            """INSERT OR IGNORE INTO label (posting_id, rule_id, kind, severity, value,
                    explain, produced_by, confidence, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (posting_id, label.rule_id, label.kind, label.severity, label.value,
             label.explain, label.produced_by, label.confidence, stamp),
        )
    if any(l.kind == "pipeline" for l in labels):
        conn.execute("UPDATE posting SET is_pipeline=1 WHERE id=?", (posting_id,))
    return labels


def close_missing(conn, run_id: int) -> int:
    """Mark postings closed -- but only where every route for that employer is healthy.

    A posting absent from one source while a sibling source still returns data is a
    source fault, not a closure. That distinction is the whole point of polling more
    than one route (ADR-0012), so it is enforced here rather than assumed.
    """
    healthy_employers = [r[0] for r in conn.execute(
        """SELECT DISTINCT s.employer_id
           FROM source s JOIN source_poll p ON p.source_id = s.id AND p.run_id = ?
           WHERE s.verified_on IS NOT NULL
           GROUP BY s.employer_id
           HAVING sum(CASE WHEN p.outcome = 'error' THEN 1 ELSE 0 END) = 0
              AND sum(CASE WHEN p.outcome = 'ok' THEN 1 ELSE 0 END) > 0""",
        (run_id,),
    ).fetchall()]
    if not healthy_employers:
        return 0
    marks = ",".join("?" * len(healthy_employers))
    cur = conn.execute(
        f"""UPDATE posting SET closed_run=?
            WHERE closed_run IS NULL AND last_seen_run < ? AND employer_id IN ({marks})""",
        (run_id, run_id, *healthy_employers),
    )
    conn.commit()
    return cur.rowcount


def execute(conn, config, trigger: str = "manual", force_seed: bool = False) -> dict:
    sources = verified_sources(conn)
    previous_runs = conn.execute(
        "SELECT count(*) FROM run WHERE digest_sent=1").fetchone()[0]
    seeding = force_seed or previous_runs == 0

    run_id = start_run(conn, trigger, seeding)
    engine = RuleEngine(config.rules)

    report = {
        "run_id": run_id, "seeding": seeding, "polls": [], "new": [],
        "closed": 0, "sources": len(sources),
        "unwatched": unwatched(conn),
    }

    for source in sources:
        outcome, items = poll(conn, run_id, source)
        report["polls"].append({
            "employer": source["employer_name"], "platform": source["platform"],
            "outcome": outcome, "count": len(items),
        })
        for item in items:
            posting_id, is_new = reconcile(conn, run_id, source, item)
            record_sighting(conn, run_id, source, posting_id, item)
            if is_new:
                labels = label_posting(conn, engine, posting_id,
                                       item.text or item.title, title=item.title)
                report["new"].append({
                    "posting_id": posting_id,
                    "employer": source["employer_name"],
                    "channel": source["channel"],
                    "title": item.title,
                    "location": item.location,
                    "url": item.url,
                    "published_at": item.published_at,
                    "labels": [l.__dict__ for l in labels],
                    "score": score(labels, (config.settings.get("ranking") or {}).get("weights")),
                    "platform": source["platform"],
                })
        conn.commit()

    report["closed"] = close_missing(conn, run_id)
    report["new"].sort(key=lambda p: (-p["score"], p["employer"], p["title"]))

    conn.execute("UPDATE run SET finished_at=? WHERE id=?", (now_iso(), run_id))
    conn.commit()
    return report


def mark_digest_sent(conn, run_id: int) -> None:
    conn.execute("UPDATE run SET digest_sent=1 WHERE id=?", (run_id,))
    conn.commit()
