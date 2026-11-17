"""Tests for the two-writer safety net.

The configuration files are the single source of truth and both a UI and a human
with an editor can write them (ADR-0016). Three things therefore must hold, and all
three fail silently if they do not, so they are tested rather than trusted:

* an invalid rules file can never be saved - it would disable every gate while
  looking like it worked;
* a concurrent edit is reported, never overwritten;
* a backup exists after every write.
"""
from __future__ import annotations

import textwrap

import pytest

from vedetta import configstore

VALID_RULES = textwrap.dedent("""
    # a comment that must survive a round trip
    profile:
      max_years_experience: 2
    rules:
      - id: language-gate
        kind: gate
        severity: blocking
        explain: "requires a language outside the profile"
        when:
          - '(?i)\\bfrench\\b.{0,30}\\brequired\\b'
        unless:
          - '(?i)\\bfrench\\b.{0,30}\\basset\\b'
    """).strip() + "\n"


@pytest.fixture()
def config_dir(tmp_path):
    (tmp_path / "rules.example.yaml").write_text(VALID_RULES, encoding="utf-8")
    return tmp_path


# --- validation -----------------------------------------------------------

def test_valid_rules_pass():
    doc = configstore.validate("rules", VALID_RULES)
    assert doc["rules"][0]["id"] == "language-gate"


def test_broken_yaml_is_refused():
    with pytest.raises(configstore.ConfigError, match="not valid YAML"):
        configstore.validate("rules", "rules: [this: is: wrong")


def test_a_rule_without_explain_is_refused():
    """`explain` is what the digest shows. A rule nobody can read is a rule nobody
    can disagree with, so it is a hard error rather than a warning."""
    bad = "rules:\n  - id: x\n    severity: info\n    when: ['a']\n"
    with pytest.raises(configstore.ConfigError, match="explain"):
        configstore.validate("rules", bad)


def test_a_broken_regex_is_refused():
    bad = ("rules:\n  - id: x\n    explain: y\n    severity: info\n"
           "    when: ['(unclosed']\n")
    with pytest.raises(configstore.ConfigError, match="not valid"):
        configstore.validate("rules", bad)


def test_duplicate_rule_ids_are_refused():
    bad = ("rules:\n"
           "  - id: x\n    explain: y\n    severity: info\n    when: ['a']\n"
           "  - id: x\n    explain: z\n    severity: info\n    when: ['b']\n")
    with pytest.raises(configstore.ConfigError, match="duplicate"):
        configstore.validate("rules", bad)


def test_a_rule_that_matches_nothing_is_refused():
    bad = "rules:\n  - id: x\n    explain: y\n    severity: info\n"
    with pytest.raises(configstore.ConfigError, match="when.*extract"):
        configstore.validate("rules", bad)


def test_bad_field_value_is_refused():
    bad = ("rules:\n  - id: x\n    explain: y\n    severity: info\n"
           "    field: headline\n    when: ['a']\n")
    with pytest.raises(configstore.ConfigError,
                       match=r"rule 'x': field 'headline' .*title, body, all"):
        configstore.validate("rules", bad)


def test_a_list_as_field_is_refused_rather_than_crashing():
    """The allowed values were a set, so `field: [title]` raised TypeError
    (unhashable list) instead of a ConfigError the interface can show."""
    bad = ("rules:\n  - id: x\n    explain: y\n    severity: info\n"
           "    field: [title]\n    when: ['a']\n")
    with pytest.raises(configstore.ConfigError, match=r"field \['title'\]"):
        configstore.validate("rules", bad)


def test_compare_field_is_not_checked_as_a_scope():
    """`compare.field` names a profile number, not what the rule reads."""
    ok = ("rules:\n  - id: years\n    explain: y\n    severity: warning\n"
          "    extract: '(\\d+)\\+? years of experience'\n"
          "    compare: { operator: gt, field: max_years_experience }\n")
    configstore.validate("rules", ok)


def test_watchlist_source_needs_platform_and_identifier():
    bad = "employers:\n  - key: a\n    sources:\n      - platform: greenhouse\n"
    with pytest.raises(configstore.ConfigError, match="identifier"):
        configstore.validate("watchlist", bad)


def _one_source(**source) -> str:
    import yaml
    return yaml.safe_dump({"employers": [{"key": "acme", "sources": [
        {"identifier": "acme", **source}]}]})


def test_a_parameter_the_platforms_adapter_does_not_read_is_refused_by_name():
    """`language` is read by the sitemap adapter only. On a Greenhouse source it
    saves, syncs and does nothing - the refusal has to name the key and the platform,
    or the operator is left hunting for which line is wrong."""
    with pytest.raises(configstore.ConfigError) as info:
        configstore.validate("watchlist", _one_source(platform="greenhouse",
                                                      language="fr"))
    message = str(info.value)
    assert "'language'" in message
    assert "greenhouse" in message


