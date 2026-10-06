"""The profile: what the reader can actually take on.

Separate from `rules.yaml` on purpose. Rules describe how to *detect* something in a
posting's text; the profile describes *the reader* — languages, work authorisation,
level, geography. Keeping them apart means a rule can be reused by anyone while the
profile stays personal, and it gives the structured facts a structured home instead
of hiding them inside regular expressions.

**This file filters nothing.** It produces labels, and a posting that trips an
exclusion is marked `not workable` — counted, explained, and one click away. The
default view hides them so the list is usable; the count is always on screen so the
reader knows what they are not looking at.

The difference matters, and it has a date attached: on 2026-09-20 a *filtered* search
of one careers portal silently passed over an eligible vacancy, which an unfiltered
pass found an hour later. Dropping something quietly is the failure. Folding it away
behind a visible number is not.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .labels.engine import Label

SPLIT = re.compile(r"[;/|]|,\s*(?=[A-Z])|\s+(?:and|or)\s+", re.I)
PARENS = re.compile(r"[()\[\]]")

# Verdict strength, strongest first. A multi-location posting takes the best of its
# locations: one workable office is enough to make the posting workable.
ORDER = ("preferred", "acceptable", "conditional", "excluded")


@dataclass
class Profile:
    languages: list[str] = field(default_factory=list)
    years: int | None = None
    max_years_requested: int | None = None
    reject_level: list[str] = field(default_factory=list)
    accept_level: list[str] = field(default_factory=list)
    preferred: list[str] = field(default_factory=list)
    acceptable: list[str] = field(default_factory=list)
    conditional: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    remote_counts_as_acceptable: bool = True
    require_track: bool = False
    exclude_if: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    # ---------------------------------------------------------------- loading
    @classmethod
    def from_dict(cls, doc: dict | None) -> "Profile":
        doc = doc or {}
        experience = doc.get("experience") or {}
        locations = doc.get("locations") or {}
        return cls(
            languages=[str(x).lower() for x in (doc.get("identity") or {}).get("languages") or []],
            years=experience.get("years"),
            max_years_requested=experience.get("max_years_requested"),
            reject_level=[str(x).lower() for x in experience.get("reject_level") or []],
            accept_level=[str(x).lower() for x in experience.get("accept_level") or []],
            preferred=[str(x) for x in locations.get("preferred") or []],
            acceptable=[str(x) for x in locations.get("acceptable") or []],
            conditional=[str(x) for x in locations.get("conditional") or []],
            excluded=[str(x) for x in locations.get("excluded") or []],
            remote_counts_as_acceptable=bool(locations.get("remote_counts_as_acceptable", True)),
            require_track=bool((doc.get("tracks") or {}).get("require_match", False)),
            exclude_if=[str(x) for x in doc.get("exclude_if") or []],
            raw=doc,
        )

    @property
    def configured(self) -> bool:
        return bool(self.preferred or self.acceptable or self.excluded
                    or self.reject_level or self.exclude_if)

    # --------------------------------------------------------------- location
    def location_verdict(self, location: str | None) -> tuple[str, str | None]:
        """Return (verdict, the fragment that decided it).

        Multi-location postings are common and are written half a dozen ways:
        "Remote, Canada; Remote, United Kingdom", "United States (Remote)",
        "GB-London", "2 Locations". Each fragment is judged and the **best** verdict
        wins, because one workable office makes the posting workable.

        An unrecognised or missing location is `unknown`, never `excluded`. Guessing
        it away would be the silent-drop failure in miniature.
        """
        if not location or not location.strip():
            return "unknown", None

        text = PARENS.sub(" ", location)
        fragments = [f.strip() for f in SPLIT.split(text) if f.strip()]
        if not fragments:
            fragments = [text.strip()]

        best, matched = None, None
        for fragment in fragments:
            verdict, hit = self._judge_fragment(fragment)
            if verdict is None:
                continue
            if best is None or ORDER.index(verdict) < ORDER.index(best):
                best, matched = verdict, hit

        if best is None:
            lowered = location.lower()
            if self.remote_counts_as_acceptable and "remote" in lowered:
                # "Remote" with no country attached: treat as workable but say so.
                return "acceptable", "remote, country unstated"
            return "unknown", None
        return best, matched

    def _judge_fragment(self, fragment: str) -> tuple[str | None, str | None]:
        lowered = fragment.lower()
        for bucket in ORDER:
            for needle in getattr(self, bucket):
                if needle.lower() in lowered:
                    return bucket, needle
        return None, None

    # ------------------------------------------------------------------ level
    def level_verdict(self, title: str | None) -> tuple[str | None, str | None]:
        if not title:
            return None, None
        lowered = title.lower()
        for word in self.accept_level:
            if re.search(rf"\b{re.escape(word)}\b", lowered):
                return "accept", word
        for word in self.reject_level:
            if re.search(rf"\b{re.escape(word)}\b", lowered):
                return "reject", word
        return None, None

    # ----------------------------------------------------------------- labels
    def labels_for(self, title: str | None, location: str | None) -> list[Label]:
        """Structured labels, kept distinct from the regex rules by `produced_by`."""
        out: list[Label] = []

        verdict, matched = self.location_verdict(location)
        if verdict == "preferred":
            out.append(Label(rule_id="location-preferred", kind="geography",
                             severity="positive", weight=4,
                             explain=f"in a preferred location ({matched})",
                             produced_by="profile"))
        elif verdict == "acceptable":
            out.append(Label(rule_id="location-acceptable", kind="geography",
                             severity="positive", weight=2,
                             explain=f"in an acceptable location ({matched})",
                             produced_by="profile"))
        elif verdict == "conditional":
            out.append(Label(rule_id="location-conditional", kind="geography",
                             severity="warning",
                             explain=f"workable only with sponsorship ({matched})",
                             produced_by="profile"))
        elif verdict == "excluded":
            out.append(Label(rule_id="location-excluded", kind="geography",
                             severity="blocking",
                             explain=f"outside where you can work ({matched})",
                             produced_by="profile"))
        else:
            out.append(Label(rule_id="location-unknown", kind="geography",
                             severity="info", weight=0,
                             explain="location unclear - shown rather than guessed away",
                             produced_by="profile"))

        level, word = self.level_verdict(title)
        if level == "reject":
            out.append(Label(rule_id="level-too-senior", kind="gate",
                             severity="blocking", value=word,
                             explain=f"the title asks for a level above yours ({word})",
                             produced_by="profile"))
        elif level == "accept":
            # kind="note", NOT "cluster". A cluster means "the right kind of work",
            # and `tracks.require_match` asks about exactly that. Labelling the level
            # as a cluster let "Trainee Accountant" through as workable, because
            # "trainee" is an acceptable level - the same mistake that had just been
            # corrected in rules.yaml, reproduced here.
            out.append(Label(rule_id="level-suitable", kind="note",
                             severity="positive", weight=2,
                             explain=f"level matches ({word})",
                             produced_by="profile"))
        return out

    # -------------------------------------------------------------- verdict
    def track_label(self, labels: list[Label]) -> Label | None:
        """Flag a posting that matched no target role cluster.

        The inverse of the cluster rules, and the single most effective filter: a
        board of 341 postings is mostly roles in other professions entirely -
        recruiting, finance, design, renewals. Catching those by listing every job
        title that is not wanted is hopeless; requiring a positive match is not.

        It is also the filter most likely to be wrong, because it fails whenever the
        cluster rules are too narrow. That is survivable only because an excluded
        posting stays visible behind a count - which is why this option exists here
        and not as a hard filter.
        """
        if not self.require_track:
            return None
        if any(l.kind == "cluster" for l in labels):
            return None
        return Label(rule_id="no-target-track", kind="gate", severity="blocking",
                     explain="matched none of your target role clusters",
                     produced_by="profile")

    def blocked_by(self, labels: list[Label]) -> list[Label]:
        """Which labels make this posting unworkable, per `exclude_if`.

        Only the rule ids the reader listed count. A gate they did not list stays a
        warning they can see and ignore, which keeps the decision theirs.
        """
        if not self.exclude_if:
            return []
        wanted = set(self.exclude_if)
        out = [l for l in labels if l.rule_id in wanted]
        extra = self.track_label(labels)
        if extra is not None and extra.rule_id in wanted:
            out.append(extra)
        return out

    def is_workable(self, labels: list[Label]) -> bool:
        return not self.blocked_by(labels)
