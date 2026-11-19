"""Adapter interface.

An adapter speaks to one hiring platform, not to one employer. That is the whole
economy of this design: one adapter reaches every employer hosted on that platform.

An adapter never decides whether a posting is interesting. It returns what the
platform said, verbatim, plus a stable key.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

# What this says has to be TRUE, because it is a claim made to the people whose
# servers we are reading, in the one place they will look.
#
# It used to end with "one request per employer per day". That was false. A Workday
# poll sends one listing request plus up to `detail_budget` detail requests - 150 on a
# normal run (`run.py`), and NO limit on a seeding run - so up to 151 per employer per
# day, and more the first time. The sitemap adapter fetches a page per advert as well.
# A quantitative promise nobody checks drifts into a lie the moment the code grows a
# budget, so what is left is only what the code actually guarantees: there is no
# concurrency anywhere in the HTTP layer, so the requests do arrive one at a time.
USER_AGENT = (
    "vedetta/0.1 (self-hosted personal job-posting monitor; "
    "requests sent one at a time)"
)

# Statuses that mean "ask again", not "the answer is no". 500/502/503/504 are a load
# balancer or an application having a moment. A 404 is absent from this set on purpose:
# asking a wrong URL three times does not make it right, and the Workday adapter reads a
# 404 as a misrecorded tenant rather than a quiet employer.
#
# 429 is here CONDITIONALLY, and `retrying` is where the condition lives. A 429 that
# carries `Retry-After` is what the comment above always assumed: the platform asking us
# to wait a stated amount, which is worth honouring. A 429 with NO `Retry-After` is
# something else, and on 18 November 2026 four Workday tenants showed what: a Cloudflare
# block page, 28,626 bytes of HTML returned with status 429, to a single request sent
# cold. Nothing was being throttled - the client was being refused. Retrying that twice
# more asks a server that just said no the same question three times, which is how a
# polite crawler becomes a blocked one. The exact thing this module says it avoids.
RETRY_ON = frozenset({429, 500, 502, 503, 504})

# Three attempts in all. Enough to ride out the single blip that is most of what goes
# wrong when reading somebody else's careers page, and few enough that a board which
# is genuinely down costs seconds rather than minutes - forty employers polled in
# series means one slow adapter delays all the ones after it.
RETRIES = 2
BACKOFF = 1.5        # seconds before the second attempt, doubled before the third
BACKOFF_CAP = 20.0   # however long a Retry-After asks for, this is the limit


def _retry_after(response: httpx.Response) -> float | None:
    """`Retry-After` in seconds, when the platform sent a usable one.

    Honoured because 429 is a request, not an error, and ignoring it is how a polite
    crawler becomes a blocked one. Only the delta-seconds form is read - the HTTP-date
    form is rare here - and an absurd value is dropped rather than slept through.
    """
    raw = (response.headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    if seconds <= 0:
        return None
    return min(seconds, BACKOFF_CAP)


@dataclass
class RawPosting:
    platform_key: str
    title: str
    location: str | None = None
    url: str | None = None
    published_at: str | None = None
    text: str = ""
    raw: dict = field(default_factory=dict)
    # "Still there, not re-read": a key from `known_keys`, emitted with no payload so
    # the posting is not taken for closed. See `Adapter.fetch`.
    resighting: bool = False

    def content_hash(self) -> str:
        blob = json.dumps(
            [self.title, self.location, self.url, self.published_at],
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


class AdapterError(RuntimeError):
    """Raised for a failure that should be recorded, not swallowed."""

    def __init__(self, message: str, http_status: int | None = None):
        super().__init__(message)
        self.http_status = http_status


class Adapter:
    platform: str = "base"
    # The source keys this adapter reads beyond the generic ones every source has
    # (platform, identifier, endpoint, the verification fields). The watchlist
    # validator refuses any of them on a source of another platform, by name: a key
    # the adapter never reads saves cleanly and then does nothing.
    params: frozenset[str] = frozenset()

    def __init__(self, timeout: float = 25.0):
        self.timeout = timeout
        # Things that went oddly without going wrong. An adapter appends to this and
        # the caller records it against the poll, which is how a listing that was
        # demonstrably short gets reported without being called a failure.
        #
        # The alternative was to raise, and that is what the Workday adapter used to
        # do for a board one posting shorter than its own declared total: a large
        # board that changed while being read. The postings were thrown away over it
        # and the digest said "1 source failing", which is how a reader learns to
        # stop reading the failures.
        self.notes: list[str] = []
        # Whether the listing itself is in doubt. Separate from the notes, and the
        # distinction is load-bearing: the caller refuses to close any posting for a
        # source whose listing was incomplete, because a posting absent from a short
        # listing may still be open.
        #
        # The first version had only the notes, and inferred incompleteness from any
        # note existing. The sitemap adapter then reported, correctly and on every
        # run, that it had chosen one of two translated sitemaps - a complete listing
        # with something worth saying about it - and Cisco would never have closed a
        # posting again.
        self.incomplete = False
        self.refusals: list[str] = []
        self._refusal_note: int | None = None

    def refused(self, what: str) -> None:
        """A request refused outright, summed up into ONE note rather than many.

        Two reasons it works this way and not by adding a note each time.

        A Workday board whose detail documents are being refused produces one of these
        PER ADVERT. A real poll of Zalando wrote six copies of the same sentence,
        1,100 characters for one fact, and this module argues in three other comments
        that a notice nobody finishes reading is worse than none at all.

        And it lands in `self.notes` rather than in a method of its own because
        `notes` is the whole surface the caller touches - the suite's stand-in adapters
        implement `notes` and `incomplete` and nothing else, by design, and a new
        method here would break twenty-four of them while testing nothing extra. The
        same reasoning the `retrying` docstring gives for taking a callable.
        """
        self.refusals.append(what)
        n = len(self.refusals)
        examples = ", ".join(self.refusals[:2])
        rest = f" and {n - 2} more" if n > 2 else ""
        if n == 1:
            subject, tail = "1 request was", "it was"
        else:
            subject, tail = f"{n} requests were", "they were"
        line = (f"{subject} refused with 429 and no Retry-After, so {tail} not "
                f"asked again: {examples}{rest}")
        if self._refusal_note is None:
            self._refusal_note = len(self.notes)
            self.notes.append(line)
        else:
            self.notes[self._refusal_note] = line

    def note(self, message: str, incomplete: bool = False) -> None:
        """Record something that went oddly without going wrong.

        `incomplete=True` also says the listing cannot be trusted to be the whole
        board, which is a statement about what may be concluded from an absence, not
        about severity.
        """
        self.notes.append(message)
        if incomplete:
            self.incomplete = True

    def client(self) -> httpx.Client:
        return httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
            timeout=self.timeout,
        )

    @staticmethod
    def _retry_note(what: str, shrugged_off: list[str], response) -> str:
        """What the record should say about a request that took more than one attempt.

        It used to say "the retry is what produced this listing" in every case, which
        is false whenever the attempts ran out. On 18 November 2026 a real poll of
        Zalando wrote exactly that about seven adverts whose three attempts had each
        answered 429: the note claimed a rescue that never happened, in the one place
        a reader goes to find out whether a board can be trusted.

        So the claim is now made only when the last answer is one the caller can use.
        """
        tried = ", ".join(shrugged_off)
        if response.status_code == 200:
            return (f"{what} answered {tried} before answering 200; the retry is what "
                    f"produced this listing")
        return (f"{what} answered {tried} and then {response.status_code}; "
                f"the attempts were spent and this is the answer we kept")

    def retrying(self, send, what: str, retries: int = RETRIES) -> httpx.Response:
        """Call ``send()`` again if what came back looks transient.

        Why this exists: a single dropped connection or one 503 from a load balancer
        was enough to fail a whole source for the day. The poll was recorded as an
        error, the employer appeared in the digest as failing, and `close_missing`
        would not retire any of its postings - all because of a blip that would have
        gone away on a second attempt a second and a half later. Reading somebody
        else's careers page is brittle by nature; not retrying made every brittle
        moment a reported fault, which is the fastest way to teach the reader to stop
        reading the faults.

        What it deliberately does NOT do:

        * It does not retry a status that will not change. See ``RETRY_ON``.
        * It does not hide what happened. A request that only succeeded on a later
          attempt leaves a note, so "that board is flaky" is something the record can
          show rather than something the reader has to remember.
        * It does not mark the listing incomplete. A retry that worked produced the
          whole answer, and setting ``incomplete`` would stop this source ever
          closing a posting again.

        A response whose status is still unacceptable after the last attempt is
        **returned**, not raised on, so the caller keeps deciding what each status
        means - the Workday adapter's 404 message is about a misrecorded tenant and
        belongs with the adapter, not here.

        ``send`` is a callable rather than a method and a URL on purpose. The caller
        writes the request it was already writing - ``lambda: client.post(...)`` - so
        the client is used exactly as before, which keeps the suite's stand-in clients
        working: they implement the verbs their adapter calls and nothing else, and a
        helper that reached for ``client.request`` would break every one of them while
        testing nothing extra. ``what`` is for the note, not for the request.
        """
        delay = BACKOFF
        shrugged_off: list[str] = []
        for attempt in range(retries + 1):
            last = attempt == retries
            try:
                response = send()
            except httpx.HTTPError as exc:
                if last:
                    raise AdapterError(f"transport: {type(exc).__name__}") from exc
                shrugged_off.append(type(exc).__name__)
                wait = delay
            else:
                if last or response.status_code not in RETRY_ON:
                    if shrugged_off:
                        self.note(self._retry_note(what, shrugged_off, response))
                    return response
                asked_to_wait = _retry_after(response)
                if response.status_code == 429 and asked_to_wait is None:
                    # A refusal, not a throttle. See RETRY_ON: a 429 without
                    # `Retry-After` is what a bot-management page looks like, and
                    # asking again changes nothing except how many times we knocked.
                    # The status is returned exactly as the last attempt would have
                    # returned it, so every caller behaves as before - what changes is
                    # that the other two requests are never sent.
                    #
                    # The note is written even on the FIRST attempt, which is the whole
                    # difference between this and a silent saving of two requests. The
                    # Workday detail fetch swallows a non-200 on purpose - the posting
                    # is kept with fewer labels rather than dropped - so this note is
                    # the ONLY trace that an advert's text was refused rather than
                    # absent. Stopping early must not also stop saying so.
                    self.refused(
                        what + (f" (after {', '.join(shrugged_off)})"
                                if shrugged_off else ""))
                    return response
                shrugged_off.append(f"HTTP {response.status_code}")
                wait = asked_to_wait or delay

            time.sleep(wait)
            delay = min(delay * 2, BACKOFF_CAP)

        # Unreachable: the loop either returns or raises on its last pass. Spelled out
        # so a future change to the range cannot fall off the end returning None.
        raise AdapterError("retry loop ended without a response")

    def fetch(self, source: dict, known_keys: set[str] | None = None,
              detail_budget: int | None = None,
              progress=None) -> list[RawPosting]:  # pragma: no cover
        """Return one posting per opening on this source.

        ``known_keys`` are the platform keys already recorded for this source. An
        adapter that has to fetch a second request per posting to get its text uses
        this to avoid re-reading what it already knows, emitting a minimal entry
        instead so the posting is not mistaken for closed.

        That minimal entry is a **re-sighting**, and it is said with the flag:
        ``RawPosting(platform_key=key, title="", url=url, resighting=True)``. The
        runner then keeps the posting open, creates nothing, and carries the previous
        content hash forward instead of hashing the empty payload. Only flag a key
        that is in ``known_keys``: a re-sighting the database has no record of
        cannot become a posting, and is dropped with a note on the poll.

        An empty title does **not** mean re-sighting. It used to, implicitly, and a
        real new posting served without a title vanished with no trace. Now a
        non-flagged item with an empty title is dropped with a note on the poll too:
        a posting cannot be created without a title, but its absence is reported.

        ``text`` is what the body rules and the skill matcher read. Left empty, they
        read the title instead - so an adapter that has the advert text should put
        title, location and text together here, as the existing ones do.

        ``detail_budget`` caps how many of those second requests one run may make.
        ``None`` means no cap, which is what a first pass over a source wants: a cap
        there would leave the remainder to arrive as "new" tomorrow and be mailed as
        news when it is in fact history.

        ``progress`` is called as ``progress(done, total, what)`` while the adapter
        works. It matters on the slow ones: a source with 465 detail pages to read
        otherwise reports nothing for twenty minutes, which from outside is
        indistinguishable from being stuck.

        An adapter whose listing already carries everything ignores all three.
        """
        raise NotImplementedError


_WS = re.compile(r"\s+")
_BRACKET_SUFFIX = re.compile(r"\s*[\(\[][^)\]]{0,40}[\)\]]\s*$")
_GENDER_TAG = re.compile(r"\s*\(?\b[mwfdxh](?:\s*/\s*[mwfdxh]){1,3}\b\)?", re.I)
_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)


def normalise(value: str | None) -> str:
    """Conservative normalisation for reconciliation.

    Strips the gender tags that the census showed are everywhere in European
    postings -- (m/f/d), (x/f/m) -- plus one trailing bracketed suffix, punctuation
    and case. Deliberately conservative: when in doubt the caller keeps two postings
    and flags one, because merging wrongly hides a posting and hiding is the failure
    this project exists to prevent.
    """
    if not value:
        return ""
    text = _GENDER_TAG.sub(" ", value)
    text = _BRACKET_SUFFIX.sub("", text)
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip().lower()
