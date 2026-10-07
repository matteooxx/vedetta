"""Which of a posting's technologies you already have, and which you do not.

Teal's distinctive idea, and worth taking for one reason: **it stops at showing.**
It reports a difference between two lists. It does not decide whether the difference
matters, because that is a judgement about your own experience, and a program guessing
at it would not merely be useless — it would be confidently wrong in writing, which is
exactly what ADR-0006 exists to prevent.

So: no score, no readiness percentage, no verdict. Two sets and a diff.

Matching is whole-word and case-insensitive, with a few deliberate exceptions where
the plain word boundary gets it wrong — `C++`, `CI/CD`, `.NET` and `Node.js` all
contain characters a word boundary does not respect.
"""
from __future__ import annotations

import re

# Terms whose shape defeats a plain \b...\b boundary.
AWKWARD = {
    "c++": r"c\+\+",
    "c#": r"c#",
    "f#": r"f#",
    ".net": r"\.net\b",
    "ci/cd": r"ci\s*/\s*cd",
    "node.js": r"node\.?js\b",
    "next.js": r"next\.?js\b",
    "vue.js": r"vue\.?js\b",
    "asp.net": r"asp\.net\b",
}


# A space or hyphen in the term, in either escaped or plain form. re.escape has
# changed its mind about escaping spaces across Python versions, so both are matched
# rather than assumed.
# A space or hyphen inside the term, in either escaped or plain form. Both are
# matched rather than assumed: re.escape has changed its mind about escaping spaces
# between Python versions, and assuming one spelling silently broke every multi-word
# term.
_SEPARATORS = re.compile(r"(?:\\ | |\\-|-)+")

# What a separator becomes: a space, hyphen or underscore, one or more. Written as a
# plain constant and substituted through a lambda, because a replacement string makes
# re.sub interpret its backslashes and the escaping goes wrong in a way that still
# compiles — which is exactly how this was broken twice.
_SEPARATOR_CLASS = r"[\s\-_]+"


def _pattern(term: str) -> re.Pattern:
    key = term.strip().lower()
    if key in AWKWARD:
        return re.compile(AWKWARD[key], re.I)
    body = _SEPARATORS.sub(lambda _: _SEPARATOR_CLASS, re.escape(term.strip()))
    return re.compile(rf"(?<![\w]){body}(?![\w])", re.I)


class SkillMatcher:
    def __init__(self, profile_doc: dict | None):
        skills = (profile_doc or {}).get("skills") or {}
        self.have: list[str] = [str(s) for s in skills.get("have") or []]
        self.watch: list[str] = [str(s) for s in skills.get("watch") or []]
        self._have = [(s, _pattern(s)) for s in self.have]
        self._watch = [(s, _pattern(s)) for s in self.watch]

    @property
    def configured(self) -> bool:
        return bool(self.have or self.watch)

    def compare(self, text: str | None, employer: str | None = None) -> dict:
        """Return what the posting asks for, split by whether you have it.

        `missing` is the useful half: terms the posting names that are on the watch
        list and not on yours. Terms it names that are on neither list are not
        reported, because an unknown word is far more likely to be prose than a
        technology, and guessing would fill the result with noise.
        """
        body = text or ""
        if not body or not self.configured:
            return {"matched": [], "missing": [], "configured": self.configured}
        # An employer's own name is not a useful signal about an employer. Every
        # GitLab posting mentions GitLab, which was true, unavoidable, and filled a
        # fifth of the facet list with nothing.
        own = (employer or "").strip().lower()
        matched = [term for term, pattern in self._have
                   if pattern.search(body) and term.strip().lower() != own]
        missing = [term for term, pattern in self._watch
                   if pattern.search(body) and term.strip().lower() != own]
        return {"matched": matched, "missing": missing, "configured": True}


def summarise(comparison: dict) -> str | None:
    """A single line for the digest. Deliberately plain arithmetic, no judgement."""
    if not comparison.get("configured"):
        return None
    matched = comparison.get("matched") or []
    missing = comparison.get("missing") or []
    if not matched and not missing:
        return None
    parts = []
    if matched:
        parts.append(f"you have: {', '.join(matched[:6])}"
                     + (f" +{len(matched) - 6}" if len(matched) > 6 else ""))
    if missing:
        parts.append(f"not on your list: {', '.join(missing[:6])}"
                     + (f" +{len(missing) - 6}" if len(missing) > 6 else ""))
    return " · ".join(parts)
