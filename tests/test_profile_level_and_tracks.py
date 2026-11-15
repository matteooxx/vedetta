"""Photograph of `profile.py` as it behaves today: level, labels, `require_match`.

`level_verdict`, `labels_for` and `track_label` had no tests at all. Step P1b will
change `level_verdict`; these cases are the "before" picture, so that an intended
change can be told apart from collateral damage.

The label ids asserted here are a contract, not an implementation detail: the
`exclude_if` lists in users' configurations name them literally.
"""
from __future__ import annotations

import pytest

from vedetta.labels.engine import Label
from vedetta.profile import Profile


def make_profile(require_match: bool = False, exclude_if=None) -> Profile:
    return Profile.from_dict({
        "experience": {
            "accept_level": ["Intern", "trainee", "sous chef", "band 5", "associate"],
            "reject_level": ["senior", "manager", "head of"],
        },
        "locations": {
            "preferred": ["Dublin"],
            "acceptable": ["Italy"],
            "conditional": ["United Kingdom"],
            "excluded": ["United States"],
        },
        "tracks": {"require_match": require_match},
        "exclude_if": exclude_if or [],
    })


def cluster_label() -> Label:
    return Label(rule_id="some-cluster", kind="cluster", severity="positive",
                 explain="right kind of work")


# ------------------------------------------------------------ level_verdict
@pytest.mark.parametrize("title, expected", [
    ("Trainee Accountant", ("accept", "trainee")),
    ("Intern, Finance", ("accept", "intern")),          # config word is lowercased
    ("Senior Accountant", ("reject", "senior")),
    ("Sous Chef", ("accept", "sous chef")),             # a phrase, not a single word
    ("Band 5 Nurse", ("accept", "band 5")),
    ("Head of Finance", ("reject", "head of")),
    ("Accountant", (None, None)),
    # Word inside another word: must NOT match (the \b boundary).
    ("International Account Executive", (None, None)),
    ("Seniority Review Analyst", (None, None)),
    ("Band 55 Nurse", (None, None)),
    (None, (None, None)),
    ("", (None, None)),
])
def test_level_verdict(title, expected):
    assert make_profile().level_verdict(title) == expected


def test_level_verdict_with_empty_lists_is_none():
    assert Profile().level_verdict("Senior Trainee Manager") == (None, None)


def test_accept_is_tested_before_reject_when_both_match_different_words():
    # Today's order: accept first. Pinned so a change of order is visible.
    assert make_profile().level_verdict("Trainee Manager") == ("accept", "trainee")


@pytest.mark.xfail(strict=True, reason=(
    "Resta cosi' fino al passo P1b, che inverte l'ordine (reject prima di accept). "
    "Quando P1b entra, togliere questo marcatore o la suite diventa rossa: e' voluto."))
def test_a_word_in_both_lists_reads_as_reject():
    # Real case: `associate` is an accept word, `manager` a reject word.
    # Commit c499800 announced this as fixed; the code was never changed.
    assert make_profile().level_verdict("Associate Renewals Manager")[0] == "reject"


# --------------------------------------------------------------- labels_for
def by_id(labels):
    return {l.rule_id: l for l in labels}


@pytest.mark.parametrize("location, rule_id, kind, severity", [
    ("Dublin", "location-preferred", "geography", "positive"),
    ("Italy", "location-acceptable", "geography", "positive"),
    ("United Kingdom", "location-conditional", "geography", "warning"),
    ("United States", "location-excluded", "geography", "blocking"),
    ("Nowhereland", "location-unknown", "geography", "info"),
    (None, "location-unknown", "geography", "info"),
])
def test_location_labels(location, rule_id, kind, severity):
    labels = make_profile().labels_for(None, location)
    assert len(labels) == 1
    label = labels[0]
    assert (label.rule_id, label.kind, label.severity) == (rule_id, kind, severity)
    assert label.produced_by == "profile"


def test_level_too_senior_label():
    labels = make_profile().labels_for("Senior Accountant", "Dublin")
    label = by_id(labels)["level-too-senior"]
    assert (label.kind, label.severity, label.value) == ("gate", "blocking", "senior")
    assert label.produced_by == "profile"
    assert "level-suitable" not in by_id(labels)


