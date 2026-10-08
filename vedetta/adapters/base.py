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
from dataclasses import dataclass, field
from typing import Any

import httpx

USER_AGENT = (
    "vedetta/0.1 (self-hosted personal job-posting monitor; "
    "one request per employer per day)"
)


@dataclass
class RawPosting:
    platform_key: str
    title: str
    location: str | None = None
    url: str | None = None
    published_at: str | None = None
    text: str = ""
    raw: dict = field(default_factory=dict)

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

    def __init__(self, timeout: float = 25.0):
        self.timeout = timeout

    def client(self) -> httpx.Client:
        return httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
            timeout=self.timeout,
        )

    def fetch(self, source: dict, known_keys: set[str] | None = None,
              detail_budget: int | None = None,
              progress=None) -> list[RawPosting]:  # pragma: no cover
        """Return one posting per opening on this source.

        ``known_keys`` are the platform keys already recorded for this source. An
        adapter that has to fetch a second request per posting to get its text uses
        this to avoid re-reading what it already knows, emitting a minimal entry
        instead so the posting is not mistaken for closed.

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
