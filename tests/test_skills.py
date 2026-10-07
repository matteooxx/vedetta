"""Tests for the technology comparison.

The feature is only defensible because it reports a difference and stops. So the
tests pin down the matching — where a careless word boundary produces confident
nonsense — and the absence of any score.
"""
from __future__ import annotations

import pytest

from vedetta.skills import SkillMatcher, summarise

PROFILE = {
    "skills": {
        "have": ["AWS", "Kubernetes", "CI/CD", "Python", "GitHub Actions", "C++",
                 ".NET", "Node.js", "Git"],
        "watch": ["Java", "Go", "Kafka", "ArgoCD", "TypeScript", "Rust"],
    }
}


@pytest.fixture()
def matcher():
    return SkillMatcher(PROFILE)


def test_a_term_you_have_is_reported_as_matched(matcher):
    out = matcher.compare("We run Kubernetes on AWS.")
    assert set(out["matched"]) == {"AWS", "Kubernetes"}
    assert out["missing"] == []


def test_a_watched_term_you_lack_is_reported_as_missing(matcher):
    out = matcher.compare("Experience with Kafka and Rust required.")
    assert set(out["missing"]) == {"Kafka", "Rust"}


# --- the matching traps ----------------------------------------------------

def test_java_does_not_match_javascript(matcher):
    """The classic false positive, and the reason matching is whole-word."""
    out = matcher.compare("Strong JavaScript skills.")
    assert "Java" not in out["missing"]


def test_go_does_not_match_going(matcher):
    out = matcher.compare("You will be going to conferences.")
    assert "Go" not in out["missing"]


def test_go_does_match_the_language(matcher):
    assert "Go" in matcher.compare("Written in Go and Python.")["missing"]


@pytest.mark.parametrize("text,term", [
    ("Experience with C++ is a plus", "C++"),
    ("Our stack is .NET 8", ".NET"),
    ("Node.js services", "Node.js"),
    ("nodejs services", "Node.js"),
    ("CI/CD pipelines", "CI/CD"),
    ("ci / cd pipelines", "CI/CD"),
])
def test_terms_whose_shape_defeats_a_word_boundary(matcher, text, term):
    """`C++`, `.NET`, `Node.js` and `CI/CD` all contain characters that \\b ignores."""
    assert term in matcher.compare(text)["matched"]


def test_a_multi_word_term_tolerates_a_hyphen(matcher):
    for text in ("GitHub Actions", "github-actions", "GitHub  Actions"):
        assert "GitHub Actions" in matcher.compare(text)["matched"]


def test_matching_is_case_insensitive(matcher):
    assert "Kubernetes" in matcher.compare("kubernetes and KUBERNETES")["matched"]


# --- the employer's own name -----------------------------------------------

def test_an_employers_own_name_is_not_a_signal_about_it():
    """Every GitLab posting mentions GitLab. True, unavoidable, and useless."""
    m = SkillMatcher({"skills": {"have": ["GitLab", "Python"], "watch": []}})
    out = m.compare("Work on GitLab using Python.", employer="GitLab")
    assert out["matched"] == ["Python"]


def test_the_same_term_still_counts_for_a_different_employer():
    m = SkillMatcher({"skills": {"have": ["GitLab"], "watch": []}})
    assert m.compare("We use GitLab CI.", employer="Intercom")["matched"] == ["GitLab"]


# --- unknown terms and empty input -----------------------------------------

def test_a_term_on_neither_list_is_not_invented(matcher):
    """An unrecognised word is far more likely to be prose than a technology, and
    guessing would fill the result with noise."""
    out = matcher.compare("Experience with Blorptron 9 essential.")
    assert out["matched"] == [] and out["missing"] == []


def test_empty_input_is_safe(matcher):
    for value in (None, "", "   "):
        out = matcher.compare(value)
        assert out["matched"] == [] and out["missing"] == []


def test_an_unconfigured_profile_reports_itself():
    m = SkillMatcher({})
    assert not m.configured
    assert m.compare("Kubernetes everywhere")["configured"] is False


# --- the summary line ------------------------------------------------------

def test_the_summary_names_both_halves(matcher):
    line = summarise(matcher.compare("Kubernetes, AWS, Kafka and Go."))
    assert "you have" in line and "not on your list" in line


def test_the_summary_has_no_score(matcher):
    """Deliberately: whether a gap matters is a judgement about your own experience,
    and a number would imply the program had made it."""
    line = summarise(matcher.compare("Kubernetes, AWS, Kafka and Go."))
    assert "%" not in line
    assert not any(token.rstrip(",.").isdigit() for token in line.split())


def test_the_summary_is_none_when_nothing_matched(matcher):
    assert summarise(matcher.compare("A role with no technologies named.")) is None


def test_the_summary_is_none_when_unconfigured():
    assert summarise(SkillMatcher({}).compare("Kubernetes")) is None
