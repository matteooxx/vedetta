"""T1: the current schema reaches a database that already exists.

CREATE TABLE IF NOT EXISTS does nothing to a table that is already there, so on an
existing database a new column exists only if it is also listed in db.MIGRATIONS.
The production database already exists and holds the operator's triage decisions,
which cannot be rebuilt. These tests build a database from a frozen schema, put one
row in every table, run the current db.connect() over it, and check:

(a) every table of the current SCHEMA has the same columns - name, type, NOT NULL,
    default - as a database created from scratch. Column order is ignored: ALTER
    TABLE appends, and nothing reads rows by position. Tables the SCHEMA does not
    know must come out exactly as they went in;
(b) every row is still there, with the same values;
(c) a second connect() changes nothing;
(d) every column a migration adds can be left out of an INSERT, so code written for
    the old schema keeps working against the new one while both run side by side.

Every check runs on two frozen schemas:

- repo: schema_ae75d5e.sql, what the repository declared at ae75d5e;
- prod: schema_prod_20261112.sql, what production actually has, read from
  sqlite_master on 2026-11-12. It differs from `repo` by the orphan table
  mail_observation (docs/data-model.md), its index and its autoindex, and by the
  column order that the real ALTER TABLE history left behind.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from vedetta import db

FIXTURES = Path(__file__).parent / "fixtures"

# (frozen schema file, tables in it that the current SCHEMA does not create). The
# second element is stated, not computed: if an orphan disappeared from the prod
# file, or a new one appeared in either, the check on it must fail rather than
# quietly adapt.
FROZEN_SCHEMAS = {
    "repo": (FIXTURES / "schema_ae75d5e.sql", set()),
    "prod": (FIXTURES / "schema_prod_20261112.sql", {"mail_observation"}),
}


def _rows(n: int) -> dict[str, dict]:
    """One row per table of the frozen schema, every column given a value.

    Values are deliberately not the defaults, and nullable columns are filled, so that
    a migration which reset or blanked a column would show up as a changed value.
    `n` keeps keys distinct when a second set is inserted.
    """
    return {
        "employer": dict(id=n, key=f"emp-{n}", display_name=f"Employer {n}",
                         channel="private", homepage=f"https://e{n}.invalid",
                         careers_url=f"https://e{n}.invalid/jobs", enabled=0,
                         notes="kept by hand"),
        "source": dict(id=n, employer_id=n, platform="greenhouse", identifier=f"ident{n}",
                       endpoint="https://api.invalid", job_url_pattern="/jobs/",
                       job_url_exclude="/intern/", discovered_by="manifest",
                       evidence="seen on careers page", verified_on="2026-01-02",
                       verified_note="checked by operator", enabled=0, health="ok"),
        "run": dict(id=n, started_at="2026-11-01T05:00:00Z",
                    finished_at="2026-11-01T05:07:00Z", trigger="cron", seeding=1,
                    digest_sent=1, state="failed", heartbeat_at="2026-11-01T05:06:00Z",
                    error="boom"),
        "run_event": dict(id=n, run_id=n, at="2026-11-01T05:01:00Z", kind="progress",
                          detail="reading detail pages", done=3, total=7),
        "source_poll": dict(id=n, run_id=n, source_id=n, outcome="partial",
                            http_status=200, item_count=12, duration_ms=345,
                            error="listing moved", note="board changed mid-page"),
        "posting": dict(id=n, employer_id=n, title=f"Engineer {n}",
                        title_norm=f"engineer {n}", location="Dublin, Ireland",
                        location_norm="dublin ireland", url=f"https://e.invalid/{n}",
                        published_at="2026-10-30", first_seen_run=n, last_seen_run=n,
                        closed_run=n, is_pipeline=1, dup_of=n, workable=0,
                        blocked_by="visa", is_remote=1, is_hybrid=1, raw='{"k": 1}'),
        "posting_place": dict(posting_id=n, place=f"Dublin-{n}"),
        "place_meta": dict(place=f"Dublin-{n}", canon="Dublin", parent="Ireland",
                           kind="place"),
        "sighting": dict(id=n, run_id=n, source_id=n, posting_id=n,
                         platform_key=f"gh-{n}", content_hash=f"hash{n}"),
        "posting_skill": dict(posting_id=n, term="python", have=1),
        "label": dict(id=n, posting_id=n, rule_id="years", kind="requirement",
                      severity="warn", value="5", explain="asks for 5 years",
                      produced_by="rules", confidence=0.75,
                      created_at="2026-11-01T05:02:00Z"),
        "triage": dict(posting_id=n, state="applied", note="sent CV, follow up friday",
                       decided_at="2026-11-02T09:30:00Z"),
        "triage_event": dict(id=n, posting_id=n, state="applied", note="moved by hand",
                             at="2026-11-02T09:30:00Z", source="import"),
        "tracker_entry": dict(id=n, source_file="tracker.xlsx",
                              employer_name=f"Employer {n}", role="Engineer",
                              status="applied", applied_on="2026-11-02",
                              imported_at="2026-11-03T10:00:00Z"),
        "tracker_match": dict(posting_id=n, tracker_entry_id=n, confidence=0.9),
        # Only in the prod schema. Empty in production; filled here anyway, so that
        # (b) proves connect() leaves the rows of a table it does not know alone.
        "mail_observation": dict(id=n, message_id=f"<msg-{n}@example.invalid>",
                                 sender="noreply@example.invalid",
                                 subject="Your application", received_at="2026-11-04",
                                 kind="ack", suggested_stage="applied",
                                 evidence="thank you for applying", from_ats=1,
                                 employer_guess=f"Employer {n}", posting_id=n,
                                 match_confidence=0.6, seen_at="2026-11-04T06:00:00Z",
                                 accepted=1, dismissed=1),
    }


def _insert(conn: sqlite3.Connection, rows: dict[str, dict]) -> None:
    # Dict order is insertion order, which is also foreign-key order.
    for table, row in rows.items():
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(row.values()))


def _tables(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def _columns(conn: sqlite3.Connection, table: str) -> dict[str, tuple]:
    """{column: (type, notnull, dflt_value)} - everything ADD COLUMN can get wrong."""
    return {r[1]: (r[2], r[3], r[4]) for r in conn.execute(f"PRAGMA table_info({table})")}


def _snapshot(conn: sqlite3.Connection) -> tuple:
    master = [tuple(r) for r in conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name")]
    info = {t: [tuple(r) for r in conn.execute(f"PRAGMA table_info({t})")]
            for t in _tables(conn)}
    return master, info


def _objects_of(conn: sqlite3.Connection, table: str) -> list[tuple]:
    """Every sqlite_master entry belonging to `table`: itself, indexes, autoindexes."""
    return [tuple(r) for r in conn.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE tbl_name = ? ORDER BY type, name",
        (table,))]


def _build_frozen(path: Path, schema: Path) -> tuple[dict[str, dict], dict[str, dict], dict]:
    """Create the old database, fill it, close it.

    Returns (rows, old columns, old sqlite_master entries per table).
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(schema.read_text(encoding="utf-8"))
        tables = _tables(conn)
        known = _rows(1)
        # The row set must cover every table and every column of the old schema, or a
        # table could lose its rows without this test having anything to compare.
        assert set(tables) <= set(known), f"no row for {set(tables) - set(known)}"
        rows = {t: r for t, r in known.items() if t in tables}
        old_columns = {t: _columns(conn, t) for t in tables}
        for table, row in rows.items():
            assert set(row) == set(old_columns[table]), table
        old_objects = {t: _objects_of(conn, t) for t in tables}
        _insert(conn, rows)
        conn.commit()
    finally:
        conn.close()
    return rows, old_columns, old_objects


