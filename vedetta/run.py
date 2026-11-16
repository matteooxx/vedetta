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
from . import placetree as placetree_mod
from .skills import SkillMatcher
from .adapters import ADAPTERS  # the registry object itself, not a copy
from .adapters.base import AdapterError, normalise
from .db import source_dict
from .labels.engine import Label, RuleEngine, now_iso, score


def start_run(conn, trigger: str, seeding: bool) -> int:
    stamp = now_iso()
    cur = conn.execute(
        """INSERT INTO run (started_at, trigger, seeding, state, heartbeat_at)
           VALUES (?,?,?,'running',?)""",
        (stamp, trigger, int(seeding), stamp),
    )
    conn.commit()
    return cur.lastrowid


def finish_run(conn, run_id: int, state: str = "finished",
               error: str | None = None) -> None:
    """Close the run row out.

    Always called, including on failure: a run left marked `running` forever is
    indistinguishable from one still working, and the interface would send the reader
    back to watch nothing.
    """
    conn.execute(
        "UPDATE run SET finished_at=?, state=?, error=?, heartbeat_at=? WHERE id=?",
        (now_iso(), state, error, now_iso(), run_id))
    conn.commit()


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
    return [source_dict(r) for r in rows]


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


def poll(conn, run_id: int, source: dict, seeding: bool = False,
         reporter=None) -> tuple[str, list, str | None]:
    """Poll one source. Returns (outcome, items, note).

    The note is the third element rather than a side effect because the digest has to
    print it: a shortfall recorded only in the database is a shortfall nobody reads.
    """
    platform = source["platform"]
    adapter_cls = ADAPTERS.get(platform)
    if adapter_cls is None:
        # Worth spelling out: this is a deployment fact, not a fault at the
        # employer's end, and the two look identical in a list of errors. It
        # happened for real - the interface kept running an older image after new
        # adapters were built, so its Run Now reported fifteen "errors" that were
        # nothing of the kind.
        _record_poll(
            conn, run_id, source["id"], "error", None, None, 0,
            f"this build has no adapter for '{platform}' - the source is fine, the "
            f"running image is out of date (built with: "
            f"{', '.join(sorted(ADAPTERS))})")
        return "error", [], None

    started = time.monotonic()
    try:
        # Every adapter takes the same two arguments; those whose listing already
        # carries everything ignore them. No detail budget on a first pass: the whole
        # board has to be recorded once, or its remainder would arrive as "new"
        # tomorrow and be mailed as news when it is in fact history.
        on_progress = None
        if reporter is not None:
            employer = source["employer_name"]

            def on_progress(done, total=None, what="postings"):
                reporter.progress(employer, done, total, what)

        adapter = adapter_cls()
        items = adapter.fetch(
            source,
            known_keys=known_keys(conn, source["id"]),
            detail_budget=None if seeding else 150,
            progress=on_progress,
        )
    except AdapterError as exc:
        _record_poll(conn, run_id, source["id"], "error", exc.http_status, None,
                     int((time.monotonic() - started) * 1000), str(exc))
        _set_health(conn, source["id"], "error")
        return "error", [], None
    except Exception as exc:  # unexpected: still recorded, never swallowed
        _record_poll(conn, run_id, source["id"], "error", None, None,
                     int((time.monotonic() - started) * 1000),
                     f"{type(exc).__name__}: {exc}")
        _set_health(conn, source["id"], "error")
        return "error", [], None

    duration = int((time.monotonic() - started) * 1000)
    # `partial` sits between ok and error: the platform answered and the postings are
    # usable, but the listing was demonstrably incomplete. Both halves of that matter.
    # It is not an error, because a failure notice that is usually nothing teaches the
    # reader to skip failure notices. It is not ok either, because close_missing must
    # not retire a posting that may be absent only because the listing was short.
    note = "; ".join(adapter.notes) or None
    # `partial` turns on whether the listing can be trusted to be the whole board,
    # not on whether the adapter had something to say. A complete listing with a note
    # on it is still `ok`: marking it partial would stop this source ever closing a
    # posting, because close_missing treats partial as unhealthy - permanently, for a
    # note that recurs every run.
    if not items:
        outcome = "empty"
    elif adapter.incomplete:
        outcome = "partial"
    else:
        outcome = "ok"
    _record_poll(conn, run_id, source["id"], outcome, 200, len(items), duration,
                 None, note=note)
    _set_health(conn, source["id"], outcome)
    if note and reporter is not None:
        reporter.note(f"{source['employer_name']}: {note}")
    return outcome, items, note


