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

from . import places as places_mod
from . import regions as regions_mod
from .labels.engine import Label

SPLIT = re.compile(r"[;/|]|,\s*(?=[A-Z])|\s+(?:and|or)\s+", re.I)
PARENS = re.compile(r"[()\[\]]")

# Verdict strength, strongest first. A multi-location posting takes the best of its
# locations: one workable office is enough to make the posting workable.
ORDER = ("preferred", "acceptable", "conditional", "excluded")


def _text_match(target: str, text: str) -> bool:
    """Substring for an ordinary place name, whole word for a short one.

    Substring matching is what makes "Ireland" catch "Remote - Ireland" and "Dublin"
    catch "Dublin Hub", and it is worth keeping. It stops being safe below about four
    characters: "US" is inside "Prussia" and "EU" is inside "Eusebio".
    """
    if len(target) > 3:
        return target in text
    return re.search(rf"(?<![a-z]){re.escape(target)}(?![a-z])", text) is not None


def _at_most_acceptable(bucket: str) -> str:
    """A verdict derived from a region never reaches the top bucket.

    `preferred` means the posting is in a place the reader wants to be. A posting
    open to all of EMEA is not in Dublin; it would simply allow Dublin. Reporting it
    as preferred would put it at the top of the digest on a claim the posting never
    made.
    """
    return "acceptable" if bucket == "preferred" else bucket


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
        """Return (verdict, what decided it).

        Multi-location postings are common and are written half a dozen ways:
        "Remote, Canada; Remote, United Kingdom", "United States (Remote)",
        "GB-London", "Home Based - APAC; Home based - EMEA". Each fragment is judged
        and the **best** verdict wins, because one workable office makes the posting
        workable.

        Within one fragment the **most specific** match wins instead, which matters
        as soon as a rule can name a whole region. A profile saying `Europe` is
        acceptable and `United Kingdom` is conditional has to read a London posting
        as conditional: without that, the broad rule would silently erase the visa
        warning on the narrow one. Specificity is scored in two parts - whether the
        platform stated the place or this module inferred it, and whether the rule
        names the place itself or a region containing it.

        An unrecognised or missing location is `unknown`, never `excluded`. Guessing
        it away would be the silent-drop failure in miniature.
        """
        if not location or not location.strip():
            return "unknown", None

        text = PARENS.sub(" ", location)
        fragments = [f.strip() for f in SPLIT.split(text) if f.strip()]
        if not fragments:
            fragments = [text.strip()]

        best, matched, best_specificity = None, None, -1
        for fragment in fragments:
            verdict, hit, specificity = self._judge_fragment(fragment)
            if verdict is None:
                continue
            better = best is None or ORDER.index(verdict) < ORDER.index(best)
            # On a tie, the fragment that needed less inference explains it. Both
            # fragments of "Milan, Italy" say acceptable; the label should read
            # "Italy", not "Italy, inferred from Milan".
            clearer = (verdict == best and specificity > best_specificity)
            if better or clearer:
                best, matched, best_specificity = verdict, hit, specificity

        if best is None:
            lowered = location.lower()
            if self.remote_counts_as_acceptable and "remote" in lowered:
                # "Remote" with no country attached: treat as workable but say so.
                return "acceptable", "remote, country unstated"
            return "unknown", None
        return best, matched

    def _judge_fragment(self, fragment: str) -> tuple[str | None, str | None, int]:
        """Judge one fragment. Returns (verdict, what decided it, specificity).

        Four ways a fragment can be judged, in descending order of how much is being
        taken on trust:

        4. the rule names the place and the platform stated it - "United States"
           against "Austin, Texas, United States";
        3. the rule names the place and this module inferred it from a city or a
           state - "United States" against "San Francisco", which the platform never
           said - or the platform named a region and the verdict comes from the
           countries inside it. "EMEA" is worth the best verdict among European,
           Middle Eastern and African countries, so a role open to all of EMEA reads
           acceptable because it can be done from Milan. 95 postings name only a city
           and 63 name only a region; nothing else reaches either group;
        2. the rule names a region containing a stated place - `EU` against
           "Bulgaria", which is how twenty-seven countries get written in one line,
           including the ones the reader never thought to list;
        1. the rule names a region containing an *inferred* place - `EU` against
           Bulgaria worked out from "Sofia". Two inferences stacked, so it ranks
           last and only decides when nothing clearer does.

        The text was once matched as a raw substring and nothing else, which caught
        "Austin, Texas, United States" and missed "Denver, Colorado, USA" entirely -
        26 postings in a country the reader cannot work in sat in the workable list.
        """
        lowered = fragment.lower()
        stated = [place for place in places_mod.extract(fragment)[0]]
        stated_lower = {place.lower() for place in stated}

        # A country this module worked out from a city or a subdivision, used only
        # when the fragment names no country of its own. This is the one guess here
        # that can exclude a posting, so what it was inferred from is carried into
        # the label: an exclusion the reader cannot see the reasoning for is one they
        # cannot argue with.
        inferred: list[tuple[str, str]] = []
        if not any(place in regions_mod.CITY_COUNTRY.values() for place in stated):
            for place in stated:
                country = regions_mod.infer_country(place)
                if country is not None and country.lower() not in stated_lower:
                    inferred.append((country, place))

        candidates: list[tuple[int, str, str]] = []   # (specificity, verdict, hit)
        for bucket in ORDER:
            for needle in getattr(self, bucket):
                target = needle.lower()
                is_group_needle = regions_mod.is_group(needle)
                rule_countries = ({c.lower() for c in regions_mod.countries_in(needle)}
                                  if is_group_needle else None)

                # A region name is NEVER matched as a substring of the raw text.
                # "EU" inside "Eusebio, Ceara, Brazil" made a Brazilian posting
                # acceptable, and "EU" inside "Seoul Teugbyeolsi" did the same for
                # Korea. A two-letter group name is a substring of a great many
                # place names, and the rule it belongs to is the broadest in the
                # file - the two together are how a whole continent gets let in.
                #
                # Short needles get a word boundary for the same reason: "US" would
                # otherwise be found inside "Prussia".
                if target in stated_lower or (
                        not is_group_needle and _text_match(target, lowered)):
                    candidates.append((4, bucket, needle))
                    continue

                for country, source in inferred:
                    if country.lower() == target:
                        candidates.append(
                            (3, bucket, f"{needle}, inferred from {source}"))

                # The platform named a region: judge the countries inside it. Capped
                # at `acceptable`, because a role open to a whole region is not *in*
                # the reader's preferred city - it merely permits it, and reporting
                # "in a preferred location (Dublin)" for a worldwide-remote posting
                # would be a claim the posting never made.
                for place in stated:
                    if not regions_mod.is_platform_region(place):
                        continue
                    inside = regions_mod.countries_in(place)
                    derived = _at_most_acceptable(bucket)
                    if any(country.lower() == target for country in inside):
                        candidates.append((3, derived, f"{needle}, via {place}"))
                    elif rule_countries is not None and (
                            rule_countries & {c.lower() for c in inside}):
                        # A region on both sides: APAC in the posting against Asia in
                        # the profile. Neither names a country, so nothing above
                        # catches it, and these are a third of the postings this
                        # whole feature exists for.
                        candidates.append((2, derived, f"{needle}, via {place}"))

                # The rule named a region: does it contain anything here?
                if rule_countries is not None:
                    for place in stated:
                        if place.lower() in rule_countries:
                            candidates.append((2, bucket, f"{needle}, via {place}"))
                    for country, source in inferred:
                        if country.lower() in rule_countries:
                            # One below a stated place matched the same way: both
                            # are a region rule, but one of them took a city on
                            # trust. "Austin, Texas, United States" should explain
                            # itself through the country the platform printed, not
                            # through the city this module looked up.
                            candidates.append(
                                (1, bucket, f"{needle}, via {country} "
                                            f"inferred from {source}"))

        if not candidates:
            return None, None, 0
        # Most specific first; among equals, the better verdict.
        candidates.sort(key=lambda c: (-c[0], ORDER.index(c[1])))
        specificity, verdict, hit = candidates[0]
        return verdict, hit, specificity

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
        # Recomputed here because this may be called with a label list that was never
        # passed through the labeller - but only added if it is not already there.
        # It was added unconditionally, and since label_posting does pass it through,
        # every excluded posting read "matched none of your target role clusters;
        # matched none of your target role clusters" in the digest and in the
        # interface. Cosmetic, and it undermines the one thing the reason line is
        # for: being read.
        seen = {l.rule_id for l in out}
        extra = self.track_label(labels)
        if extra is not None and extra.rule_id in wanted and extra.rule_id not in seen:
            out.append(extra)
        return out

    def is_workable(self, labels: list[Label]) -> bool:
        return not self.blocked_by(labels)