def test_the_parameters_an_adapter_declares_are_accepted_on_its_own_platform():
    from vedetta.adapters import ADAPTERS
    params = {name: "x" for name in ADAPTERS["sitemap"].params}
    assert params, "precondition: the sitemap adapter declares its parameters"
    configstore.validate("watchlist", _one_source(platform="sitemap", **params))


def test_a_platform_with_no_adapter_yet_accepts_any_declared_parameter():
    """The plan's decision, and a case that exists in the live watchlist: `ashby`
    (Mistral AI) and `eightfold` (Microsoft) are kept for the future with no adapter
    behind them. Refusing their keys would stop the operator saving the whole file
    from the interface; the runtime already says loudly that the adapter is missing.
    """
    configstore.validate("watchlist", _one_source(
        platform="eightfold", endpoint="https://x.invalid/", language="en",
        job_url_pattern="/job/"))


def test_a_profile_with_max_years_requested_is_refused_and_says_where_it_went():
    """The key was read by nothing; the years gate reads rules.yaml. An operator who
    kept the two in step by hand did so for a number that did nothing. The refusal
    must name the real home of the number, not just say "unknown key"."""
    old = "experience:\n  years: 1\n  max_years_requested: 2\n"
    with pytest.raises(configstore.ConfigError) as info:
        configstore.validate("profile", old)
    message = str(info.value)
    assert "experience.max_years_requested" in message
    assert "rules.yaml" in message
    assert "profile.max_years_experience" in message


def test_the_descriptive_profile_keys_are_still_accepted():
    doc = configstore.validate(
        "profile", "identity:\n  languages: [english]\nexperience:\n  years: 1\n")
    assert doc["experience"]["years"] == 1


# --- reading and the example fallback -------------------------------------

def test_read_falls_back_to_the_example(config_dir):
    current = configstore.read(config_dir, "rules")
    assert current.is_example
    assert "language-gate" in current.text


def test_saving_creates_the_real_file_and_leaves_the_example(config_dir):
    saved = configstore.save(config_dir, "rules", VALID_RULES, None)
    assert saved.path.name == "rules.yaml"
    assert not saved.is_example
    assert (config_dir / "rules.example.yaml").exists()


# --- the two-writer guard -------------------------------------------------

def test_a_concurrent_edit_is_reported_and_nothing_is_overwritten(config_dir):
    configstore.save(config_dir, "rules", VALID_RULES, None)
    opened = configstore.read(config_dir, "rules")

    # someone edits the file over SSH while the form is open
    changed = VALID_RULES.replace("max_years_experience: 2", "max_years_experience: 4")
    (config_dir / "rules.yaml").write_text(changed, encoding="utf-8")

    mine = VALID_RULES.replace("max_years_experience: 2", "max_years_experience: 9")
    with pytest.raises(configstore.ConflictError) as info:
        configstore.save(config_dir, "rules", mine, opened.digest)

    assert "max_years_experience: 4" in info.value.current_text
    on_disk = (config_dir / "rules.yaml").read_text(encoding="utf-8")
    assert "max_years_experience: 4" in on_disk   # the other edit survived


def test_a_backup_is_kept_on_every_overwrite(config_dir):
    configstore.save(config_dir, "rules", VALID_RULES, None)
    first = configstore.read(config_dir, "rules")
    configstore.save(config_dir, "rules",
                     VALID_RULES.replace("explain: \"requires", "explain: \"needs"),
                     first.digest)
    backups = list(config_dir.glob("rules.yaml.bak-*"))
    assert len(backups) == 1
    assert "requires" in backups[0].read_text(encoding="utf-8")


def test_an_invalid_document_never_reaches_disk(config_dir):
    configstore.save(config_dir, "rules", VALID_RULES, None)
    good = (config_dir / "rules.yaml").read_text(encoding="utf-8")
    with pytest.raises(configstore.ConfigError):
        configstore.save(config_dir, "rules", "rules: [", None)
    assert (config_dir / "rules.yaml").read_text(encoding="utf-8") == good


def test_comments_survive_a_structured_patch(config_dir):
    configstore.save(config_dir, "rules", VALID_RULES, None)
    current = configstore.read(config_dir, "rules")

    def bump(doc):
        doc["profile"]["max_years_experience"] = 3

    try:
        saved = configstore.patch(config_dir, "rules", bump, current.digest)
    except configstore.ConfigError as exc:
        pytest.skip(f"round-trip library unavailable: {exc}")
    assert "a comment that must survive" in saved.text
    assert "max_years_experience: 3" in saved.text