def _record_poll(conn, run_id, source_id, outcome, status, count, duration, error,
                 note=None):
    conn.execute(
        """INSERT INTO source_poll (run_id, source_id, outcome, http_status,
                item_count, duration_ms, error, note)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(run_id, source_id) DO UPDATE SET
             outcome=excluded.outcome, http_status=excluded.http_status,
             item_count=excluded.item_count, duration_ms=excluded.duration_ms,
             error=excluded.error, note=excluded.note""",
        (run_id, source_id, outcome, status, count, duration, error, note),
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

    # Neither of the two returns below is silent: the caller notes every item that
    # comes back without a posting on the poll, saying which of the two it was.
    if item.resighting:
        # Declared "still there, not re-read" - but rule 1 found no record of the key.
        # known_keys comes from this same table, so this is an adapter fault. There
        # is no payload to create a posting from.
        return None, False

    if not item.title:
        # A posting the platform served without a title. It cannot be created, and
        # it is NOT a re-sighting: an empty title used to mean that, implicitly, and
        # a real new opening disappeared here without a trace.
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
    if item.resighting:
        # A minimal re-sighting: three adapters emit these for keys they already
        # know, without re-reading the posting. Hashing the empty payload would make
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
                  location: str | None = None, matcher=None,
                  employer: str | None = None, kept: list = ()) -> list:
    """Regex rules plus the profile's structured labels.

    Two independent labellers over the same posting, each carrying its own
    `produced_by`. Neither overrules the other: they accumulate as evidence.

    `kept` are rule labels relabel carries over from a body it no longer has (rule B
    in `relabel`, whose `engine` then judges only the `field: title` rules). They
    join before `track_label` and `blocked_by`, so a cluster or a gate found only in
    that body still counts; a rule the text here reproduced is not carried twice.
    Order follows `engine.rules`, as at first sight, because `blocked_by` is written
    in label order.
    """
    labels = engine.apply(text, title=title)
    if kept:
        found = {l.rule_id for l in labels}
        order: dict = {}
        for position, rule in enumerate(engine.rules):
            order.setdefault(rule.get("id"), position)
        labels = sorted(labels + [l for l in kept if l.rule_id not in found],
                        key=lambda l: order.get(l.rule_id, len(order)))
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

    # Which technologies the posting names, split by whether the reader claims them.
    # A difference, never a score: whether a gap matters is a judgement about the
    # reader's own experience and the program has no business guessing at it.
    if matcher is not None and matcher.configured:
        comparison = matcher.compare(text, employer=employer)
        conn.execute("DELETE FROM posting_skill WHERE posting_id=?", (posting_id,))
        for term in comparison["matched"]:
            conn.execute("INSERT OR IGNORE INTO posting_skill (posting_id, term, have) "
                         "VALUES (?,?,1)", (posting_id, term))
        for term in comparison["missing"]:
            conn.execute("INSERT OR IGNORE INTO posting_skill (posting_id, term, have) "
                         "VALUES (?,?,0)", (posting_id, term))

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

    `partial` counts as unhealthy here, exactly like `error`. A listing that came
    back short is the one case where a posting can be absent and still open, and the
    shortfall gives no way to tell which posting it was. Closing on it would retire
    an opening that is still live - the expensive direction to be wrong in.
    """
    healthy_employers = [r[0] for r in conn.execute(
        """SELECT DISTINCT s.employer_id
           FROM source s JOIN source_poll p ON p.source_id = s.id AND p.run_id = ?
           WHERE s.verified_on IS NOT NULL
           GROUP BY s.employer_id
           HAVING sum(CASE WHEN p.outcome IN ('error','partial')
                           THEN 1 ELSE 0 END) = 0
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


