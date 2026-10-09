"""Keys nothing reads, the generator prompt, and the check that writes nothing.

The first of these is the load-bearing one. `location:` where the code wants
`locations:` parses perfectly, saves cleanly, and silently stops every location rule
from applying — and nothing in the interface would ever say so. It is the likeliest
mistake in a file written by hand or by a language model, and it was invisible until
the keys the code reads were written down.
"""
from __future__ import annotations

import os

import pytest

from vedetta import configstore
from vedetta import prompts

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, "config")


# --- keys nothing reads ----------------------------------------------------

def test_a_key_with_a_typo_is_refused_and_the_right_one_suggested():
    with pytest.raises(configstore.ConfigError) as caught:
        configstore.validate("profile", "location:\n  acceptable: [Ireland]\n")
    message = str(caught.value)
    assert "location" in message
    assert "did you mean locations?" in message


def test_a_key_nothing_reads_is_refused_even_without_a_near_match():
    with pytest.raises(configstore.ConfigError) as caught:
        configstore.validate("profile", "favourite_colour: blue\n")
    assert "favourite_colour" in str(caught.value)


def test_only_the_shallowest_unknown_key_is_reported():
    """A typo in a parent would otherwise report every child under it as well, and
    bury the one line that matters."""
    reported = configstore.unknown_keys(
        "profile", {"location": {"acceptable": ["Ireland"], "excluded": ["India"]}})
    assert [path for path, _ in reported] == ["location"]


@pytest.mark.parametrize("name", ["profile", "rules", "settings", "watchlist"])
def test_every_shipped_example_validates(name):
    """The drift test, and it caught a real one: `extract` had become a list of
    patterns while this validator still compiled it as a single string, so from that
    day the rules file could not be saved from the interface at all - it raised a
    TypeError rather than reporting anything. No test had put a shipped file through
    `validate`."""
    with open(os.path.join(EXAMPLES, f"{name}.example.yaml"), encoding="utf-8") as fh:
        configstore.validate(name, fh.read())


