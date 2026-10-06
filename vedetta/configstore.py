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
"""
from __future__ import annotations

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

EDITABLE = ("settings", "watchlist", "rules")


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


def read(config_dir: Path, name: str) -> ConfigFile:
    if name not in EDITABLE:
        raise ConfigError(f"unknown configuration file: {name}")
    path, is_example = resolve(Path(config_dir), name)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return ConfigFile(name=name, path=path, text=text, digest=_hash(text), is_example=is_example)


# --------------------------------------------------------------------- validation

_YEARS = re.compile(r"\(\?i\)|\(\?:|\\")  # presence of regex syntax, used as a hint


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

    if name == "rules":
        _validate_rules(doc)
    elif name == "watchlist":
        _validate_watchlist(doc)
    elif name == "settings":
        _validate_settings(doc)
    return doc


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
        if rule.get("extract"):
            try:
                re.compile(rule["extract"])
            except re.error as exc:
                raise ConfigError(f"{where}: 'extract' is not valid: {exc}") from exc


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
