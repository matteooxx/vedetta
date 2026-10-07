"""Tests for the sitemap adapter's parsing, with no network involved.

The location flattening is the part worth pinning down: schema.org nests the address,
sometimes as a list, and this adapter has to produce the same flat string the other
adapters give so that one location parser serves all of them.
"""
from __future__ import annotations

from vedetta.adapters.sitemap import _location_of, _plain
from vedetta.places import extract


def test_single_nested_address_is_flattened():
    item = {"jobLocation": {"address": {"addressLocality": "Dublin",
                                        "addressCountry": "Ireland"}}}
    assert _location_of(item) == "Dublin, Ireland"


def test_several_locations_are_joined_the_way_other_adapters_write_them():
    item = {"jobLocation": [
        {"address": {"addressLocality": "Dublin", "addressCountry": "Ireland"}},
        {"address": {"addressLocality": "Krakow", "addressCountry": "Poland"}},
    ]}
    assert _location_of(item) == "Dublin, Ireland; Krakow, Poland"


def test_country_given_as_an_object_is_read():
    item = {"jobLocation": {"address": {"addressLocality": "Paris",
                                        "addressCountry": {"name": "France"}}}}
    assert _location_of(item) == "Paris, France"


def test_telecommute_with_no_address_becomes_remote():
    assert _location_of({"jobLocationType": "TELECOMMUTE"}) == "Remote"


def test_telecommute_alongside_an_address_keeps_both():
    item = {"jobLocationType": "TELECOMMUTE",
            "jobLocation": {"address": {"addressCountry": "Germany"}}}
    assert _location_of(item) == "Germany; Remote"


def test_duplicate_locations_are_collapsed():
    item = {"jobLocation": [
        {"address": {"addressCountry": "Spain"}},
        {"address": {"addressCountry": "Spain"}},
    ]}
    assert _location_of(item) == "Spain"


def test_missing_location_is_none_rather_than_a_guess():
    assert _location_of({}) is None


def test_the_flattened_form_feeds_the_normal_place_parser():
    """One location parser, not two: whatever this produces must be readable by the
    places module that every other adapter's output goes through."""
    item = {"jobLocation": [
        {"address": {"addressLocality": "Dublin", "addressCountry": "Ireland"}},
        {"address": {"addressLocality": "Krakow", "addressCountry": "Poland"}},
    ]}
    places, remote, _ = extract(_location_of(item))
    assert places == ["Dublin", "Ireland", "Krakow", "Poland"]
    assert remote is False


def test_description_html_is_flattened_for_the_rule_engine():
    html = "<p>Fluent <b>French</b> is&nbsp;required.</p>"
    assert _plain(html) == "Fluent French is required."
