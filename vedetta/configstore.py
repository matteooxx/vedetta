"""Reading and writing the configuration files safely.

The files are the single source of truth (ADR-0016). The UI is an editor for them,
not a second store. That makes three things mandatory rather than nice to have:

**Comments survive.** The rule file's comments are what explain the rules. A UI that
stripped them would make the file worse every time it was opened.

**A concurrent edit is detected, not overwritten.** The UI records the file's hash
when it renders a form and refuses to save against a different one.

**Nothing invalid can be saved.** A rules file that does not parse would silently
disable every gate - the exact class of silent failure this project exists to
prevent - so validation happens before the write, not after.

**A key nothing reads is refused.** `location:` where the code wants `locations:`
parses perfectly, saves cleanly, and silently stops every location rule from
applying. Nothing in the interface would ever say so. That is the likeliest mistake
in a file written by hand or by a language model, and it was invisible until the keys
below were written down.
"""
from __future__ import annotations

import difflib
import hashlib
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

try:  # comment-preserving round trip, used only by the editor
    from ruamel.yaml import YAML as _RuamelYAML

    _ruamel = _RuamelYAML()
    _ruamel.preserve_quotes = True
    _ruamel.width = 4096
except Exception:  # pragma: no cover - the daily run never needs it
    _ruamel = None

EDITABLE = ("profile", "watchlist", "rules", "settings")


class ConfigError(ValueError):
    """Raised when a document would not be safe to save."""


class ConflictError(RuntimeError):
    def __init__(self, message: str, current_text: str, current_hash: str):
        super().__init__(message)
        self.current_text = current_text
        self.current_hash = current_hash


@dataclass
class ConfigFile:
    name: str
    path: Path
    text: str
    digest: str
    is_example: bool

    @property
    def exists(self) -> bool:
        return not self.is_example


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def resolve(config_dir: Path, name: str) -> tuple[Path, bool]:
    """Return the file to edit, and whether we are falling back to the example."""
    real = config_dir / f"{name}.yaml"
    if real.exists():
        return real, False
    return config_dir / f"{name}.example.yaml", True


def read(config_dir: Path, name: str, prefer_example: bool = False) -> ConfigFile:
    """The live file, or with `prefer_example` the shipped example beside it.

    The example is the schema: every key with a comment saying what it does. The
    generator prompt is built from it rather than from a hand-written summary, so it
    cannot describe keys the code does not read.
    """
    if name not in EDITABLE:
        raise ConfigError(f"unknown configuration file: {name}")
    if prefer_example:
        path = Path(config_dir) / f"{name}.example.yaml"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        return ConfigFile(name=name, path=path, text=text, digest=_hash(text),
                          is_example=True)
    path, is_example = resolve(Path(config_dir), name)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return ConfigFile(name=name, path=path, text=text, digest=_hash(text), is_example=is_example)


# --------------------------------------------------------------------- validation

_YEARS = re.compile(r"\(\?i\)|\(\?:|\\")  # presence of regex syntax, used as a hint