def execute(conn, config, trigger: str = "manual", force_seed: bool = False,
            reporter=None) -> dict:
    """Create a run row and carry it out."""
    sources = verified_sources(conn)
    seeding_sources = {s["id"] for s in sources
                       if force_seed or is_seeding_source(conn, s["id"])}
    seeding = bool(sources) and len(seeding_sources) == len(sources)
    run_id = start_run(conn, trigger, seeding)
    return execute_in(conn, config, run_id, reporter=reporter,
                      force_seed=force_seed)


def execute_in(conn, config, run_id: int, reporter=None,
               force_seed: bool = False, finish: bool = True) -> dict:
    """Carry out a run whose row already exists.

    Split out because the interface creates the run row first, in the request, so it
    can redirect the reader to a progress page before the work starts. Without that
    the page could not name the run it was supposed to be watching.

    `finish=False` leaves the run marked running for the caller to close. The
    interface uses it because composing and queueing the digest is part of the run:
    marked finished a moment too early, the progress page stops refreshing just
    before the digest appears, and the reader is told nothing about where it went.
    """
    sources = verified_sources(conn)
    seeding_sources = {s["id"] for s in sources
                       if force_seed or is_seeding_source(conn, s["id"])}
    seeding = bool(sources) and len(seeding_sources) == len(sources)
    conn.execute("UPDATE run SET seeding=? WHERE id=?", (int(seeding), run_id))
    conn.commit()

    engine = RuleEngine(config.rules)
    profile = config.profile
    matcher = SkillMatcher(config.profile_doc)

    report = {
        "run_id": run_id, "seeding": seeding, "polls": [], "new": [],
        "seeded": [], "excluded": [], "excluded_reasons": {},
        "closed": 0, "sources": len(sources),
        "unwatched": unwatched(conn),
    }

    for index, source in enumerate(sources, 1):
        if reporter is not None:
            reporter.source(source["employer_name"], source["platform"],
                            index, len(sources))
        outcome, items, note = poll(conn, run_id, source,
                                    seeding=source["id"] in seeding_sources,
                                    reporter=reporter)
        report["polls"].append({
            "employer": source["employer_name"], "platform": source["platform"],
            "outcome": outcome, "count": len(items), "note": note,
            "seeding": source["id"] in seeding_sources,
        })
        untitled: list[str] = []
        unknown: list[str] = []
        for item in items:
            posting_id, is_new = reconcile(conn, run_id, source, item)
            if posting_id is None:
                (unknown if item.resighting else untitled).append(item.platform_key)
                continue
            record_sighting(conn, run_id, source, posting_id, item)
            if is_new:
                # The one text this posting is judged on: what the engine and the
                # skill line read below, and what is stored for every later relabel.
                # Without a text from the adapter the title is read as the body, and
                # stored as such, so a relabel reads what first sight read.
                text, origin = ((item.text, "first-sight") if item.text
                                else (item.title, "title-fallback"))
                # Whole: a stored text shorter than the one read would be judged
                # differently. REPLACE only matters if a posting id is ever reused.
                conn.execute(
                    "INSERT OR REPLACE INTO posting_text (posting_id, text, origin, "
                    "stored_at) VALUES (?,?,?,?)", (posting_id, text, origin, now_iso()))
                labels = label_posting(conn, engine, posting_id,
                                       text, title=item.title,
                                       profile=profile, location=item.location,
                                       matcher=matcher,
                                       employer=source["employer_name"])
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
                    "skills": _skill_line(matcher, text, source["employer_name"]),
                    "workable": not blocking,
                    "blocked_by": [l.explain for l in blocking],
                })
        unplaced = _unplaced_note(untitled, unknown)
        if unplaced:
            # On the poll's own note, where the dashboard, the digest and a rebuilt
            # digest all read it. The outcome stays as it was: nothing was recorded
            # for these keys, so there is nothing close_missing could wrongly retire,
            # while `partial` would stop this employer closing anything at all.
            note = "; ".join(part for part in (note, unplaced) if part)
            conn.execute("UPDATE source_poll SET note=? WHERE run_id=? AND source_id=?",
                         (note, run_id, source["id"]))
            report["polls"][-1]["note"] = note
            if reporter is not None:
                reporter.note(f"{source['employer_name']}: {unplaced}")
        conn.commit()

    report["closed"] = close_missing(conn, run_id)
    # The location tree, rebuilt from the places this run has just written. It lives
    # beside them so the filter can never offer a hierarchy over places that are gone.
    placetree_mod.rebuild(conn)
    report["new"].sort(key=lambda p: (-p["score"], p["employer"], p["title"]))
    # Split for the digest. Both halves are reported; only the prominence differs.
    report["excluded"] = [p for p in report["new"] if not p.get("workable", True)]
    report["new"] = [p for p in report["new"] if p.get("workable", True)]
    reasons: dict[str, int] = {}
    for posting in report["excluded"]:
        for reason in posting["blocked_by"]:
            reasons[reason] = reasons.get(reason, 0) + 1
    report["excluded_reasons"] = dict(sorted(reasons.items(), key=lambda kv: -kv[1]))

    if reporter is not None:
        reporter.note(f"{len(report['new'])} new, {len(report['excluded'])} excluded, "
                      f"{len(report['seeded'])} seeded")
    if finish:
        finish_run(conn, run_id, "finished")
    return report


