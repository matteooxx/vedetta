"""SQLite schema and access.

The schema is the one designed in docs/data-model.md. Two properties are enforced
here rather than left to discipline:

* a source with no ``verified_on`` can never be polled, because enrolment is a
  human act (two independent discovery sources have each returned a different
  company than the one asked for);
* every poll writes a row, including on failure, so that silence is impossible.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS employer (
  id            INTEGER PRIMARY KEY,
  key           TEXT NOT NULL UNIQUE,
  display_name  TEXT NOT NULL,
  channel       TEXT NOT NULL DEFAULT 'default',
  homepage      TEXT,
  careers_url   TEXT,
  enabled       INTEGER NOT NULL DEFAULT 1,
  notes         TEXT
);

CREATE TABLE IF NOT EXISTS source (
  id              INTEGER PRIMARY KEY,
  employer_id     INTEGER NOT NULL REFERENCES employer(id) ON DELETE CASCADE,
  platform        TEXT NOT NULL,
  identifier      TEXT NOT NULL,
  endpoint        TEXT,
  job_url_pattern TEXT,
  job_url_exclude TEXT,
  discovered_by   TEXT NOT NULL DEFAULT 'config',
  evidence        TEXT,
  verified_on     TEXT,
  verified_note   TEXT,
  enabled         INTEGER NOT NULL DEFAULT 1,
  health          TEXT NOT NULL DEFAULT 'unknown',
  UNIQUE (employer_id, platform, identifier)
);

CREATE TABLE IF NOT EXISTS run (
  id          INTEGER PRIMARY KEY,
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  trigger     TEXT NOT NULL DEFAULT 'manual',
  seeding     INTEGER NOT NULL DEFAULT 0,
  digest_sent INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS source_poll (
  id          INTEGER PRIMARY KEY,
  run_id      INTEGER NOT NULL REFERENCES run(id) ON DELETE CASCADE,
  source_id   INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  outcome     TEXT NOT NULL,
  http_status INTEGER,
  item_count  INTEGER,
  duration_ms INTEGER,
  error       TEXT,
  UNIQUE (run_id, source_id)
);

CREATE TABLE IF NOT EXISTS posting (
  id             INTEGER PRIMARY KEY,
  employer_id    INTEGER NOT NULL REFERENCES employer(id) ON DELETE CASCADE,
  title          TEXT NOT NULL,
  title_norm     TEXT NOT NULL,
  location       TEXT,
  location_norm  TEXT,
  url            TEXT,
  published_at   TEXT,
  first_seen_run INTEGER NOT NULL REFERENCES run(id),
  last_seen_run  INTEGER NOT NULL REFERENCES run(id),
  closed_run     INTEGER REFERENCES run(id),
  is_pipeline    INTEGER,
  dup_of         INTEGER REFERENCES posting(id),
  -- Workability per the reader's profile. 0 means folded out of the default view,
  -- never deleted: the count is always shown and one click reveals them.
  workable       INTEGER NOT NULL DEFAULT 1,
  blocked_by     TEXT,
  is_remote      INTEGER NOT NULL DEFAULT 0,
  is_hybrid      INTEGER NOT NULL DEFAULT 0,
  raw            TEXT
);
CREATE INDEX IF NOT EXISTS posting_recon
  ON posting(employer_id, title_norm, location_norm);
CREATE INDEX IF NOT EXISTS posting_workable
  ON posting(workable, closed_run, id);

-- One row per place mentioned by a posting. A free-text location column cannot be
-- faceted, and a posting routinely names several places.
CREATE TABLE IF NOT EXISTS posting_place (
  posting_id INTEGER NOT NULL REFERENCES posting(id) ON DELETE CASCADE,
  place      TEXT NOT NULL,
  PRIMARY KEY (posting_id, place)
);
CREATE INDEX IF NOT EXISTS posting_place_place ON posting_place(place);

CREATE TABLE IF NOT EXISTS sighting (
  id           INTEGER PRIMARY KEY,
  run_id       INTEGER NOT NULL REFERENCES run(id) ON DELETE CASCADE,
  source_id    INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  posting_id   INTEGER NOT NULL REFERENCES posting(id) ON DELETE CASCADE,
  platform_key TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  UNIQUE (run_id, source_id, platform_key)
);
CREATE INDEX IF NOT EXISTS sighting_key ON sighting(source_id, platform_key);

-- Technologies a posting names, split by whether the reader claims them. Stored
-- rather than computed on the fly so the terms can be filtered on, which turns a
-- read-only observation into a way to find work.
CREATE TABLE IF NOT EXISTS posting_skill (
  posting_id INTEGER NOT NULL REFERENCES posting(id) ON DELETE CASCADE,
  term       TEXT NOT NULL,
  have       INTEGER NOT NULL,
  PRIMARY KEY (posting_id, term)
);
CREATE INDEX IF NOT EXISTS posting_skill_term ON posting_skill(term, have);

CREATE TABLE IF NOT EXISTS label (
  id          INTEGER PRIMARY KEY,
  posting_id  INTEGER NOT NULL REFERENCES posting(id) ON DELETE CASCADE,
  rule_id     TEXT NOT NULL,
  kind        TEXT NOT NULL,
  severity    TEXT NOT NULL,
  value       TEXT,
  explain     TEXT NOT NULL,
  produced_by TEXT NOT NULL,
  confidence  REAL,
  created_at  TEXT NOT NULL,
  UNIQUE (posting_id, rule_id, produced_by)
);

CREATE TABLE IF NOT EXISTS triage (
  posting_id INTEGER PRIMARY KEY REFERENCES posting(id) ON DELETE CASCADE,
  state      TEXT NOT NULL,
  note       TEXT,
  decided_at TEXT NOT NULL
);

-- Every stage change, appended and never collapsed. Moving back a stage is
-- information, and so is having cleared one: deleting either would quietly rewrite
-- the record of a search.
CREATE TABLE IF NOT EXISTS triage_event (
  id         INTEGER PRIMARY KEY,
  posting_id INTEGER NOT NULL REFERENCES posting(id) ON DELETE CASCADE,
  state      TEXT NOT NULL,
  note       TEXT,
  at         TEXT NOT NULL,
  source     TEXT NOT NULL DEFAULT 'human'
);
CREATE INDEX IF NOT EXISTS triage_event_posting ON triage_event(posting_id, id);

CREATE TABLE IF NOT EXISTS tracker_entry (
  id            INTEGER PRIMARY KEY,
  source_file   TEXT NOT NULL,
  employer_name TEXT NOT NULL,
  role          TEXT,
  status        TEXT,
  applied_on    TEXT,
  imported_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tracker_match (
  posting_id       INTEGER NOT NULL REFERENCES posting(id) ON DELETE CASCADE,
  tracker_entry_id INTEGER NOT NULL REFERENCES tracker_entry(id) ON DELETE CASCADE,
  confidence       REAL NOT NULL,
  PRIMARY KEY (posting_id, tracker_entry_id)
);
"""


