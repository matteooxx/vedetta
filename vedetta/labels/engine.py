"""The rule engine.

Rules are data, never code (ADR-0013): adding a gate is editing a YAML file, and
every label carries the rule's own human-readable explanation so a low-ranked
posting can be argued with.

Three rule shapes:

``when`` / ``unless``
    Regular expressions. ``unless`` is what separates a blocking requirement from a
    desirable one -- "French required" versus "French is a strong asset" -- which is
    the single distinction that decides whether a posting is alive or dead.

``extract`` + ``compare``
    Pull a number out of the text and compare it against a profile field, for
    seniority thresholds. ``extract`` takes one pattern or a list of them, each with
    exactly one capturing group around the number. ``compare.ignore_above`` discards
    a figure too large to be a real requirement before the comparison, because the
    largest match is the one used and a company's "40 years of innovation" otherwise
    outranks the "3+ years of experience" beside it.

``field``
    Which part of the posting the rule reads: ``title``, ``body`` or ``all``
    (the default). This exists because the first real run labelled a "Senior Backend
    Engineer" as early-career: the word "graduate" appears in almost every long job
    description's boilerplate. A level or cluster rule usually belongs on the title;
    a gate usually needs the body.

``kind`` / ``severity``
    Carried through to the label. Severity never hides a posting; it only orders it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class Label:
    rule_id: str
    kind: str
    severity: str
    explain: str
    value: str | None = None
    produced_by: str = "rules"
    confidence: float | None = None
    weight: int | None = None   # per-rule override of the severity default


def _patterns(spec: Any) -> list[re.Pattern]:
    """Accept a string, a list of strings, or a list of {matches: ...} mappings."""
    if spec is None:
        return []
    if isinstance(spec, str):
        spec = [spec]
    out = []
    for item in spec:
        if isinstance(item, dict):
            item = item.get("matches")
        if item:
            out.append(re.compile(item))
    return out


class RuleEngine:
    def __init__(self, config: dict):
        self.profile: dict = config.get("profile") or {}
        self.rules: list[dict] = config.get("rules") or []
        self._compiled = []
        for rule in self.rules:
            self._compiled.append(
                {
                    "raw": rule,
                    "when": _patterns(rule.get("when")),
                    "unless": _patterns(rule.get("unless")),
                    # A list, like `when` and `unless`, because the two orders an
                    # advert states a requirement in ("5+ years of experience" and
                    # "experience: 5+ years") cannot share one capture group.
                    "extract": _patterns(rule["extract"]) if rule.get("extract") else None,
                }
            )

    def apply(self, text: str, title: str | None = None) -> list[Label]:
        """Apply every rule.

        ``title`` is optional only for convenience in tests; in a real run it is
        always supplied, because field scoping is what keeps boilerplate from
        producing confident nonsense.
        """
        body = text or ""
        title = title if title is not None else body
        scopes = {"title": title, "body": body,
                  "all": title + chr(10) + body}

        labels: list[Label] = []
        for item in self._compiled:
            rule = item["raw"]
            if not rule.get("id"):
                continue
            subject = scopes.get(rule.get("field", "all"), scopes["all"])
            label = self._evaluate(item, rule, subject)
            if label:
                labels.append(label)
        return labels

    def _evaluate(self, item: dict, rule: dict, text: str) -> Label | None:
        if item["extract"] is not None:
            return self._evaluate_numeric(item, rule, text)

        if not item["when"]:
            return None
        if not any(p.search(text) for p in item["when"]):
            return None
        # An `unless` hit means the requirement is desirable, not mandatory.
        if any(p.search(text) for p in item["unless"]):
            return None
        return Label(
            rule_id=rule["id"],
            kind=rule.get("kind", "note"),
            severity=rule.get("severity", "info"),
            explain=rule.get("explain", rule["id"]),
            weight=rule.get("weight"),
        )

    def _evaluate_numeric(self, item: dict, rule: dict, text: str) -> Label | None:
        found: list[int] = []
        for pattern in item["extract"]:
            found.extend(int(m) for m in pattern.findall(text) if m.isdigit())
        if not found:
            return None
        compare = rule.get("compare") or {}
        field = compare.get("field")
        limit = self.profile.get(field) if field else compare.get("value")
        if limit is None:
            return None

        # An implausible figure is dropped rather than compared, and `max` below is
        # why it has to be. Several Cisco adverts produced "asks for more years than
        # you have: 40" - a company founded in 1984 writing "40 years of innovation"
        # in its own boilerplate. No advert asks for forty years of anything, and
        # taking the largest match means one stray number outranks the real
        # requirement sitting next to it.
        #
        # A ceiling cannot be the only defence, because it only catches the absurd:
        # "15 years of partnership" would still read as a requirement. The pattern
        # has to insist on the word experience, which it now does. This is the second
        # line, kept because every pattern here has eventually been wrong about
        # something.
        ceiling = compare.get("ignore_above")
        if ceiling is not None:
            plausible = [v for v in found if v <= ceiling]
            if not plausible:
                return None
            found = plausible
        value = max(found)
        op = compare.get("operator", "gt")
        hit = (value > limit) if op == "gt" else (value < limit) if op == "lt" else (value == limit)
        if not hit:
            return None
        return Label(
            rule_id=rule["id"],
            kind=rule.get("kind", "gate"),
            severity=rule.get("severity", "warning"),
            explain=rule.get("explain", rule["id"]),
            value=str(value),
            weight=rule.get("weight"),
        )


SEVERITY_WEIGHT = {"positive": 3, "info": 0, "warning": -2, "blocking": -6}


def score(labels: list[Label], weights: dict | None = None) -> int:
    """A transparent sum over labels.

    Deliberately arithmetic over visible facts rather than a learned or embedded
    similarity: the resulting order has to be explainable in one line in the digest
    and disagreed with (ADR-0006).
    """
    table = dict(SEVERITY_WEIGHT)
    if weights:
        table.update(weights)
    # A rule may override its severity's weight. This exists because the first real
    # run put "Associate Renewals Manager" at the top: an early-career signal alone
    # scored the same as being in a target role cluster. Being the right LEVEL is a
    # modifier; being the right KIND OF WORK is the point.
    return sum(l.weight if l.weight is not None else table.get(l.severity, 0)
               for l in labels)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