def test_level_suitable_label_is_a_note_not_a_cluster():
    labels = make_profile().labels_for("Trainee Accountant", "Dublin")
    label = by_id(labels)["level-suitable"]
    assert label.kind == "note"
    assert label.kind != "cluster"
    assert label.severity == "positive"
    assert label.produced_by == "profile"
    assert "level-too-senior" not in by_id(labels)


def test_no_level_label_when_title_matches_nothing():
    labels = make_profile().labels_for("Accountant", "Dublin")
    assert [l.rule_id for l in labels] == ["location-preferred"]


def test_labels_for_none_title_gives_only_location():
    labels = make_profile().labels_for(None, "Italy")
    assert [l.rule_id for l in labels] == ["location-acceptable"]


# ------------------------------------------------- track_label / blocked_by
def test_track_label_is_none_when_require_match_is_off():
    assert make_profile(require_match=False).track_label([]) is None


def test_track_label_is_none_when_a_cluster_is_present():
    assert make_profile(require_match=True).track_label([cluster_label()]) is None


def test_track_label_without_cluster_when_required():
    label = make_profile(require_match=True).track_label([])
    assert label is not None
    assert (label.rule_id, label.kind, label.severity, label.produced_by) == (
        "no-target-track", "gate", "blocking", "profile")


def test_track_label_ignores_non_cluster_labels():
    other = Label(rule_id="x", kind="note", severity="positive", explain="")
    assert make_profile(require_match=True).track_label([other]) is not None


def test_require_match_without_cluster_makes_posting_unworkable():
    profile = make_profile(require_match=True, exclude_if=["no-target-track"])
    labels = profile.labels_for("Accountant", "Dublin")
    assert [l.rule_id for l in profile.blocked_by(labels)] == ["no-target-track"]
    assert profile.is_workable(labels) is False


def test_require_match_with_cluster_leaves_posting_workable():
    profile = make_profile(require_match=True, exclude_if=["no-target-track"])
    labels = profile.labels_for("Accountant", "Dublin") + [cluster_label()]
    assert profile.blocked_by(labels) == []
    assert profile.is_workable(labels) is True


def test_level_suitable_does_not_satisfy_require_match():
    # "Trainee Accountant" once slipped through as workable because the level
    # label was a cluster. It must still be blocked.
    profile = make_profile(require_match=True, exclude_if=["no-target-track"])
    labels = profile.labels_for("Trainee Accountant", "Dublin")
    assert "level-suitable" in by_id(labels)
    assert [l.rule_id for l in profile.blocked_by(labels)] == ["no-target-track"]
    assert profile.is_workable(labels) is False


def test_require_match_off_leaves_posting_workable():
    profile = make_profile(require_match=False, exclude_if=["no-target-track"])
    labels = profile.labels_for("Accountant", "Dublin")
    assert profile.is_workable(labels) is True


def test_require_match_alone_blocks_nothing_without_exclude_if():
    # Behaviour today: the gate only counts if `no-target-track` is in `exclude_if`.
    # `require_match: true` by itself yields the label but not unworkability.
    profile = make_profile(require_match=True, exclude_if=[])
    labels = profile.labels_for("Accountant", "Dublin")
    assert profile.track_label(labels) is not None
    assert profile.blocked_by(labels) == []
    assert profile.is_workable(labels) is True


def test_no_target_track_is_not_duplicated_if_already_in_labels():
    profile = make_profile(require_match=True, exclude_if=["no-target-track"])
    labels = profile.labels_for("Accountant", "Dublin")
    labels = labels + [profile.track_label(labels)]
    assert [l.rule_id for l in profile.blocked_by(labels)] == ["no-target-track"]


def test_blocked_by_uses_exact_rule_ids_from_labels_for():
    profile = make_profile(exclude_if=["location-excluded", "level-too-senior"])
    labels = profile.labels_for("Senior Accountant", "United States")
    assert sorted(l.rule_id for l in profile.blocked_by(labels)) == [
        "level-too-senior", "location-excluded"]
    # An unlisted gate stays a visible warning, not a block.
    profile = make_profile(exclude_if=["location-excluded"])
    labels = profile.labels_for("Senior Accountant", "Dublin")
    assert profile.is_workable(labels) is True