# Every key the code actually reads, by file. A key outside these sets is refused on
# save, with the nearest match suggested.
#
# Written out rather than derived from the example files, because the examples do not
# show everything: a sitemap source can carry `job_url_pattern` and `language`, and
# `saved_views` is written by the interface itself. A test asserts that every key in
# every example file appears here, so the two cannot drift apart.
#
# `[]` in a path means "each item of this list".
KNOWN_KEYS = {
    "profile": {
        "identity", "identity.name", "identity.languages", "identity.notes",
        "experience", "experience.years", "experience.max_years_requested",
        "experience.max_years_experience",
        "experience.accept_level", "experience.reject_level",
        "locations", "locations.preferred", "locations.acceptable",
        "locations.conditional", "locations.excluded",
        "locations.remote_counts_as_acceptable",
        "skills", "skills.have", "skills.watch",
        "tracks", "tracks.require_match",
        "exclude_if",
    },
    "rules": {
        "profile", "profile.max_years_experience",
        "rules", "rules[].id", "rules[].kind", "rules[].severity",
        "rules[].explain", "rules[].when", "rules[].unless", "rules[].field",
        "rules[].extract", "rules[].weight", "rules[].value",
        "rules[].compare", "rules[].compare.operator", "rules[].compare.field",
        "rules[].compare.value", "rules[].compare.ignore_above",
    },
    "settings": {
        "database",
        "digest", "digest.subject_prefix", "digest.transport", "digest.hour",
        "digest.timezone", "digest.to", "digest.sender", "digest.host",
        "digest.port", "digest.user", "digest.starttls",
        "ranking", "ranking.weights", "ranking.weights.positive",
        "ranking.weights.info", "ranking.weights.warning",
        "ranking.weights.blocking",
        "discovery", "discovery.manifest", "discovery.redirect",
        "discovery.markers", "discovery.identifier_extraction", "discovery.dns",
        "discovery.sitemap", "discovery.structured_data",
        "discovery.headless_browser",
        "ai_worker", "ai_worker.url",
        "saved_views", "saved_views[].name", "saved_views[].query",
        # Declared in the example and read by nothing yet - the tracker import is
        # backlog item C4. Listed so the shipped example validates, and listed HERE
        # rather than silently tolerated so that whoever implements C4 finds it.
        "trackers", "trackers[].path", "trackers[].format",
        "trackers[].columns", "trackers[].columns.employer",
        "trackers[].columns.role", "trackers[].columns.status",
    },
    "watchlist": {
        "employers",
        "employers[].key", "employers[].display_name", "employers[].channel",
        "employers[].careers_url", "employers[].homepage", "employers[].enabled",
        "employers[].notes", "employers[].sources",
        "employers[].sources[].platform", "employers[].sources[].identifier",
        "employers[].sources[].endpoint", "employers[].sources[].discovered_by",
        "employers[].sources[].evidence", "employers[].sources[].verified_on",
        "employers[].sources[].verified_note", "employers[].sources[].enabled",
        "employers[].sources[].job_url_pattern",
        "employers[].sources[].job_url_exclude",
        "employers[].sources[].sitemap_include",
        "employers[].sources[].sitemap_exclude",
        "employers[].sources[].language",
    },
}


def key_paths(node, prefix: str = "") -> list[str]:
    """Every key path in a document, with `[]` for a step through a list."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            found.append(path)
            found.extend(key_paths(value, path))
    elif isinstance(node, list):
        for item in node:
            found.extend(key_paths(item, prefix + "[]"))
    return found


def unknown_keys(name: str, doc: dict) -> list[tuple[str, str | None]]:
    """Keys nothing reads, each with the nearest key that is read.

    The suggestion is what makes this worth having. "location" against "locations" is
    one letter, and the difference between a profile that excludes half the board and
    one that excludes nothing at all.
    """
    known = KNOWN_KEYS.get(name)
    if not known:
        return []
    out: list[tuple[str, str | None]] = []
    for path in dict.fromkeys(key_paths(doc)):
        if path in known:
            continue
        # Only report the shallowest unknown: a typo in a parent would otherwise
        # report every child under it as well.
        if any(path.startswith(parent + ".") or path.startswith(parent + "[]")
               for parent, _ in out):
            continue
        near = difflib.get_close_matches(path, sorted(known), n=1, cutoff=0.7)
        out.append((path, near[0] if near else None))
    return out


def validate(name: str, text: str) -> dict:
    """Parse and check shape. Returns the parsed document."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"not valid YAML: {exc}") from exc
    if doc is None:
        doc = {}
    if not isinstance(doc, dict):
        raise ConfigError("the document must be a mapping at the top level")

    strays = unknown_keys(name, doc)
    if strays:
        lines = []
        for path, near in strays:
            lines.append(f"  {path}" + (f"  - did you mean {near}?" if near else ""))
        listed = "\n".join(lines)
        raise ConfigError(
            "nothing in this program reads these keys, so they would have no "
            "effect at all:\n" + listed
            + "\n\nA key with a typo in it saves cleanly and then does nothing, "
              "which is the one kind of mistake this file cannot afford. Fix or "
              "remove them.")

    if name == "rules":
        _validate_rules(doc)
    elif name == "watchlist":
        _validate_watchlist(doc)
    elif name == "settings":
        _validate_settings(doc)
    elif name == "profile":
        _validate_profile(doc)
    return doc