# Additive migrations only: {table: {column: definition}}. CREATE TABLE IF NOT EXISTS
# does nothing to a table that already exists, so a new column needs this. Additive
# is the only kind allowed here - a destructive migration on a database holding the
# operator's triage decisions is not something a start-up path should be able to do.
MIGRATIONS = {
    "posting": {
        "workable": "INTEGER NOT NULL DEFAULT 1",
        "blocked_by": "TEXT",
        "is_remote": "INTEGER NOT NULL DEFAULT 0",
        "is_hybrid": "INTEGER NOT NULL DEFAULT 0",
    },
}


def _migrate(conn: sqlite3.Connection) -> list[str]:
    applied = []
    for table, columns in MIGRATIONS.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue
        for column, definition in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                applied.append(f"{table}.{column}")
    if applied:
        conn.commit()
    return applied


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    # Migrate before the schema script, because the script creates indexes that
    # reference the new columns.
    _migrate(conn)
    conn.executescript(SCHEMA)
    return conn


def check(path: str | Path) -> dict:
    """Read-only integrity check.

    Opened read-only on purpose: a plain connect() against a missing file creates
    an empty database and then every check passes against nothing.
    """
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return {"ok": False, "reason": "missing or empty"}
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        objects = conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
        quick = conn.execute("PRAGMA quick_check").fetchone()[0]
        return {"ok": objects > 0 and quick == "ok", "objects": objects, "quick_check": quick}
    finally:
        conn.close()
