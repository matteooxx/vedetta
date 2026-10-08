"""Sitemap + schema.org adapter: the one that does not care what software an
employer bought.

Most careers sites publish `sitemap.xml` listing every job URL, and their detail
pages carry schema.org `JobPosting` markup because Google for Jobs rewards it. That
combination is a complete monitoring path needing **no API, no tenant and no
identifier** — which is the problem that produced an asphalt contractor in place of
an asset manager everywhere else in this project.

Two properties make it cheap as well as general:

**One request gives the whole set.** The sitemap *is* the list of postings, so "what
is new" is a set difference over URLs. Detail pages are fetched only for URLs that
are actually new, so on a quiet day an employer costs one small XML file.

**The key is the URL**, which is stable and needs no guessing.

Its one catch, learned the hard way: the pattern separating job pages from content
pages **must be configured per source**. A single global pattern was wrong in both
directions within an hour of testing — too loose it matched `careers-blog`, too
strict it lost an employer whose jobs live at `/careers/<uuid>`.
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import urljoin, urlparse

import httpx

from .base import Adapter, AdapterError, RawPosting

LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
IS_INDEX = re.compile(r"<sitemapindex", re.I)
LD_BLOCK = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)
SITEMAP_LINE = re.compile(r"(?im)^\s*sitemap:\s*(\S+)")

# A path segment that is a language or a locale code: en, fr, en-gb, pt_BR. Used to
# recognise two sitemaps as translations of each other, never to rewrite a URL that
# gets fetched.
_LOCALE_CODE = re.compile(r"^[a-z]{2}([-_][a-z]{2})?$", re.I)

# Guard rails. A careers sitemap index can fan out a long way, and this runs daily
# against someone else's server.
MAX_SITEMAP_FETCHES = 12
MAX_URLS = 4000
POLITE_DELAY = 0.35


class SitemapAdapter(Adapter):
    platform = "sitemap"

    def fetch(self, source: dict, known_keys: set[str] | None = None,
              detail_budget: int | None = 150,
              progress=None) -> list[RawPosting]:
        """Return one posting per job URL.

        ``known_keys`` are URLs already recorded for this source: they are emitted
        without fetching their detail page, because nothing about them has to be
        re-read. ``detail_budget`` caps how many new detail pages one run will
        fetch; ``None`` means no cap, which is what a first pass over a source
        wants.
        """
        known = known_keys or set()
        host_url = source.get("endpoint") or self._guess(source["identifier"])
        origin = f"{urlparse(host_url).scheme}://{urlparse(host_url).netloc}"

        include = re.compile(source["job_url_pattern"]) if source.get("job_url_pattern") else None
        if include is None:
            raise AdapterError(
                "a sitemap source needs job_url_pattern: no global pattern separates "
                "job pages from content pages correctly on every site")
        exclude = re.compile(source["job_url_exclude"]) if source.get("job_url_exclude") else None
        # Which sitemaps to follow, in the same shape as the job-URL filters above
        # and for the same reason: no single rule is right for every site.
        sitemap_include = (re.compile(source["sitemap_include"])
                           if source.get("sitemap_include") else None)
        sitemap_exclude = (re.compile(source["sitemap_exclude"])
                           if source.get("sitemap_exclude") else None)
        language = (source.get("language") or "en").lower()

        with self.client() as client:
            if progress is not None:
                progress(0, None, "reading the sitemap")
            urls = self._collect(client, host_url, origin,
                                 include=sitemap_include, exclude=sitemap_exclude,
                                 language=language)
            job_urls = [u for u in urls
                        if include.search(u) and not (exclude and exclude.search(u))]
            if not job_urls:
                raise AdapterError(
                    f"the sitemap returned {len(urls)} URLs but none matched "
                    f"job_url_pattern - the pattern is probably wrong, which is not "
                    f"the same as the employer being quiet")

            out: list[RawPosting] = []
            spent = 0
            # Only the pages actually fetched are worth counting: the known ones cost
            # nothing, so including them would make a slow run look fast.
            to_read = sum(1 for u in job_urls if u not in known)
            for url in job_urls:
                if url in known:
                    # Already recorded. Emitted so the posting is not treated as
                    # closed, but not re-read.
                    out.append(RawPosting(platform_key=url, title="", url=url))
                    continue
                if detail_budget is not None and spent >= detail_budget:
                    # Left for the next run rather than guessed at. Skipping it is
                    # safe only because the source is established by now; a first
                    # pass runs with no budget.
                    continue
                spent += 1
                posting = self._read_detail(client, url)
                if posting is not None:
                    out.append(posting)
                if progress is not None:
                    progress(spent, to_read, "job pages read")
                time.sleep(POLITE_DELAY)
        return out

    # ------------------------------------------------------------------ sitemaps
    @staticmethod
    def _guess(identifier: str) -> str:
        host = identifier if "://" in identifier else f"https://{identifier}"
        return urljoin(host, "/sitemap.xml")

    def _collect(self, client: httpx.Client, host_url: str, origin: str,
                 include=None, exclude=None, language: str = "en") -> list[str]:
        """robots.txt first, as a matter of manners, then walk what it declares."""
        candidates: list[str] = []
        try:
            robots = client.get(f"{origin}/robots.txt")
            if robots.status_code == 200:
                candidates = SITEMAP_LINE.findall(robots.text)
        except httpx.HTTPError:
            pass
        if host_url not in candidates:
            candidates.insert(0, host_url)

        if include is not None:
            candidates = [c for c in candidates
                          if include.search(c) or c == host_url]
        if exclude is not None:
            candidates = [c for c in candidates
                          if not exclude.search(c) or c == host_url]
        candidates = self._one_per_language(candidates, language, prefer=host_url)

        budget = {"left": MAX_SITEMAP_FETCHES}
        seen: set[str] = set()
        urls: list[str] = []
        for candidate in candidates[:3]:
            urls.extend(self._walk(client, candidate, seen, budget))
            if len(urls) >= MAX_URLS:
                break
        return urls[:MAX_URLS]

    def _one_per_language(self, candidates: list[str], language: str,
                          prefer: str | None = None) -> list[str]:
        """Collapse sitemaps that are translations of each other.

        Cisco's robots.txt declares two: `/ca/fr/sitemap_index.xml` and
        `/global/en/sitemap_index.xml`. Both were followed, both list the same
        openings, and the result was every Cisco posting stored twice - 2,752 rows
        for 1,376 real jobs - because a translated posting has a different URL, a
        different title key and a location in a different language, so nothing
        reconciled them. The digest then reported the same opening twice, in two
        languages, as two new jobs.

        Several sitemaps for one site is normal and wanted: `sitemap-jobs.xml` and
        `sitemap-pages.xml` hold different content. Several *translations* of one
        sitemap are not. Two things have to hold before one is dropped: the
        candidates end in the same file name, and at least one of them carries a
        language code as a path segment. `/sitemap.xml` beside `/news/sitemap.xml`
        fails the second test and both are kept.

        The choice is reported as a note rather than made silently, because it is a
        guess about someone else's site; `language` or `sitemap_include` on the
        source overrides it. So does the source's own endpoint: a sitemap somebody
        recorded by hand during discovery is never dropped in favour of a guess.
        """
        groups: dict[tuple[str, str], list[str]] = {}
        for url in candidates:
            parsed = urlparse(url)
            name = parsed.path.rsplit("/", 1)[-1].lower()
            groups.setdefault((parsed.netloc.lower(), name), []).append(url)

        kept: list[str] = []
        for group in groups.values():
            if len(group) == 1 or not any(_locales_in(u) for u in group):
                kept.extend(group)
                continue
            choice = (prefer if prefer in group
                      else _pick_language(group, language)
                      or _pick_language(group, "")
                      or group[0])
            dropped = [u for u in group if u != choice]
            self.note(
                f"robots.txt declared {len(group)} translations of the same "
                f"sitemap; following {choice}, skipping {', '.join(dropped)} "
                f"- set `language` or `sitemap_include` on the source to choose "
                f"differently")
            kept.append(choice)
        return kept

    def _walk(self, client: httpx.Client, url: str, seen: set[str], budget: dict,
              depth: int = 0) -> list[str]:
        if depth > 2 or budget["left"] <= 0 or url in seen:
            return []
        seen.add(url)
        budget["left"] -= 1
        try:
            response = client.get(url)
        except httpx.HTTPError as exc:
            if depth == 0:
                raise AdapterError(f"sitemap unreachable: {type(exc).__name__}") from exc
            return []
        if response.status_code != 200:
            if depth == 0:
                raise AdapterError(f"sitemap returned HTTP {response.status_code}",
                                   http_status=response.status_code)
            return []

        body = response.text
        locations = LOC.findall(body)
        if IS_INDEX.search(body):
            out: list[str] = []
            for sub in locations:
                out.extend(self._walk(client, sub, seen, budget, depth + 1))
                if len(out) >= MAX_URLS:
                    break
            return out
        return locations

    # -------------------------------------------------------------------- detail
    def _read_detail(self, client: httpx.Client, url: str) -> RawPosting | None:
        """Read one job page's structured data.

        A page without `JobPosting` markup is skipped rather than guessed at from its
        HTML: a posting with an invented title is worse than one that is missing,
        because it looks right.
        """
        try:
            response = client.get(url)
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None

        for block in LD_BLOCK.findall(response.text):
            try:
                document = json.loads(block)
            except ValueError:
                continue
            for item in (document if isinstance(document, list) else [document]):
                if not isinstance(item, dict) or item.get("@type") != "JobPosting":
                    continue
                return RawPosting(
                    platform_key=url,
                    title=(item.get("title") or "").strip(),
                    location=_location_of(item),
                    url=url,
                    published_at=item.get("datePosted"),
                    text=" \n".join(filter(None, [
                        item.get("title"),
                        _location_of(item),
                        _plain(item.get("description") or ""),
                    ])),
                    raw={k: v for k, v in item.items() if k != "description"},
                )
        return None


def _locales_in(url: str) -> list[str]:
    """The language codes appearing as path segments of a URL."""
    return [seg.lower() for seg in urlparse(url).path.split("/")
            if _LOCALE_CODE.match(seg)]


def _pick_language(group: list[str], language: str) -> str | None:
    """The member written in `language`, or with no language at all when it is empty.

    A sitemap with no locale segment is the canonical one on most sites, which makes
    it the right second choice when the wanted language is not on offer.
    """
    for url in group:
        locales = _locales_in(url)
        if language:
            if any(loc == language or loc.startswith(f"{language}-")
                   or loc.startswith(f"{language}_") for loc in locales):
                return url
        elif not locales:
            return url
    return None


def _plain(html: str) -> str:
    text = re.sub(r"<[^>]{0,300}>", " ", html)
    for entity, char in (("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&"),
                         ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")):
        text = text.replace(entity, char)
    return re.sub(r"\s+", " ", text).strip()


def _location_of(item: dict) -> str | None:
    """Flatten `jobLocation` into the same free text the other adapters produce.

    schema.org nests it, sometimes as a list, and the places module already knows how
    to read the flat form - so this keeps one location parser rather than two.
    """
    raw = item.get("jobLocation")
    if not raw:
        if item.get("jobLocationType") == "TELECOMMUTE":
            return "Remote"
        return None
    entries = raw if isinstance(raw, list) else [raw]
    parts: list[str] = []
    for entry in entries:
        if isinstance(entry, str):
            parts.append(entry)
            continue
        if not isinstance(entry, dict):
            continue
        address = entry.get("address")
        if isinstance(address, str):
            parts.append(address)
            continue
        if not isinstance(address, dict):
            continue
        bits = [address.get("addressLocality"), address.get("addressRegion"),
                address.get("addressCountry")]
        flat = []
        for bit in bits:
            if isinstance(bit, dict):
                bit = bit.get("name")
            if bit:
                flat.append(str(bit))
        if flat:
            parts.append(", ".join(flat))
    if item.get("jobLocationType") == "TELECOMMUTE":
        parts.append("Remote")
    return "; ".join(dict.fromkeys(parts)) or None