def _validate_profile(doc: dict) -> None:
    locations = doc.get("locations") or {}
    if not isinstance(locations, dict):
        raise ConfigError("'locations' must be a mapping")
    for bucket in ("preferred", "acceptable", "conditional", "excluded"):
        value = locations.get(bucket)
        if value is not None and not isinstance(value, list):
            raise ConfigError(f"'locations.{bucket}' must be a list")
    experience = doc.get("experience") or {}
    if not isinstance(experience, dict):
        raise ConfigError("'experience' must be a mapping")
    for key in ("years", "max_years_requested"):
        if experience.get(key) is not None and not isinstance(experience[key], int):
            raise ConfigError(f"'experience.{key}' must be a whole number")
    skills = doc.get("skills")
    if skills is not None:
        if not isinstance(skills, dict):
            raise ConfigError("'skills' must be a mapping with 'have' and 'watch'")
        for bucket in ("have", "watch"):
            value = skills.get(bucket)
            if value is not None and not isinstance(value, list):
                raise ConfigError(f"'skills.{bucket}' must be a list")

    exclude = doc.get("exclude_if")
    if exclude is not None and not isinstance(exclude, list):
        raise ConfigError("'exclude_if' must be a list of rule ids")
    # An overlap between acceptable and excluded would be silently resolved by
    # precedence, which is exactly the kind of quiet surprise this file exists to
    # avoid. Say so instead.
    acceptable = {str(x).lower() for x in locations.get("acceptable") or []}
    excluded = {str(x).lower() for x in locations.get("excluded") or []}
    clash = acceptable & excluded
    if clash:
        raise ConfigError(
            "these locations are in both 'acceptable' and 'excluded': "
            + ", ".join(sorted(clash)))


def _validate_rules(doc: dict) -> None:
    rules = doc.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ConfigError("'rules' must be a non-empty list")
    seen = set()
    allowed_fields = {"title", "body", "all"}
    for index, rule in enumerate(rules, 1):
        where = f"rule {index}"
        if not isinstance(rule, dict):
            raise ConfigError(f"{where}: must be a mapping")
        rid = rule.get("id")
        if not rid:
            raise ConfigError(f"{where}: missing 'id'")
        where = f"rule '{rid}'"
        if rid in seen:
            raise ConfigError(f"{where}: duplicate id")
        seen.add(rid)
        if not rule.get("explain"):
            # Enforced, not advisory: the explanation is what appears next to the
            # posting in the digest. A rule nobody can read is a rule nobody can
            # argue with.
            raise ConfigError(f"{where}: missing 'explain' - it is shown in the digest")
        if "field" in rule and rule["field"] not in allowed_fields:
            raise ConfigError(f"{where}: 'field' must be one of {sorted(allowed_fields)}")
        if "weight" in rule and not isinstance(rule["weight"], int):
            raise ConfigError(f"{where}: 'weight' must be a whole number")
        has_match = any(k in rule for k in ("when", "extract"))
        if not has_match:
            raise ConfigError(f"{where}: needs either 'when' or 'extract'")
        for key in ("when", "unless"):
            for pattern in _as_patterns(rule.get(key)):
                try:
                    re.compile(pattern)
                except re.error as exc:
                    raise ConfigError(f"{where}: '{key}' pattern is not valid: {exc}") from exc
        # `extract` takes one pattern or a list of them - the two orders an advert
        # states a requirement in cannot share a capture group. This validator was
        # still compiling it as a single string, so from the day `extract` became a
        # list the rules file could not be saved from the interface at all: it raised
        # a TypeError rather than reporting anything. No test had ever put a shipped
        # example file through `validate`, which is the test this earned.
        for pattern in _as_patterns(rule.get("extract")):
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                raise ConfigError(f"{where}: 'extract' is not valid: {exc}") from exc
            if compiled.groups != 1:
                raise ConfigError(
                    f"{where}: each 'extract' pattern needs exactly one capturing "
                    f"group, around the number; this one has {compiled.groups}")