def _unplaced_note(untitled: list[str], unknown: list[str]) -> str | None:
    """Say what `reconcile` could not place, and which of the two cases it was.

    The distinction is the diagnosis: an untitled posting is the platform's doing, a
    re-sighting of a key with no record is the adapter's. Keys beyond the first ten
    are counted rather than listed, so one broken adapter cannot bury the digest.
    """
    def keys(found: list[str]) -> str:
        shown = ", ".join(found[:10])
        return shown + (f" and {len(found) - 10} more" if len(found) > 10 else "")

    parts = []
    if untitled:
        parts.append(f"{len(untitled)} new posting(s) served with no title - nothing "
                     f"can be recorded without one: {keys(untitled)}")
    if unknown:
        parts.append(f"{len(unknown)} posting(s) the adapter reported as already seen "
                     f"have no record on this source - an adapter fault, nothing "
                     f"recorded: {keys(unknown)}")
    return "; ".join(parts) or None


def _skill_line(matcher, text: str, employer: str | None = None) -> str | None:
    if matcher is None or not matcher.configured:
        return None
    from .skills import summarise
    return summarise(matcher.compare(text, employer=employer))


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

    A posting with a row in `posting_text` is judged again, whole, on the text first
    sight read. One without - collected before that table existed, and not rebuilt
    by `vedetta backfill-text` - has no body anywhere, and what cannot be recomputed
    is not deleted (rule B):

    1. its `rules` labels are read before anything is deleted; `profile` labels are
       never kept, they come from the title and location, which are there;
    2. the profile and the `field: title` rules are judged on the title. A rule that
       reads the body (no `field`, or anything but `title`) is not judged at all:
       its stored verdict stands, absence included. On the title alone an `unless`
       loses the body it was written for, so the rule would add a gate the body had
       lifted - and the live `language-gate` is in `exclude_if`, so that hides the
       posting. The price: a body rule added or changed since does not reach these
       postings, in either direction. "Stored" is not always first sight: a relabel
       from before P4 may have judged them on the title alone, and what it wrote
       stays;
    3. a label from point 1 is kept while its rule still exists and reads the body -
       worded as the rule is now, with only `value` from the old row;
    4. `no-target-track`, `blocked_by` and `workable` are decided on 2 and 3 together,
       or a cluster found only in the body would hand the posting `no-target-track`;
    5. its skills are left as they are: no matcher, so nothing deleted or added;
    6. it is counted, as `without_text`, so the reader is told how many.
    """
    engine = RuleEngine(config.rules)
    profile = config.profile
    matcher = SkillMatcher(config.profile_doc)
    # The rules a kept label may come from. `field` defaults to `all`, and a field the
    # engine does not know reads `all` too (engine.py:102): only `title` is not body.
    body_rules: dict[str, dict] = {}
    for rule in engine.rules:
        if rule.get("id") and rule.get("field", "all") != "title":
            body_rules.setdefault(rule["id"], rule)
    # Point 2: the same rules in the same order, the body ones reduced to their id. A
    # rule with no `when` and no `extract` never fires (engine.py:109-113), and the
    # id keeps its place: label_posting sorts `kept` into rules.yaml order, and
    # `blocked_by` is written in label order.
    title_engine = RuleEngine({**config.rules, "rules": [
        rule if rule.get("field") == "title" else {"id": rule.get("id")}
        for rule in engine.rules]})
    # Ids first and texts one at a time: this loop writes to `posting`, which an open
    # SELECT over it should not be reading at the same time.
    rows = conn.execute(
        """SELECT p.id, p.title, p.location, e.display_name AS employer
           FROM posting p JOIN employer e ON e.id = p.employer_id
           ORDER BY p.id""").fetchall()

    stats = {"postings": 0, "workable": 0, "excluded": 0, "without_text": 0}
    for row in rows:
        stored = conn.execute("SELECT text FROM posting_text WHERE posting_id=?",
                              (row["id"],)).fetchone()
        if stored is not None:
            conn.execute("DELETE FROM label WHERE posting_id=?", (row["id"],))
            labels = label_posting(conn, engine, row["id"], stored[0],
                                   title=row["title"], profile=profile,
                                   location=row["location"], matcher=matcher,
                                   employer=row["employer"])
        else:
            old = conn.execute(                                          # 1
                "SELECT rule_id, value FROM label "
                "WHERE posting_id=? AND produced_by='rules'", (row["id"],)).fetchall()
            kept = [_kept_label(body_rules[r["rule_id"]], r["value"])   # 3
                    for r in old if r["rule_id"] in body_rules]
            conn.execute("DELETE FROM label WHERE posting_id=?", (row["id"],))
            labels = label_posting(conn, title_engine, row["id"], row["title"],  # 2, 4
                                   title=row["title"], profile=profile,
                                   location=row["location"], matcher=None,  # 5
                                   employer=row["employer"], kept=kept)
            stats["without_text"] += 1                                    # 6
        stats["postings"] += 1
        if profile.configured and profile.blocked_by(labels):
            stats["excluded"] += 1
        else:
            stats["workable"] += 1
    conn.commit()
    stats["places"] = placetree_mod.rebuild(conn)
    return stats


def _kept_label(rule: dict, value: str | None) -> Label:
    """A label carried over from a body that is gone, worded as its rule is now.

    The defaults are RuleEngine's (engine.py:121-123 for `when`, :164-166 for
    `extract`): a kept label must read exactly as the engine would have written it.
    """
    numeric = bool(rule.get("extract"))
    return Label(rule_id=rule["id"],
                 kind=rule.get("kind", "gate" if numeric else "note"),
                 severity=rule.get("severity", "warning" if numeric else "info"),
                 explain=rule.get("explain", rule["id"]),
                 value=value, weight=rule.get("weight"))