@pytest.fixture(params=list(FROZEN_SCHEMAS), ids=list(FROZEN_SCHEMAS))
def migrated(request, tmp_path):
    """The old database after the current db.connect(), and what it held before.

    Parametrised over FROZEN_SCHEMAS, so every test using it runs as [repo] and [prod].
    """
    schema, unknown = FROZEN_SCHEMAS[request.param]
    if not schema.is_file():
        # The production schema stays out of the public repository (see .gitignore):
        # it is the shape of the operator own database, read from sqlite_master. It
        # holds no data at all - 213 lines, zero INSERT - but the decision is his.
        #
        # So on a clean clone this case SKIPS and says why, instead of failing. On the
        # machine where the file exists it still runs in full, and that is where the
        # value is: the migration proven against what production ACTUALLY has, which
        # differs from what the repository declares (the orphan mail_observation, its
        # index, its autoindex, and the column order the real ALTER TABLE history
        # left behind).
        pytest.skip("frozen schema not in the repository: " + schema.name)
    rows, old_columns, old_objects = _build_frozen(tmp_path / "existing.db", schema)
    conn = db.connect(tmp_path / "existing.db")
    fresh = db.connect(tmp_path / "fresh.db")
    try:
        yield conn, fresh, rows, old_columns, old_objects, unknown
    finally:
        conn.close()
        fresh.close()


