"""Greenhouse job board adapter.

Chosen as the first adapter because it reaches the largest share of the verified
population: 22 of the 57 employers confirmed reachable during design.

The public board endpoint needs no authentication and supplies a stable integer id
and an ``updated_at`` timestamp, so "what is new" is a set difference on a primary
key rather than a comparison of text.
"""
from __future__ import annotations

import httpx

import re

from .base import Adapter, AdapterError, RawPosting

BASE = "https://boards-api.greenhouse.io/v1/boards/{identifier}/jobs"


class GreenhouseAdapter(Adapter):
    platform = "greenhouse"

    def fetch(self, source: dict) -> list[RawPosting]:
        identifier = source["identifier"]
        url = source.get("endpoint") or BASE.format(identifier=identifier)
        # content=true returns the description, which the rule engine needs to see
        # gate wording rather than only the title.
        url = url + ("&" if "?" in url else "?") + "content=true"

        with self.client() as client:
            try:
                response = client.get(url)
            except (httpx.HTTPError, httpx.StreamError) as exc:
                raise AdapterError(f"transport: {type(exc).__name__}") from exc

            if response.status_code == 404:
                raise AdapterError(
                    f"board '{identifier}' not found (404) - the identifier is wrong, "
                    "not the employer quiet",
                    http_status=404,
                )
            if response.status_code != 200:
                raise AdapterError(f"HTTP {response.status_code}", http_status=response.status_code)

            try:
                payload = response.json()
            except ValueError as exc:
                raise AdapterError("response was not JSON", http_status=response.status_code) from exc

        jobs = payload.get("jobs")
        if jobs is None:
            raise AdapterError("response had no 'jobs' key")

        out: list[RawPosting] = []
        for job in jobs:
            location = (job.get("location") or {}).get("name")
            content = job.get("content") or ""
            out.append(
                RawPosting(
                    platform_key=str(job.get("id")),
                    title=(job.get("title") or "").strip(),
                    location=location,
                    url=job.get("absolute_url"),
                    published_at=job.get("first_published") or job.get("updated_at"),
                    # The rule engine reads title, location and description together.
                    text=" \n".join(filter(None, [job.get("title"), location, _unescape(content)])),
                    raw=job,
                )
            )
        return out


_ENTITIES = {
    "&lt;": "<", "&gt;": ">", "&amp;": "&", "&quot;": '"', "&#39;": "'",
    "&nbsp;": " ", "&rsquo;": "'", "&ldquo;": '"', "&rdquo;": '"',
}


def _unescape(html: str) -> str:
    """Greenhouse returns the description as escaped HTML. Flatten it to text.

    Crude on purpose: the rule engine matches words, so tag soup only has to stop
    being tag soup, not become well-formed prose.
    """
    text = html
    for entity, char in _ENTITIES.items():
        text = text.replace(entity, char)
    text = re.sub(r"<[^>]{0,200}>", " ", text)
    return re.sub(r"\s+", " ", text).strip()
