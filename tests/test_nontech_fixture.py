"""How much of the mechanism holds for a non-tech reader, with no change to the code.

LIMIT, stated up front: the postings, profile and rules in ``fixtures/nontech`` are
synthetic and were written by someone who knows the tech side of this project, not
nursing, retail or catering. This file proves that the CODE is not in the way. It does
NOT prove that these rules would be any good for a nurse or a chef.

Part one passes: what already works. Part two is a list of ``xfail`` tests, deliberately
NOT strict, each one a place where the first real non-tech user will hit a wall. They
are a measurement, not a to-do list; nothing under ``vedetta/`` was touched to write
them. When one starts to pass it simply turns into an XPASS in the report.
"""
from __future__ import annotations

import copy
import json
import os

import pytest
import yaml

from vedetta.adapters.greenhouse import GreenhouseAdapter
from vedetta.labels.engine import RuleEngine
from vedetta.profile import Profile
from vedetta.skills import SkillMatcher

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "nontech")


def _yaml(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Board:
    """Stand-in for the HTTP client: serves postings.json as a Greenhouse board."""

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url):
        return _Response(self.payload)


@pytest.fixture(scope="module")
def profile_doc():
    return _yaml("profile.yaml")


@pytest.fixture(scope="module")
def postings():
    """The synthetic board, read through the real Greenhouse adapter (no network)."""
    with open(os.path.join(HERE, "postings.json"), encoding="utf-8") as fh:
        payload = json.load(fh)
    adapter = GreenhouseAdapter()
    adapter.client = lambda: _Board(payload)
    items = adapter.fetch({"identifier": "nontech"})
    return {item.title: item for item in items}


@pytest.fixture(scope="module")
def engine():
    return RuleEngine(_yaml("rules.yaml"))


def labelled(engine, profile, posting):
    """What ``run.label_posting`` computes, minus the database."""
    labels = engine.apply(posting.text, title=posting.title)
    labels = labels + profile.labels_for(posting.title, posting.location)
    track = profile.track_label(labels)
    if track is not None:
        labels = labels + [track]
    return labels


def ids(labels):
    return {l.rule_id for l in labels}


# =====================================================================================
# PART ONE - what holds
# =====================================================================================

def test_the_board_loads_through_the_real_adapter(postings):
    assert len(postings) == 8
    assert postings["Sous Chef"].location == "Austin, Texas, United States"


@pytest.mark.parametrize("title, expected", [
    ("Sous Chef", ("accept", "sous chef")),
    ("Head Chef", ("reject", "head chef")),
    ("Band 5 Nurse - Emergency Department", ("accept", "band 5")),
    ("Staff Nurse - Medical Ward", ("accept", "staff nurse")),
    ("Kitchen Porter", (None, None)),
])
def test_phrase_levels_work(profile_doc, title, expected):
    """A level may be a whole phrase, not only a word."""
    assert Profile.from_dict(profile_doc).level_verdict(title) == expected


def test_require_match_with_a_non_tech_cluster(engine, profile_doc, postings):
    profile = Profile.from_dict(profile_doc)
    nurse = ids(labelled(engine, profile, postings["Staff Nurse - Medical Ward"]))
    porter = ids(labelled(engine, profile, postings["Kitchen Porter"]))
    assert "cluster-patient-care" in nurse and "no-target-track" not in nurse
    assert "no-target-track" in porter
    assert not profile.is_workable(labelled(engine, profile, postings["Kitchen Porter"]))


def test_each_non_tech_cluster_fires_on_its_own_trade(engine, profile_doc, postings):
    profile = Profile.from_dict(profile_doc)
    expected = {
        "Staff Nurse - Medical Ward": "cluster-patient-care",
        "Occupational Therapist": "cluster-patient-care",
        "Sales Associate": "cluster-counter-sales",
        "Head Chef": "cluster-kitchen",
    }
    for title, rule_id in expected.items():
        assert rule_id in ids(labelled(engine, profile, postings[title])), title


def test_multi_word_skills(profile_doc, postings):
    matcher = SkillMatcher(profile_doc)
    nurse = matcher.compare(postings["Staff Nurse - Medical Ward"].text)
    assert "manual handling" in nurse["matched"]
    assert "patient care" in nurse["matched"]
    # A hyphen where the profile has a space: the separator class covers it.
    ed = matcher.compare(postings["Band 5 Nurse - Emergency Department"].text)
    assert "manual handling" in ed["matched"]
    assert "first aid" in ed["missing"]
    chef = matcher.compare(postings["Sous Chef"].text)
    assert chef["matched"] == ["food hygiene"]
    assert chef["missing"] == ["allergen management"]
    assert "cash handling" in matcher.compare(postings["Sales Associate"].text)["matched"]


def test_a_location_exclusion_carries_its_rule_id(engine, profile_doc, postings):
    profile = Profile.from_dict(profile_doc)
    labels = labelled(engine, profile, postings["Sous Chef"])
    assert "location-excluded" in ids(labels)
    assert [l.rule_id for l in profile.blocked_by(labels)] == ["location-excluded"]


def test_a_level_exclusion_carries_its_rule_id(engine, profile_doc, postings):
    profile = Profile.from_dict(profile_doc)
    labels = labelled(engine, profile, postings["Head Chef"])
    assert "level-too-senior" in ids(labels)
    assert [l.rule_id for l in profile.blocked_by(labels)] == ["level-too-senior"]


