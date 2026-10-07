"""Tests for the digest outbox.

The outbox exists so an undelivered digest is retried rather than lost, and an unsent
digest is the one failure the reader cannot discover by reading the digest. So what
matters is that a queued digest survives everything short of being delivered.
"""
from __future__ import annotations

import pytest

from vedetta.digest import outbox


@pytest.fixture()
def db(tmp_path):
    return tmp_path / "runtime" / "vedetta.db"


def test_a_digest_is_queued_with_its_subject_and_body(db):
    outbox.write(db, 7, "Vedetta: 3 new", "the body\nover two lines")
    waiting = outbox.pending(db)
    assert len(waiting) == 1
    assert waiting[0].run_id == 7
    assert waiting[0].subject == "Vedetta: 3 new"
    assert waiting[0].body == "the body\nover two lines"


def test_the_file_is_plain_enough_for_a_person_to_read(db):
    path = outbox.write(db, 1, "Subject here", "Body here")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("Subject here\n\n")
    assert "Body here" in text


def test_several_digests_queue_oldest_run_first(db):
    for run_id in (12, 3, 7):
        outbox.write(db, run_id, f"s{run_id}", f"b{run_id}")
    assert [p.run_id for p in outbox.pending(db)] == [3, 7, 12]


def test_an_empty_outbox_is_not_an_error(db):
    assert outbox.pending(db) == []


def test_clearing_removes_only_that_one(db):
    outbox.write(db, 1, "a", "a")
    second = outbox.write(db, 2, "b", "b")
    outbox.clear(second)
    assert [p.run_id for p in outbox.pending(db)] == [1]


def test_clearing_something_already_gone_is_safe(db):
    path = outbox.write(db, 1, "a", "a")
    outbox.clear(path)
    outbox.clear(path)
    assert outbox.pending(db) == []


def test_a_half_written_file_is_never_listed(db, monkeypatch):
    """Written to a temporary name and renamed, so the runner cannot read a partial
    digest and mail it."""
    outbox.write(db, 1, "s", "b")
    directory = outbox.directory(db)
    (directory / "run-2.txt.tmp").write_text("incomplete", encoding="utf-8")
    assert [p.run_id for p in outbox.pending(db)] == [1]


def test_unrelated_files_are_ignored(db):
    outbox.write(db, 1, "s", "b")
    (outbox.directory(db) / "notes.txt").write_text("hello", encoding="utf-8")
    (outbox.directory(db) / "run-abc.txt").write_text("hello", encoding="utf-8")
    assert [p.run_id for p in outbox.pending(db)] == [1]


def test_a_body_containing_blank_lines_survives_the_round_trip(db):
    body = "first\n\nsecond paragraph\n\nthird"
    outbox.write(db, 4, "subject", body)
    assert outbox.pending(db)[0].body == body


def test_requeueing_the_same_run_replaces_rather_than_duplicates(db):
    outbox.write(db, 5, "old", "old body")
    outbox.write(db, 5, "new", "new body")
    waiting = outbox.pending(db)
    assert len(waiting) == 1 and waiting[0].subject == "new"