@pytest.mark.parametrize("name", ["profile", "rules", "settings", "watchlist"])
def test_every_key_in_an_example_is_a_key_the_code_reads(name):
    """The same drift, from the other side: a key documented in an example but absent
    from KNOWN_KEYS would make the example itself unsaveable."""
    import yaml
    with open(os.path.join(EXAMPLES, f"{name}.example.yaml"), encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    missing = [p for p in configstore.key_paths(doc)
               if p not in configstore.KNOWN_KEYS[name]]
    assert missing == []


def test_a_rules_file_with_several_extract_patterns_is_accepted():
    """Two orders of the same requirement cannot share a capture group, so `extract`
    takes a list."""
    configstore.validate("rules", """
rules:
  - id: years
    kind: gate
    severity: warning
    explain: "asks for more years than you have:"
    extract:
      - '(?i)\\b(\\d{1,2})\\s*years?\\b[^.]{0,40}\\bexperience\\b'
      - '(?i)\\bexperience\\b[^.]{0,25}\\b(\\d{1,2})\\s*years?\\b'
    compare: { operator: gt, field: max_years_experience, ignore_above: 25 }
""")


def test_an_extract_pattern_without_one_group_is_refused():
    """The engine reads group 1. A pattern with none returns nothing and a pattern
    with two returns tuples, which used to raise deep inside the labeller."""
    for pattern in ("(?i)\\d{1,2} years", "(?i)(\\d{1,2}) (years|yrs)"):
        with pytest.raises(configstore.ConfigError) as caught:
            configstore.validate("rules", f"""
rules:
  - id: years
    kind: gate
    severity: warning
    explain: "years"
    extract: '{pattern}'
    compare: {{ operator: gt, value: 4 }}
""")
        assert "capturing group" in str(caught.value)


# --- the prompt ------------------------------------------------------------

@pytest.mark.parametrize("name", prompts.GENERATED)
def test_the_prompt_carries_the_real_schema(name):
    """Generated from the file on disk, so it cannot describe keys the code does not
    read. A hand-written summary would have drifted by now."""
    with open(os.path.join(EXAMPLES, f"{name}.example.yaml"), encoding="utf-8") as fh:
        schema = fh.read()
    prompt = prompts.build(name, schema)
    assert schema.strip()[:80] in prompt


@pytest.mark.parametrize("name", prompts.GENERATED)
def test_the_prompt_forbids_guessing_before_anything_else(name):
    """The rule that decides whether the output is useful or merely plausible, and
    it has to come first: a model reads the top of a list hardest."""
    prompt = prompts.build(name, "x: 1")
    rules = prompt[prompt.index("RULES"):]
    assert "NEVER INVENT A VALUE" in rules.split("2.")[0]
    assert "ask them all at once" in rules.split("2.")[0]


@pytest.mark.parametrize("name", prompts.GENERATED)
def test_the_prompt_asks_for_a_cv_rather_than_assuming_memory(name):
    """A reader opening a fresh chat has an assistant that knows nothing about them.
    A prompt that assumes otherwise produces a confident, invented file."""
    prompt = prompts.build(name, "x: 1")
    assert "attached to this message" in prompt
    assert "Do not assume you do." in prompt


def test_the_prompt_can_carry_the_readers_current_file():
    prompt = prompts.build("profile", "schema: here", "locations:\n  acceptable: [x]")
    assert "WHAT I HAVE NOW" in prompt
    assert "acceptable: [x]" in prompt


def test_there_is_no_prompt_for_the_watchlist():
    """An assistant asked for a hiring-platform identifier produces one that looks
    right. Two independent automated sources each returned a different company than
    the one asked for during this project's design."""
    assert "watchlist" not in prompts.GENERATED
    with pytest.raises(KeyError):
        prompts.build("watchlist", "x: 1")


def test_the_rules_prompt_protects_the_gates():
    """The gates encode visa and language facts, tuned against real adverts. The
    prompt is for the role clusters and nothing else."""
    prompt = prompts.build("rules", "x: 1")
    assert "Keep every `kind: gate` rule EXACTLY as it is" in prompt


def test_the_settings_prompt_refuses_to_touch_the_machine():
    prompt = prompts.build("settings", "x: 1")
    assert "LEAVE ALONE" in prompt
    assert "Never write a password" in prompt


# --- what a change would do ------------------------------------------------

@pytest.fixture()
def board(tmp_path):
    from vedetta import db as db_mod
    conn = db_mod.connect(tmp_path / "v.db")
    conn.execute("INSERT INTO employer (id, key, display_name) VALUES (1,'x','X')")
    conn.execute("INSERT INTO run (id, started_at) VALUES (1,'2026-10-09')")
    rows = [("Observability Engineer", "Dublin, Ireland"),
            ("Monitoring Specialist", "Krakow, Poland"),
            ("Backend Engineer", "Austin, United States"),
            ("Support Engineer", "London, United Kingdom")]
    for index, (title, location) in enumerate(rows, 1):
        conn.execute(
            "INSERT INTO posting (id, employer_id, title, title_norm, location, "
            "first_seen_run, last_seen_run) VALUES (?,1,?,?,?,1,1)",
            (index, title, title.lower(), location))
    conn.commit()
    return conn


def test_a_rule_that_matches_nothing_is_reported_as_zero(board):
    """The most useful thing this check says. A pattern can be perfectly valid and
    still match no title on the reader's own board, and there is no other way to
    find that out short of saving and relabelling."""
    from vedetta import predict
    candidate = {"rules": [
        {"id": "cluster-observability", "kind": "cluster", "severity": "positive",
         "field": "title", "explain": "observability",
         "when": [r"(?i)\b(observability|monitoring)\b.{0,24}"
                  r"\b(engineer|specialist)\b"]},
        {"id": "cluster-nothing", "kind": "cluster", "severity": "positive",
         "field": "title", "explain": "too narrow",
         "when": [r"(?i)\bquantum druid\b"]},
    ]}
    report = predict.rules_effect(board, {"rules": []}, candidate)
    assert report["added"] == ["cluster-observability", "cluster-nothing"]
    assert {h["id"]: h["n"] for h in report["hits"]} == {
        "cluster-observability": 2, "cluster-nothing": 0}


def test_a_removed_rule_is_named(board):
    from vedetta import predict
    rule = {"id": "gone", "kind": "cluster", "explain": "x", "when": ["x"]}
    report = predict.rules_effect(board, {"rules": [rule]}, {"rules": []})
    assert report["removed"] == ["gone"]


def test_the_profile_check_lists_what_would_stop_being_workable(board):
    """The expensive direction, so it is listed posting by posting rather than
    summarised into a number."""
    from vedetta import predict
    from vedetta.profile import Profile
    current = Profile.from_dict({"locations": {"acceptable": ["Europe"]}})
    candidate = Profile.from_dict({"locations": {"acceptable": ["Ireland"],
                                                "excluded": ["Europe"]}})
    report = predict.profile_effect(board, current, candidate)
    assert report["lost_total"] >= 1
    lost = {m["location"] for m in report["lost"]}
    assert "London, United Kingdom" in lost
    assert all(m["now_why"] for m in report["lost"]), (
        "every exclusion has to say which rule decided it")


def test_the_profile_check_writes_nothing(board):
    from vedetta import predict
    from vedetta.profile import Profile
    before = board.execute("SELECT count(*) FROM posting WHERE workable=1").fetchone()[0]
    predict.profile_effect(board, Profile.from_dict({}),
                           Profile.from_dict({"locations": {"excluded": ["Europe"]}}))
    after = board.execute("SELECT count(*) FROM posting WHERE workable=1").fetchone()[0]
    assert after == before


def test_the_settings_check_is_a_key_level_diff():
    from vedetta import predict
    report = predict.settings_effect(
        {"digest": {"subject_prefix": "Vedetta", "hour": 5}},
        {"digest": {"subject_prefix": "Jobs", "hour": 5}})
    assert report["changes"] == [
        {"key": "digest.subject_prefix", "was": "Vedetta", "now": "Jobs"}]
