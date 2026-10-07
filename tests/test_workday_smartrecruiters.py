"""Tests for the Workday and SmartRecruiters adapters, with no network involved.

Both carry a trap that produces a *quietly partial* result, which is the worst kind
here: a board returning a third of its postings looks exactly like a smaller board.
"""
from __future__ import annotations

import pytest

from vedetta.adapters.smartrecruiters import _labels, _location
from vedetta.adapters.workday import _IS_COUNT, _plain, _posted_on, _public_base
from vedetta.places import extract


# --- Workday ---------------------------------------------------------------

def test_public_base_turns_the_api_url_into_a_human_one():
    endpoint = "https://zendesk.wd1.myworkdayjobs.com/wday/cxs/zendesk/zendesk/jobs"
    assert _public_base(endpoint) == "https://zendesk.wd1.myworkdayjobs.com/zendesk"


def test_public_base_handles_a_site_name_that_differs_from_the_tenant():
    endpoint = "https://guidewire.wd5.myworkdayjobs.com/wday/cxs/guidewire/external/jobs"
    assert _public_base(endpoint) == "https://guidewire.wd5.myworkdayjobs.com/external"


@pytest.mark.parametrize("raw,offset_days", [
    ("Posted Today", 0),
    ("Posted Yesterday", 1),
    ("Posted 3 Days Ago", 3),
    ("Posted 2 Weeks Ago", 14),
    ("Posted 30+ Days Ago", 30),
])
def test_prose_dates_become_real_ones(raw, offset_days):
    """Workday reports recency as prose; the rest of the system orders by date."""
    from datetime import date, timedelta
    assert _posted_on(raw) == (date.today() - timedelta(days=offset_days)).isoformat()


def test_an_unrecognised_date_is_left_alone_rather_than_guessed():
    """A wrong date silently changes what counts as new."""
    assert _posted_on("sometime last spring") is None
    assert _posted_on(None) is None
    assert _posted_on(17) is None


@pytest.mark.parametrize("raw", ["2 Locations", "  3 locations ", "10 Locations"])
def test_a_location_count_is_recognised_as_not_a_place(raw):
    assert _IS_COUNT.match(raw)


@pytest.mark.parametrize("raw", ["Dublin, Ireland", "Remote", "Locations"])
def test_a_real_location_is_not_mistaken_for_a_count(raw):
    assert not _IS_COUNT.match(raw)


def test_a_location_count_carries_no_place_at_all():
    """Which is why the detail document has to be consulted.

    Left as it comes from the listing, a third of one real board had no filterable
    location whatsoever.
    """
    assert extract("2 Locations")[0] == []


def test_the_resolved_multi_location_string_parses():
    resolved = ("Austin, Texas, United States of America; "
                "San Francisco, California, United States of America")
    places, _, _ = extract(resolved)
    assert "Austin" in places and "San Francisco" in places
    assert "United States" in places


def test_description_html_is_flattened():
    assert _plain("<p>Fluent&nbsp;<b>German</b> required.</p>") == "Fluent German required."


# --- SmartRecruiters -------------------------------------------------------

def test_location_is_flattened_for_the_shared_place_parser():
    raw = {"city": "Brussels", "region": "Brussels-Capital", "country": "be"}
    assert _location(raw) == "Brussels, Brussels-Capital, be"


def test_the_flattened_form_resolves_the_country_code():
    """A two-letter country code is the platform's normal output, and the shared
    place parser already knows how to expand it - so the adapter does not."""
    places, _, _ = extract(_location({"city": "Warsaw", "country": "pl"}))
    assert places == ["Warsaw", "Poland"]


def test_remote_flag_is_appended_as_text():
    raw = {"city": "Strasbourg", "country": "fr", "remote": True}
    assert _location(raw).endswith("Remote")
    assert extract(_location(raw))[1] is True


def test_duplicate_parts_are_collapsed():
    assert _location({"city": "Luxembourg", "country": "Luxembourg"}) == "Luxembourg"


def test_missing_location_is_none():
    assert _location(None) is None
    assert _location({}) is None


def test_structured_fields_reach_the_rule_engine():
    """`experienceLevel` is a gate this platform states outright rather than leaving
    to be inferred from prose, so it has to be in the text the rules read."""
    entry = {"experienceLevel": {"label": "Student (High school)"},
             "typeOfEmployment": {"label": "Internship"},
             "department": {"label": "Engineering"}}
    text = _labels(entry)
    assert "Student (High school)" in text
    assert "Internship" in text
    assert "Engineering" in text


def test_labels_tolerate_missing_fields():
    assert _labels({}) == ""
    assert _labels({"experienceLevel": None, "function": "not a mapping"}) == ""
