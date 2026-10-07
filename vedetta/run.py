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

from . import places as places_mod
from .adapters.base import AdapterError, normalise
from .adapters.greenhouse import GreenhouseAdapter
from .adapters.sitemap import SitemapAdapter
from .adapters.smartrecruiters import SmartRecruitersAdapter
from .adapters.workday import WorkdayAdapter
from .labels.engine import RuleEngine, now_iso, score

ADAPTERS = {
    GreenhouseAdapter.platform: GreenhouseAdapter,
    SitemapAdapter.platform: SitemapAdapter,
    SmartRecruitersAdapter.platform: SmartRecruitersAdapter,
    WorkdayAdapter.platform: WorkdayAdapter,
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


def known_keys(conn, source_id: int) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT DISTINCT platform_key FROM sighting WHERE source_id=?", (source_id,))}


def poll(conn, run_id: int, source: dict, seeding: bool = False) -> tuple[str, list]:
    platform = source["platform"]
    adapter_cls = ADAPTERS.get(platform)
    if adapter_cls is None:
        _record_poll(conn, run_id, source["id"], "error", None, None, 0,
                     f"no adapter for platform '{platform}'")
        return "error", []

    started = time.monotonic()
    try:
        # Every adapter takes the same two arguments; those whose listing already
        # carries everything ignore them. No detail budget on a first pass: the whole
        # board has to be recorded once, or its remainder would arrive as "new"
        # tomorrow and be mailed as news when it is in fact history.
        items = adapter_cls().fetch(
            source,
            known_keys=known_keys(conn, source["id"]),
            detail_budget=None if seeding else 150,
        )
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

    if not item.title:
        # A re-sighting with no payload (the sitemap adapter emits these for URLs it
        # already knows). There is nothing to reconcile and nothing to create.
        return None, False

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
    digest = item.content_hash()
    if not item.title:
        # A minimal re-sighting: the sitemap adapter emits these for URLs it already
        # knows, without re-reading the page. Hashing the empty payload would make
        # every one of them look edited the moment edit detection exists, so the
        # previous hash is carried forward instead.
        previous = conn.execute(
            """SELECT content_hash FROM sighting
               WHERE source_id=? AND platform_key=? ORDER BY id DESC LIMIT 1""",
            (source["id"], item.platform_key)).fetchone()
        if previous:
            digest = previous[0]
    conn.execute(
        """INSERT OR IGNORE INTO sighting (run_id, source_id, posting_id, platform_key, content_hash)
           VALUES (?,?,?,?,?)""",
        (run_id, source["id"], posting_id, item.platform_key, digest),
    )


def label_posting(conn, engine: RuleEngine, posting_id: int, text: str,
                  title: str | None = None, profile=None,
                  location: str | None = None) -> list:
    """Regex rules plus the profile's structured labels.

    Two independent labellers over the same posting, each carrying its own
    `produced_by`. Neither overrules the other: they accumulate as evidence.
    """
    labels = engine.apply(text, title=title)
    if profile is not None and profile.configured:
        labels = labels + profile.labels_for(title, location)
        track = profile.track_label(labels)
        if track is not None:
            labels = labels + [track]
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

    # Normalised places, so the location can be filtered on rather than only read.
    found, is_remote, is_hybrid = places_mod.extract(location)
    conn.execute("DELETE FROM posting_place WHERE posting_id=?", (posting_id,))
    for place in found:
        conn.execute("INSERT OR IGNORE INTO posting_place (posting_id, place) VALUES (?,?)",
                     (posting_id, place))
    conn.execute("UPDATE posting SET is_remote=?, is_hybrid=? WHERE id=?",
                 (int(is_remote), int(is_hybrid), posting_id))

    # Workability is recorded, not enforced. The posting stays in the database and
    # in the UI; it is folded out of the default view behind a visible count.
    if profile is not None and profile.configured:
        blocking = profile.blocked_by(labels)
        conn.execute(
            "UPDATE posting SET workable=?, blocked_by=? WHERE id=?",
            (0 if blocking else 1,
             "; ".join(l.explain for l in blocking) or None,
             posting_id))
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


def is_seeding_source(conn, source_id: int) -> bool:
    """True when this source has never been polled successfully before.

    Seeding is per SOURCE, not per run. The first version keyed it off whether a
    digest had ever been sent, which meant a --stdout run never left seeding mode and,
    worse, a persistent mail failure would have kept every future run silent.

    Per-source is also the correct granularity for the actual requirement: adding one
    employer to the watchlist must not produce an email with that employer's entire
    back catalogue in it, while the employers already being watched carry on normally.
    """
    row = conn.execute(
        "SELECT 1 FROM sighting WHERE source_id=? LIMIT 1", (source_id,)
    ).fetchone()
    return row is None


def execute(conn, config, trigger: str = "manual", force_seed: bool = False) -> dict:
    sources = verified_sources(conn)
    seeding_sources = {s["id"] for s in sources if force_seed or is_seeding_source(conn, s["id"])}
    seeding = bool(sources) and len(seeding_sources) == len(sources)

    run_id = start_run(conn, trigger, seeding)
    engine = RuleEngine(config.rules)
    profile = config.profile

    report = {
        "run_id": run_id, "seeding": seeding, "polls": [], "new": [],
        "seeded": [], "excluded": [], "excluded_reasons": {},
        "closed": 0, "sources": len(sources),
        "unwatched": unwatched(conn),
    }

    for source in sources:
        outcome, items = poll(conn, run_id, source,
                              seeding=source["id"] in seeding_sources)
        report["polls"].append({
            "employer": source["employer_name"], "platform": source["platform"],
            "outcome": outcome, "count": len(items),
            "seeding": source["id"] in seeding_sources,
        })
        for item in items:
            posting_id, is_new = reconcile(conn, run_id, source, item)
            if posting_id is None:
                continue
            record_sighting(conn, run_id, source, posting_id, item)
            if is_new:
                labels = label_posting(conn, engine, posting_id,
                                       item.text or item.title, title=item.title,
                                       profile=profile, location=item.location)
                # A posting from a source being seeded is recorded and labelled, but
                # kept out of the digest: it is history, not news.
                bucket = "seeded" if source["id"] in seeding_sources else "new"
                blocking = (profile.blocked_by(labels)
                            if profile is not None and profile.configured else [])
                report[bucket].append({
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
                    "workable": not blocking,
                    "blocked_by": [l.explain for l in blocking],
                })
        conn.commit()

    report["closed"] = close_missing(conn, run_id)
    report["new"].sort(key=lambda p: (-p["score"], p["employer"], p["title"]))
    # Split for the digest. Both halves are reported; only the prominence differs.
    report["excluded"] = [p for p in report["new"] if not p.get("workable", True)]
    report["new"] = [p for p in report["new"] if p.get("workable", True)]
    reasons: dict[str, int] = {}
    for posting in report["excluded"]:
        for reason in posting["blocked_by"]:
            reasons[reason] = reasons.get(reason, 0) + 1
    report["excluded_reasons"] = dict(sorted(reasons.items(), key=lambda kv: -kv[1]))

    conn.execute("UPDATE run SET finished_at=? WHERE id=?", (now_iso(), run_id))
    conn.commit()
    return report


def mark_digest_sent(conn, run_id: int) -> None:
    conn.execute("UPDATE run SET digest_sent=1 WHERE id=?", (run_id,))
    conn.commit()


def relabel(conn, config) -> dict:
    """Re-evaluate every stored posting against the current rules and profile.

    Needed because the labels are a cached judgement. Edit rules.yaml or profile.yaml
    and the postings already in the database still carry the old verdicts - which
    would mean the thing you just changed appears not to work, and a posting you just
    un-excluded stays hidden. That is the silent-failure shape again, so it gets a
    command rather than a note in the documentation.

    Triage decisions are never touched.
    """
    engine = RuleEngine(config.rules)
    profile = config.profile
    rows = conn.execute(
        "SELECT id, title, location, raw FROM posting ORDER BY id").fetchall()

    stats = {"postings": 0, "workable": 0, "excluded": 0}
    for row in rows:
        text = row["title"] or ""
        if row["raw"]:
            try:
                payload = json.loads(row["raw"])
                content = payload.get("content") or payload.get("description") or ""
                if content:
                    from .adapters.greenhouse import _unescape
                    parts = [row["title"], row["location"], _unescape(content)]
                    text = "\n".join(p for p in parts if p)
            except Exception:
                pass
        conn.execute("DELETE FROM label WHERE posting_id=?", (row["id"],))
        labels = label_posting(conn, engine, row["id"], text, title=row["title"],
                               profile=profile, location=row["location"])
        stats["postings"] += 1
        if profile.configured and profile.blocked_by(labels):
            stats["excluded"] += 1
        else:
            stats["workable"] += 1
    conn.commit()
    return stats
