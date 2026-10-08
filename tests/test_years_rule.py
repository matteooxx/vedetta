"""The years-of-experience gate, against sentences adverts actually contain.

Several Cisco postings arrived labelled "asks for more years than you have: 40".
Nobody asks for forty years of anything. Cisco was founded in 1984 and writes "40
years of innovation" into its own boilerplate, and because the rule uses the largest
figure it finds, that one number outranked the real requirement beside it.

It is a `warning`, so it cost attention rather than opportunities - but a warning
that is wrong often enough stops being read, and then a real one goes past unnoticed.

These cases are the sentences, not the pattern. A regex can be rewritten; what must
keep holding is which sentences are requirements.
"""
from __future__ import annotations

import os

import pytest
import yaml

from vedetta.labels.engine import RuleEngine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def engine():
    """The shipped rule, not a copy of it: a copy would drift from what runs."""
    with open(os.path.join(ROOT, "config", "rules.example.yaml"),
              encoding="utf-8") as handle:
        doc = yaml.safe_load(handle)
    rule = next(r for r in doc["rules"] if r["id"] == "seniority-threshold")
    return RuleEngine({"profile": {"max_years_experience": 4}, "rules": [rule]})


def _years(engine, text):
    labels = engine.apply(text, title="Software Engineer")
    return labels[0].value if labels else None


@pytest.mark.parametrize("sentence", [
    # The one that started it.
    "Cisco, after 40 years of innovation, is hiring a Full Stack Engineer.",
    "Celebrating 40 years in business. 3+ years of experience with Go required.",
    "40 years of partnership with our customers.",
    "Our 401(k) plan is generous and vests after 2 years.",
    "The team has delivered for 30 years.",
])
def test_a_number_beside_the_word_years_is_not_a_requirement(engine, sentence):
    assert _years(engine, sentence) is None


@pytest.mark.parametrize("sentence,expected", [
    ("We need 8+ years of experience in distributed systems.", "8"),
    ("Minimum 10 years of relevant professional experience.", "10"),
    ("At least 5 years of hands-on experience with Kubernetes.", "5"),
    ("6 years experience in Python.", "6"),
    # Stated the other way round, which one capture group cannot do alone - hence
    # two patterns rather than one.
    ("Experience: 7+ years building platforms.", "7"),
    ("Experience of 9 years in a similar role.", "9"),
])
def test_a_real_requirement_is_still_caught(engine, expected, sentence):
    assert _years(engine, sentence) == expected


def test_the_requirement_is_read_past_an_unrelated_number(engine):
    """Matches do not overlap, so a false match swallows the true one behind it.
    "30 year old company" used to reach the word experience and report 30, taking
    the 6 with it."""
    assert _years(
        engine, "A 30 year old company seeking 6 years experience in Python.") == "6"


def test_a_range_is_read_at_its_lower_bound(engine):
    """"3-5 years" asks for three. Reading it as five would exclude a posting the
    reader qualifies for, and an exclusion is the expensive direction."""
    assert _years(engine, "3-5 years of experience with Kubernetes.") is None
    assert _years(engine, "6-9 years of experience with Kubernetes.") == "6"


def test_a_requirement_within_reach_produces_nothing(engine):
    """The label means "more than you have", so at or below the profile is silent."""
    assert _years(engine, "2 years of experience is plenty.") is None
    assert _years(engine, "4 years of experience required.") is None
    assert _years(engine, "5 years of experience required.") == "5"


def test_an_implausible_figure_is_dropped_rather_than_compared():
    """The ceiling is the second line of defence, for the next way a pattern turns
    out to be wrong. Tested directly, because the shipped pattern now refuses to
    produce a figure this large in the first place."""
    rule = {"id": "y", "kind": "gate", "severity": "warning", "explain": "years:",
            "extract": r"(\d{1,3})\s*years",
            "compare": {"operator": "gt", "field": "max_years_experience",
                        "ignore_above": 25}}
    engine = RuleEngine({"profile": {"max_years_experience": 4}, "rules": [rule]})
    assert engine.apply("40 years of innovation", title="x") == []
    # And it drops only the implausible one: the real requirement beside it stands.
    labels = engine.apply("40 years of innovation. 7 years of experience.", title="x")
    assert [l.value for l in labels] == ["7"]


def test_without_a_ceiling_the_largest_figure_still_wins():
    """Why the ceiling is needed at all: `max` is deliberate - the strictest stated
    requirement is the one that matters - and it is also what lets one stray number
    outrank the real one."""
    rule = {"id": "y", "kind": "gate", "severity": "warning", "explain": "years:",
            "extract": r"(\d{1,3})\s*years",
            "compare": {"operator": "gt", "field": "max_years_experience"}}
    engine = RuleEngine({"profile": {"max_years_experience": 4}, "rules": [rule]})
    assert engine.apply("40 years of innovation. 7 years of experience.",
                        title="x")[0].value == "40"
