"""Tests for the two places where this project is most likely to be quietly wrong.

The rule engine's `unless` clause and the reconciliation ordering are both things
whose failure is silent: a posting that should have been shown is simply not there.
So they get tests, and the tests encode the real distinctions rather than toy cases.
"""
from __future__ import annotations

import pytest
import yaml

from vedetta.adapters.base import normalise
from vedetta.labels.engine import RuleEngine, score

RULES = yaml.safe_load(
    """
profile:
  max_years_experience: 2
rules:
  - id: language-gate
    kind: gate
    severity: blocking
    explain: "requires a language outside the profile"
    when:
      - '(?i)\\b(fluent|required)\\b[^.]{0,60}\\b(french|german)\\b'
      - '(?i)\\b(french|german)\\b[^.]{0,40}\\b(required|mandatory)\\b'
    unless:
      - '(?i)\\b(french|german)\\b[^.]{0,50}\\b(asset|a plus|nice to have)\\b'
  - id: seniority-threshold
    kind: gate
    severity: warning
    explain: "asks for more years than the profile has:"
    extract: '(?i)(\\d{1,2})\\s*\\+?\\s*years?\\b'
    compare: { operator: gt, field: max_years_experience }
  - id: cluster-cloud
    kind: cluster
    severity: positive
    explain: "cloud / devops"
    when:
      - '(?i)\\b(cloud|devops)\\s+engineer\\b'
"""
)


def engine():
    return RuleEngine(RULES)


# --- the distinction the whole engine exists for ---------------------------

def test_language_required_is_blocking():
    labels = engine().apply("Fluent French is required for this role.")
    assert [l.rule_id for l in labels] == ["language-gate"]
    assert labels[0].severity == "blocking"


def test_language_as_an_asset_is_not_a_gate():
    """The same language, described as desirable, must NOT block.

    This is the case that decides whether several real postings are alive or dead.
    """
    labels = engine().apply("English required. French is a strong asset.")
    assert [l.rule_id for l in labels] == []


def test_language_mandatory_phrasing_blocks():
    labels = engine().apply("German is mandatory for client contact.")
    assert [l.rule_id for l in labels] == ["language-gate"]


# --- numeric gate ---------------------------------------------------------

def test_seniority_above_profile_is_flagged_with_its_value():
    labels = engine().apply("We are looking for 5+ years of experience.")
    assert labels[0].rule_id == "seniority-threshold"
    assert labels[0].value == "5"


def test_seniority_within_profile_is_not_flagged():
    assert engine().apply("1 year of experience is enough.") == []


def test_highest_number_wins_when_several_are_present():
    labels = engine().apply("2 years required, 7 years preferred.")
    assert labels[0].value == "7"


# --- what a rule reads: `field` --------------------------------------------
#
# An unknown `field` used to fall back to `all` in silence, so a rule written to read
# the department fired on any mention in the advert. It is refused when the rules are
# compiled, by name, before a single posting is judged.

def _cash_rule(**extra):
    return {"id": "cash-dept", "kind": "cluster", "severity": "positive",
            "explain": "x", "when": [r"(?i)\bcash handling\b"], **extra}


def test_an_unknown_field_is_refused_naming_the_rule_and_the_value():
    with pytest.raises(ValueError) as refused:
        RuleEngine({"rules": [_cash_rule(field="department")]})
    message = str(refused.value)
    assert message.startswith("rule 'cash-dept': field 'department' ")
    assert "title, body, all" in message


@pytest.mark.parametrize("value", [None, "Title", ["title"]],
                         ids=["empty", "capitalised", "list"])
def test_a_field_that_is_almost_a_scope_is_refused_too(value):
    """`field:` left empty reads as None, and None fell back to `all` like the rest."""
    with pytest.raises(ValueError, match="cash-dept"):
        RuleEngine({"rules": [_cash_rule(field=value)]})


def test_a_rule_without_an_id_is_named_by_its_position():
    rule = _cash_rule(field="department")
    del rule["id"]
    with pytest.raises(ValueError, match=r"^rule 2: field 'department' "):
        RuleEngine({"rules": [_cash_rule(), rule]})


def test_a_field_changed_after_compiling_fails_instead_of_reading_everything():
    """The second guard, in `apply`: no fallback to `all` there either."""
    rule = _cash_rule(field="body")
    compiled = RuleEngine({"rules": [rule]})
    rule["field"] = "department"
    with pytest.raises(KeyError):
        compiled.apply("Duties include cash handling.", title="Store Manager")


def test_the_three_scopes_still_read_what_they_say():
    text = "Duties include cash handling."
    for field, fires in (("title", False), ("body", True), ("all", True)):
        labels = RuleEngine({"rules": [_cash_rule(field=field)]}).apply(
            text, title="Store Manager")
        assert bool(labels) is fires, field
    assert RuleEngine({"rules": [_cash_rule()]}).apply(text, title="Store Manager")


def test_compare_field_is_not_a_scope():
    """The other `field`: inside `compare` it names a profile number, as in the live
    years gate. Checking it against title/body/all would refuse production's rules."""
    assert [l.value for l in engine().apply("At least 5+ years of experience.")] == ["5"]


# --- scoring is arithmetic over visible facts ----------------------------

def test_score_is_a_transparent_sum():
    labels = engine().apply("Cloud Engineer. 5+ years. French is a plus.")
    kinds = {l.rule_id for l in labels}
    assert "cluster-cloud" in kinds and "seniority-threshold" in kinds
    assert "language-gate" not in kinds          # 'a plus' is not a gate
    assert score(labels) == 3 - 2                # positive + warning


def test_a_posting_that_trips_everything_still_scores_and_is_therefore_shown():
    labels = engine().apply("Fluent German required. 10 years experience.")
    assert score(labels) < 0                      # ranked low
    assert labels                                 # but labelled, so it is explainable


# --- normalisation for reconciliation ------------------------------------

def test_gender_tags_are_stripped():
    assert normalise("DevOps Engineer (m/f/d)") == normalise("DevOps Engineer")
    assert normalise("Cloud Architect (x/f/m)") == normalise("Cloud Architect")


def test_case_and_punctuation_are_ignored():
    assert normalise("Senior  SRE,  Platform") == normalise("senior sre platform")


def test_normalisation_does_not_collapse_different_roles():
    """Conservative on purpose: when unsure the caller keeps both and flags one."""
    assert normalise("Cloud Engineer") != normalise("Cloud Architect")
    assert normalise("Engineer II") != normalise("Engineer III")


def test_empty_input_is_safe():
    assert normalise(None) == ""
    assert normalise("") == ""


def test_an_exclusion_reason_is_not_printed_twice():
    """Every excluded posting read "matched none of your target role clusters;
    matched none of your target role clusters", because blocked_by recomputed a
    label the labeller had already added. The reason line exists to be read."""
    from vedetta.profile import Profile
    profile = Profile.from_dict({
        "tracks": {"require_match": True},
        "exclude_if": ["no-target-track"],
    })
    labels = [profile.track_label([])]
    blocking = profile.blocked_by(labels)
    assert [l.rule_id for l in blocking] == ["no-target-track"]
    assert "; ".join(l.explain for l in blocking) == (
        "matched none of your target role clusters")


def test_the_reason_still_appears_when_the_labeller_did_not_add_it():
    """blocked_by may be handed a list that never went through the labeller, so the
    recompute has to stay."""
    from vedetta.profile import Profile
    profile = Profile.from_dict({
        "tracks": {"require_match": True},
        "exclude_if": ["no-target-track"],
    })
    assert [l.rule_id for l in profile.blocked_by([])] == ["no-target-track"]