def test_a_existing_db_has_the_columns_of_a_fresh_one(migrated):
    conn, fresh, _, old_columns, old_objects, unknown = migrated
    current_tables = _tables(fresh)
    assert current_tables, "fresh database has no tables"
    # Parity is over the tables of the current SCHEMA, not over the whole database: a
    # table SCHEMA does not know (the prod orphan) is allowed to be there.
    missing_tables = set(current_tables) - set(_tables(conn))
    assert not missing_tables, f"tables never created on the existing database: {missing_tables}"
    for table in current_tables:
        assert _columns(conn, table) == _columns(fresh, table), (
            f"{table}: existing database diverges from a fresh one. A column added to "
            f"SCHEMA must also be added to MIGRATIONS, with the same definition."
        )

    # And the tables SCHEMA does not know are exactly the expected ones, and come out
    # of connect() untouched: same columns, same table and index definitions. This is
    # the proof that the start-up path leaves alone what it does not own.
    extra = set(_tables(conn)) - set(current_tables)
    assert extra == unknown, f"tables outside SCHEMA: {extra}, expected {unknown}"
    for table in unknown:
        assert _columns(conn, table) == old_columns[table], f"{table}: columns changed"
        assert _objects_of(conn, table) == old_objects[table], (
            f"{table}: table or index definitions changed by connect()")


def test_b_no_row_lost_or_altered(migrated):
    # Read through the connection connect() returned, not a new one: it also sees
    # anything a migration did and has not committed yet.
    conn, _, rows, old_columns, _, _ = migrated
    for table, row in rows.items():
        cols = list(old_columns[table])
        got = [tuple(r) for r in conn.execute(
            f"SELECT {', '.join(cols)} FROM {table} ORDER BY rowid")]
        assert got == [tuple(row[c] for c in cols)], f"{table}: rows lost or altered"


def test_c_second_connect_applies_nothing(migrated, tmp_path):
    # connect() discards what _migrate returns, so a second connect() is proven
    # harmless by what it leaves behind, and _migrate is asked directly afterwards.
    conn = migrated[0]
    before = _snapshot(conn)
    conn.close()
    again = db.connect(tmp_path / "existing.db")
    try:
        assert _snapshot(again) == before
        assert db._migrate(again) == []
        assert _snapshot(again) == before
    finally:
        again.close()


def _droppable(spec: tuple) -> bool:
    _type, notnull, default = spec
    return not notnull or default is not None


def test_d_added_columns_can_be_left_out_by_old_code(migrated):
    # SQLite itself refuses ALTER TABLE ADD COLUMN ... NOT NULL without a DEFAULT, so
    # that case would already fail loudly at connect(). What this protects is the
    # behaviour below: an INSERT written for the old schema, naming only the old
    # columns, must keep working against the new one - the interface container may
    # run old code against a new schema for a while after a deploy.
    conn, _, _, old_columns, _, _ = migrated
    for table, old in old_columns.items():
        added = {c: s for c, s in _columns(conn, table).items() if c not in old}
        for column, spec in added.items():
            assert _droppable(spec), f"{table}.{column} is NOT NULL without DEFAULT"

    second = _rows(2)
    _insert(conn, {t: {c: v for c, v in row.items() if c in old_columns[t]}
                   for t, row in second.items() if t in old_columns})
    conn.rollback()


@pytest.mark.parametrize("table,column", [
    (t, c) for t, cols in db.MIGRATIONS.items() for c in cols])
def test_d_migration_definitions_are_nullable_or_defaulted_and_match_schema(table, column):
    # Both frozen schemas already have every column in MIGRATIONS, so on them the migration
    # adds nothing and (a) and (d) above never see these definitions at work. Apply
    # each one to a scratch table and compare it with what SCHEMA creates: a column
    # declared `TEXT` in MIGRATIONS but `NOT NULL DEFAULT 'x'` in SCHEMA would make
    # every migrated database differ from a fresh one.
    definition = db.MIGRATIONS[table][column]
    scratch = sqlite3.connect(":memory:")
    try:
        scratch.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY)")
        scratch.execute(f"ALTER TABLE probe ADD COLUMN {column} {definition}")
        migrated_spec = _columns(scratch, "probe")[column]
        scratch.executescript(db.SCHEMA)
        schema_columns = _columns(scratch, table)
    finally:
        scratch.close()
    assert column in schema_columns, f"{table}.{column} is in MIGRATIONS but not in SCHEMA"
    assert _droppable(migrated_spec), f"{table}.{column} is NOT NULL without DEFAULT"
    assert migrated_spec == schema_columns[column], (
        f"{table}.{column}: MIGRATIONS says {migrated_spec}, SCHEMA says "
        f"{schema_columns[column]}")
