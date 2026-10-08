"""SmartRecruiters adapter.

Second-largest platform in the watched population after Greenhouse, and the one that
reaches the best structural fit on the whole candidate list.

The listing is paginated and carries title, location and release date, but **not the
job advert text** — which the rule engine needs, because that is where language
requirements, sponsorship statements and seniority thresholds live. So the text comes
from a second request per posting, made only for postings not already recorded.

The listing also carries `experienceLevel` as a structured field, which is one of the
gates otherwise inferred from prose.
"""
from __future__ import annotations

import re
import time

import httpx

from .base import Adapter, AdapterError, RawPosting

LIST = "https://api.smartrecruiters.com/v1/companies/{identifier}/postings"
DETAIL = "https://api.smartrecruiters.com/v1/companies/{identifier}/postings/{posting}"

PAGE = 100            # the endpoint's maximum
MAX_PAGES = 15        # 1,500 postings is more than any watched board
POLITE_DELAY = 0.2


class SmartRecruitersAdapter(Adapter):
    platform = "smartrecruiters"

    def fetch(self, source: dict, known_keys: set[str] | None = None,
              detail_budget: int | None = None,
              progress=None) -> list[RawPosting]:
        identifier = source["identifier"]
        known = known_keys or set()

        with self.client() as client:
            if progress is not None:
                progress(0, None, "listing postings")
            listings = self._list(client, identifier)
            out: list[RawPosting] = []
            spent = 0
            # Counted over the ones needing a second request; the known ones are free
            # and including them would make a slow run look fast.
            to_read = sum(1 for e in listings
                          if str(e.get("id") or e.get("uuid") or "") not in known)
            for entry in listings:
                key = str(entry.get("id") or entry.get("uuid") or "")
                if not key:
                    continue
                if key in known:
                    out.append(RawPosting(platform_key=key, title="",
                                          url=self._public_url(entry, identifier)))
                    continue

                title = (entry.get("name") or "").strip()
                location = _location(entry.get("location"))
                text_parts = [title, location, _labels(entry)]

                if detail_budget is None or spent < detail_budget:
                    spent += 1
                    body = self._detail(client, identifier, key)
                    if body:
                        text_parts.append(body)
                    time.sleep(POLITE_DELAY)

                out.append(RawPosting(
                    platform_key=key,
                    title=title,
                    location=location,
                    url=self._public_url(entry, identifier),
                    published_at=entry.get("releasedDate") or entry.get("createdOn"),
                    text=" \n".join(p for p in text_parts if p),
                    raw=entry,
                ))
                if progress is not None and spent:
                    progress(spent, to_read, "adverts read")
        return out

    # -------------------------------------------------------------------- listing
    def _list(self, client: httpx.Client, identifier: str) -> list[dict]:
        url = LIST.format(identifier=identifier)
        collected: list[dict] = []
        offset = 0
        for _ in range(MAX_PAGES):
            try:
                response = client.get(url, params={"limit": PAGE, "offset": offset})
            except httpx.HTTPError as exc:
                raise AdapterError(f"transport: {type(exc).__name__}") from exc
            if response.status_code == 404:
                raise AdapterError(
                    f"company '{identifier}' not found (404) - the identifier is "
                    "wrong, not the employer quiet", http_status=404)
            if response.status_code != 200:
                raise AdapterError(f"HTTP {response.status_code}",
                                   http_status=response.status_code)
            try:
                payload = response.json()
            except ValueError as exc:
                raise AdapterError("response was not JSON") from exc

            page = payload.get("content")
            if page is None:
                raise AdapterError("response had no 'content' key")
            collected.extend(page)
            total = payload.get("totalFound")
            offset += PAGE
            if len(page) < PAGE or (total is not None and offset >= total):
                break
            time.sleep(POLITE_DELAY)
        return collected

    # --------------------------------------------------------------------- detail
    def _detail(self, client: httpx.Client, identifier: str, posting: str) -> str | None:
        """The advert text. A failure here is survivable and silent on purpose.

        Without it the posting is still recorded and still shown; it just carries
        fewer labels. Dropping the posting because its description would not load
        would turn a minor fault into a missing opening.
        """
        try:
            response = client.get(DETAIL.format(identifier=identifier, posting=posting))
            if response.status_code != 200:
                return None
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None

        sections = (payload.get("jobAd") or {}).get("sections") or {}
        chunks: list[str] = []
        for key in ("companyDescription", "jobDescription", "qualifications",
                    "additionalInformation"):
            section = sections.get(key) or {}
            text = section.get("text")
            if text:
                chunks.append(_plain(text))
        return " \n".join(chunks) or None

    @staticmethod
    def _public_url(entry: dict, identifier: str) -> str | None:
        ref = entry.get("ref")
        if isinstance(ref, str) and ref.startswith("http"):
            # The API's own `ref` is the API URL, not the page a human opens.
            pass
        slug = entry.get("id")
        if not slug:
            return None
        return f"https://jobs.smartrecruiters.com/{identifier}/{slug}"


def _location(raw) -> str | None:
    """Flatten into the same free text the other adapters produce.

    One location parser serves every adapter, so each one flattens into the shape
    `places.py` already understands rather than inventing a second format.
    """
    if not isinstance(raw, dict):
        return None
    bits = [raw.get("city"), raw.get("region"), raw.get("country")]
    flat = [str(b) for b in bits if b]
    if raw.get("remote"):
        flat.append("Remote")
    return ", ".join(dict.fromkeys(flat)) or None


def _labels(entry: dict) -> str:
    """Structured fields worth putting in front of the rule engine.

    `experienceLevel` in particular is a gate this platform states outright instead
    of leaving to be inferred from prose.
    """
    parts = []
    for key in ("experienceLevel", "typeOfEmployment", "department", "function",
                "industry"):
        value = entry.get(key)
        if isinstance(value, dict):
            label = value.get("label") or value.get("id")
            if label:
                parts.append(str(label))
    return " \n".join(parts)


_ENTITIES = {"&lt;": "<", "&gt;": ">", "&amp;": "&", "&quot;": '"', "&#39;": "'",
             "&nbsp;": " "}


def _plain(html: str) -> str:
    text = html
    for entity, char in _ENTITIES.items():
        text = text.replace(entity, char)
    text = re.sub(r"<[^>]{0,300}>", " ", text)
    return re.sub(r"\s+", " ", text).strip()