def test_which_postings_are_workable(engine, profile_doc, postings):
    profile = Profile.from_dict(profile_doc)
    workable = sorted(t for t, p in postings.items()
                      if profile.is_workable(labelled(engine, profile, p)))
    assert workable == ["Band 5 Nurse - Emergency Department", "Occupational Therapist",
                        "Sales Associate", "Staff Nurse - Medical Ward"]


# --- retail: the same code, two configurations --------------------------------------

def _retail_verdicts(profile_doc, accept, reject):
    doc = copy.deepcopy(profile_doc)
    doc["experience"]["accept_level"] = accept
    doc["experience"]["reject_level"] = reject
    profile = Profile.from_dict(doc)
    return (profile.level_verdict("Store Manager")[0],
            profile.level_verdict("Sales Associate")[0])


def test_retail_right_fixture_rejects_manager_and_accepts_associate(profile_doc):
    assert _retail_verdicts(profile_doc, ["associate"], ["manager"]) == ("reject", "accept")


def test_retail_wrong_fixture_inverts_both(profile_doc):
    """The two words swapped between the lists: same code, opposite answers.

    So the outcome is a fact about configuration, not about the code. (A title holding
    BOTH words reads accept today because accept is tested first; that is covered by
    the xfail in test_profile_level_and_tracks.py and is not repeated here.)
    """
    assert _retail_verdicts(profile_doc, ["manager"], ["associate"]) == ("accept", "reject")


# =====================================================================================
# PART TWO - where the mechanism does not reach (xfail, NOT strict)
# =====================================================================================

@pytest.mark.xfail(strict=False, reason=(
    "Livelli a intervallo non supportati. level_verdict cerca ogni parola/frase della "
    "lista come testo intero nel titolo: 'band 6' non e' contenuto in 'Band 5-7', "
    "quindi un profilo che accetta la fascia 6 non vede un annuncio aperto alle "
    "fasce 5-7. Servirebbe interpretare l'intervallo. (Nota: con 'band 5' in lista "
    "'Band 5-7' risulta accettato, ma per puro caso: combacia l'estremo inferiore.)"))
def test_a_band_range_overlapping_an_accepted_band_is_accepted():
    profile = Profile.from_dict({"experience": {"accept_level": ["band 6"]}})
    assert profile.level_verdict("Band 5-7 Occupational Therapist")[0] == "accept"


@pytest.mark.xfail(strict=False, reason=(
    "Livello dichiarato fuori dal titolo non letto. level_verdict(title) legge solo il "
    "titolo, e l'adapter Greenhouse mette nel testo solo titolo, localita' e "
    "descrizione: il campo strutturato (qui metadata 'Level: Band 6') resta in "
    "raw e nessuno lo guarda. Nel settore sanitario il livello e' spesso solo li'."))
def test_a_level_declared_in_a_structured_field_is_seen(profile_doc, postings):
    posting = postings["Occupational Therapist"]
    assert posting.raw["metadata"] == [{"name": "Level", "value": "Band 6"}]  # it is there
    labels = Profile.from_dict(profile_doc).labels_for(posting.title, posting.location)
    assert "level-suitable" in ids(labels)


def _rule_engine(field, pattern):
    return RuleEngine({"rules": [{
        "id": "structured-signal", "field": field, "kind": "cluster",
        "severity": "positive", "explain": "x", "when": [pattern]}]})


@pytest.mark.xfail(strict=False, reason=(
    "Nessuna regola puo' leggere reparto o tipo di contratto. Una regola legge solo "
    "title, body o all (labels/engine.py:94-102) e apply() riceve solo titolo e testo. "
    "Nel posting reale 'Kitchen Porter' il reparto e' 'Catering' e il contratto "
    "'Bank', ma stanno in raw e non arrivano al motore: una regola `field: "
    "department` non scatta mai. Nei settori non tech sono spesso il segnale migliore."))
@pytest.mark.parametrize("field, pattern", [
    ("department", r"(?i)\bcatering\b"),
    ("employment_type", r"(?i)\bbank\b"),
], ids=["department", "contract-type"])
def test_a_rule_can_read_department_or_contract_type(postings, field, pattern):
    posting = postings["Kitchen Porter"]
    labels = _rule_engine(field, pattern).apply(posting.text, title=posting.title)
    assert "structured-signal" in ids(labels)


@pytest.mark.xfail(strict=False, reason=(
    "Un `field` sconosciuto non da' errore: ricade in silenzio su 'all' "
    "(labels/engine.py:94-102, scopes.get(field, scopes['all'])). Una regola scritta "
    "`field: department` quindi non e' inerte, legge titolo e descrizione insieme e "
    "scatta su qualunque menzione nel testo: qui 'Store Manager' ha reparto 'Retail "
    "Operations', ma la regola scatta per la parola nella descrizione. Meglio un "
    "errore che un risultato sbagliato e plausibile."))
def test_an_unknown_field_does_not_silently_read_everything(postings):
    # 'cash handling' is in the BODY of this posting only; the rule says department.
    posting = postings["Store Manager"]
    labels = _rule_engine("department", r"(?i)\bcash handling\b").apply(
        posting.text, title=posting.title)
    assert "structured-signal" not in ids(labels)