def _as_patterns(spec) -> list[str]:
    if spec is None:
        return []
    if isinstance(spec, str):
        return [spec]
    out = []
    for item in spec:
        if isinstance(item, dict):
            item = item.get("matches")
        if item:
            out.append(item)
    return out


def _validate_watchlist(doc: dict) -> None:
    employers = doc.get("employers")
    if not isinstance(employers, list):
        raise ConfigError("'employers' must be a list")
    keys = set()
    for index, employer in enumerate(employers, 1):
        if not isinstance(employer, dict):
            raise ConfigError(f"employer {index}: must be a mapping")
        key = employer.get("key")
        if not key:
            raise ConfigError(f"employer {index}: missing 'key'")
        if key in keys:
            raise ConfigError(f"employer '{key}': duplicate key")
        keys.add(key)
        for source in employer.get("sources") or []:
            if not isinstance(source, dict):
                raise ConfigError(f"employer '{key}': each source must be a mapping")
            if not source.get("platform") or not source.get("identifier"):
                raise ConfigError(
                    f"employer '{key}': a source needs both 'platform' and 'identifier'")


def _validate_settings(doc: dict) -> None:
    db = doc.get("database")
    if db is not None and not isinstance(db, str):
        raise ConfigError("'database' must be a path string")
    digest = doc.get("digest")
    if digest is not None and not isinstance(digest, dict):
        raise ConfigError("'digest' must be a mapping")
    views = doc.get("saved_views")
    if views is not None:
        if not isinstance(views, list):
            raise ConfigError("'saved_views' must be a list")
        names = set()
        for index, view in enumerate(views, 1):
            if not isinstance(view, dict):
                raise ConfigError(f"saved view {index}: must be a mapping")
            name = (view.get("name") or "").strip()
            if not name:
                raise ConfigError(f"saved view {index}: missing 'name'")
            if name.lower() in names:
                raise ConfigError(f"saved view '{name}': duplicate name")
            names.add(name.lower())
            if not isinstance(view.get("query") or "", str):
                raise ConfigError(f"saved view '{name}': 'query' must be a string")

    weights = (doc.get("ranking") or {}).get("weights")
    if weights is not None:
        if not isinstance(weights, dict):
            raise ConfigError("'ranking.weights' must be a mapping")
        for severity, value in weights.items():
            if not isinstance(value, int):
                raise ConfigError(f"ranking weight '{severity}' must be a whole number")


# ------------------------------------------------------------------------- writing

def save(config_dir: Path, name: str, text: str, expected_digest: str | None) -> ConfigFile:
    """Validate, guard against a concurrent edit, back up, then write atomically."""
    config_dir = Path(config_dir)
    validate(name, text)

    target = config_dir / f"{name}.yaml"
    current_text = target.read_text(encoding="utf-8") if target.exists() else ""
    current_digest = _hash(current_text)

    if expected_digest is not None and target.exists() and current_digest != expected_digest:
        raise ConflictError(
            "the file changed on disk since this form was opened",
            current_text=current_text,
            current_hash=current_digest,
        )

    if target.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(target, target.with_suffix(f".yaml.bak-{stamp}"))

    temp = target.with_suffix(".yaml.tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(target)
    return read(config_dir, name)


def patch(config_dir: Path, name: str, mutate, expected_digest: str | None) -> ConfigFile:
    """Apply a structured change while keeping comments and layout.

    Used by the form-based parts of the UI. Falls back to a plain rewrite when the
    round-trip library is unavailable, and says so rather than silently dropping
    every comment in the file.
    """
    current = read(config_dir, name)
    if _ruamel is None:
        raise ConfigError(
            "structured editing needs ruamel.yaml; edit the file as text instead "
            "(a plain rewrite here would strip every comment)")
    import io

    doc = _ruamel.load(current.text) or {}
    mutate(doc)
    buffer = io.StringIO()
    _ruamel.dump(doc, buffer)
    return save(config_dir, name, buffer.getvalue(), expected_digest or current.digest)
