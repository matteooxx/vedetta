"""Workday adapter.

Where most of the large enterprises in the watched population live. Unlike the other
platforms here it is a **POST** API, which is why a straightforward GET probe found
nothing for Salesforce, Zalando, Guidewire or Zendesk during the census — they were
reachable all along.

The endpoint is `/wday/cxs/{tenant}/{site}/jobs`, takes `{limit, offset, searchText}`
and answers `{total, jobPostings:[...]}`. Twenty per page is the server's cap. Each
posting's `externalPath` leads to a detail document carrying the advert text, which
the rule engine needs for the gates that live in prose.

The source's `endpoint` is the list URL, recorded by a human during discovery. It is
not derived from the employer name: a Workday tenant and its site name are two
separate strings that no amount of guessing produces — "zendesk/zendesk" happens to
repeat, "guidewire/external" does not.
"""
from __future__ import annotations

import re
import time

import httpx

from .base import Adapter, AdapterError, RawPosting

# "2 Locations", "3 Locations": a count where a place should be.
_IS_COUNT = re.compile(r"^\s*\d+\s+locations?\s*$", re.I)

PAGE = 20             # the server's cap, regardless of what you ask for
MAX_PAGES = 40        # 800 postings
POLITE_DELAY = 0.25


class WorkdayAdapter(Adapter):
    platform = "workday"

    def fetch(self, source: dict, known_keys: set[str] | None = None,
              detail_budget: int | None = None,
              progress=None) -> list[RawPosting]:
        endpoint = source.get("endpoint")
        if not endpoint:
            raise AdapterError(
                "a workday source needs its endpoint recorded: the tenant and the "
                "site name are two separate strings and neither follows from the "
                "employer's name")
        known = known_keys or set()
        base = endpoint.rsplit("/jobs", 1)[0]
        public = _public_base(endpoint)

        with self.client() as client:
            if progress is not None:
                progress(0, None, "listing postings")
            postings = self._list(client, endpoint)
            out: list[RawPosting] = []
            spent = 0
            to_read = sum(1 for e in postings
                          if (e.get("externalPath") or "") not in known)
            for entry in postings:
                path = entry.get("externalPath") or ""
                key = path or str(entry.get("bulletFields") or entry.get("title"))
                if not key:
                    continue
                url = f"{public}{path}" if path else None

                if key in known:
                    out.append(RawPosting(platform_key=key, title="", url=url))
                    continue

                title = (entry.get("title") or "").strip()
                location = entry.get("locationsText")
                parts = [title, location]

                if path and (detail_budget is None or spent < detail_budget):
                    spent += 1
                    body, detailed = self._detail(client, base, path)
                    if body:
                        parts.append(body)
                    # The listing's "2 Locations" carries no place at all, so the
                    # detail document's version replaces it when there is one.
                    if detailed and (not location or _IS_COUNT.match(location)):
                        location = detailed
                        parts[1] = location
                    time.sleep(POLITE_DELAY)

                out.append(RawPosting(
                    platform_key=key,
                    title=title,
                    location=location,
                    url=url,
                    published_at=_posted_on(entry.get("postedOn")),
                    text=" \n".join(p for p in parts if p),
                    raw=entry,
                ))
                if progress is not None and spent:
                    progress(spent, to_read, "adverts read")
        return out

    # -------------------------------------------------------------------- listing
    def _list(self, client: httpx.Client, endpoint: str) -> list[dict]:
        collected: list[dict] = []
        offset = 0
        total: int | None = None
        for _ in range(MAX_PAGES):
            try:
                response = client.post(
                    endpoint,
                    json={"limit": PAGE, "offset": offset, "searchText": "",
                          "appliedFacets": {}},
                    headers={"Content-Type": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise AdapterError(f"transport: {type(exc).__name__}") from exc
            if response.status_code == 404:
                raise AdapterError(
                    "endpoint not found (404) - the tenant or site name is wrong, "
                    "not the employer quiet", http_status=404)
            if response.status_code != 200:
                raise AdapterError(f"HTTP {response.status_code}",
                                   http_status=response.status_code)
            try:
                payload = response.json()
            except ValueError as exc:
                raise AdapterError("response was not JSON") from exc

            page = payload.get("jobPostings")
            if page is None:
                raise AdapterError("response had no 'jobPostings' key")
            collected.extend(page)
            # Workday reports `total` on the FIRST page only; every later page says
            # 0. Trusting it per page makes the loop stop after two pages and return
            # a third of the board, silently - 40 postings out of 127 when this was
            # found. The first page's figure is kept and used instead.
            if total is None:
                total = payload.get("total") or None
            offset += PAGE
            if len(page) < PAGE or (total is not None and offset >= total):
                break
            time.sleep(POLITE_DELAY)
        if total is not None and len(collected) < total:
            # Said out loud rather than returned quietly: a partial board looks
            # exactly like an employer that has fewer openings than it does.
            raise AdapterError(
                f"listing stopped at {len(collected)} of {total} postings - "
                f"pagination is incomplete, which is not the same as a small board")
        return collected

    # --------------------------------------------------------------------- detail
    def _detail(self, client: httpx.Client, base: str,
                path: str) -> tuple[str | None, str | None]:
        """Return (advert text, real location).

        A failure is survivable and deliberately quiet: the posting is still recorded
        and still shown, just with fewer labels. Discarding it because its
        description would not load would turn a minor fault into a missing opening.

        The location matters as much as the text here. Workday's listing hides
        multi-site postings behind "2 Locations" — 42 of 127 on the first board
        tested, a third of it — and a posting with no parseable place cannot be
        filtered by the facet that matters most.
        """
        try:
            response = client.get(f"{base}{path}")
            if response.status_code != 200:
                return None, None
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None, None
        info = payload.get("jobPostingInfo") or {}

        text = _plain(info.get("jobDescription") or "") or None

        places: list[str] = []
        primary = info.get("location")
        if isinstance(primary, str) and primary.strip():
            places.append(primary.strip())
        for extra in info.get("additionalLocations") or []:
            if isinstance(extra, str) and extra.strip():
                places.append(extra.strip())
        if info.get("remoteType"):
            places.append("Remote")
        return text, "; ".join(dict.fromkeys(places)) or None


def _public_base(endpoint: str) -> str:
    """Turn the API endpoint into the page a human opens.

    `https://x.wd1.myworkdayjobs.com/wday/cxs/x/Site/jobs` becomes
    `https://x.wd1.myworkdayjobs.com/Site`, which is where `externalPath` hangs off.
    """
    match = re.match(r"(https://[^/]+)/wday/cxs/[^/]+/([^/]+)/jobs", endpoint)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    return endpoint.rsplit("/wday/", 1)[0]


def _posted_on(value) -> str | None:
    """Workday reports recency as prose: "Posted 3 Days Ago", "Posted Today".

    Converted to a day offset the rest of the system can order by. Only the shapes
    actually observed are handled; anything else is left alone rather than guessed,
    because a wrong date silently changes what counts as new.
    """
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    lowered = text.lower()
    from datetime import date, timedelta

    if "today" in lowered:
        return date.today().isoformat()
    if "yesterday" in lowered:
        return (date.today() - timedelta(days=1)).isoformat()
    match = re.search(r"(\d+)\+?\s*(day|week|month)", lowered)
    if match:
        count = int(match.group(1))
        unit = match.group(2)
        days = count * {"day": 1, "week": 7, "month": 30}[unit]
        return (date.today() - timedelta(days=days)).isoformat()
    return None


_ENTITIES = {"&lt;": "<", "&gt;": ">", "&amp;": "&", "&quot;": '"', "&#39;": "'",
             "&nbsp;": " "}


def _plain(html: str) -> str:
    text = html if isinstance(html, str) else str(html)
    for entity, char in _ENTITIES.items():
        text = text.replace(entity, char)
    text = re.sub(r"<[^>]{0,300}>", " ", text)
    return re.sub(r"\s+", " ", text).strip()
