# S02 — Local AI scraping, and what already exists

**Date:** 2026-10-07
**Phase:** Brainstorming, prompted by two operator questions: whether a locally-run
AI scraper would help, and whether something like Vedetta already exists.
**Status:** Research and argument. No decision taken.

## The question splits in two, and the halves have opposite answers

Conflating them is the main risk here.

**Job 1 — reading structured feeds.** Greenhouse, SmartRecruiters, Ashby, Lever and
Breezy already return clean JSON with stable primary keys and publication dates.
The census confirmed 33 employers reachable this way.

For this job a language model is **strictly worse** than ten lines of code. It is
slower, it costs more, it is non-deterministic, and — decisively — it would replace
an exact set difference on a primary key with a judgement about whether two things
are the same posting. The reliability of "what is new" is the foundation the whole
product stands on. Nothing should be allowed to make it probabilistic.

**Job 2 — extracting structure from unstructured HTML.** The 22 employers the census
could not reach, plus the institutional portals. There is no feed, no key, no date
field; there is a page.

This is where an AI scraper would genuinely earn something, because the
alternative is a bespoke, brittle parser per employer.

## Does this contradict ADR-0006?

No, and the distinction is worth stating precisely rather than waving at.

ADR-0006 rejected a model **judging** — deciding whether a posting is a good fit.
The argument was that the verdict would be unauditable, that a weaker second
opinion would be competing with a better one already in the loop, and that the one
documented failure in this workflow came from trusting a filter.

Extraction is a different act. Its output is **checkable**: did we get a title, a
location, a URL, a date? A missing or malformed field is visible immediately, and a
wrong extraction shows up as a posting that looks wrong rather than as a posting
that silently never appears. Judgement has no such check.

So ADR-0006 stands as written, and a future decision on extraction is a separate
question — not an exception to it. If extraction is adopted, ADR-0006 should be
amended with one sentence making the boundary explicit, so a later reader does not
have to reconstruct this reasoning.

## What the hardware says

This matters more than the tooling comparison, and it is the part most easily
skipped.

The server is a Ryzen 5 3600X, 6 cores, 23 GiB of RAM, **no GPU**, **no swap**. The
platform envelope proposed a 1 GiB ceiling for this app, and no swap means an
out-of-memory condition is a kill rather than a slowdown — one that could take
other applications down with it.

| Approach | Memory | Practical speed on this box |
| --- | --- | --- |
| Deterministic JSON parsing | negligible | milliseconds |
| Small task-specific model (0.3–1B) | ~0.5–1.5 GiB | workable on CPU |
| General 7–8B model, 4-bit | ~5 GiB | single-digit tokens per second; minutes per page |
| Browser-driven AI scraper (Crawl4AI, ScrapeGraphAI, self-hosted Firecrawl) | Chromium plus the model | the envelope stops applying |

The leading open-source AI scrapers — [Crawl4AI](https://www.firecrawl.dev/blog/best-open-source-web-crawler),
[Firecrawl](https://www.firecrawl.dev/blog/best-open-source-web-crawler) in its
self-hosted form, and [ScrapeGraphAI](https://scrapegraphai.com/blog/crawl4ai-alternatives) —
are all capable, and ScrapeGraphAI in particular is built for exactly the thing
being asked about: natural-language prompts producing structured JSON, adapting to
layout changes instead of breaking on them. But they assume a browser and, in
practice, a model with real capacity behind it. On this hardware that is a different
class of application from the one the envelope describes.

**None of this rules it out.** It says that adopting it is a deliberate change to
the envelope, with a cost, and it should be paid for a problem that remains after
the cheaper options are exhausted — not instead of trying them.

## The finding that may remove most of the problem

`ats-scrapers`, version 0.3.0, MIT licensed, on PyPI, source at
[kalil0321/ats-scrapers](https://github.com/kalil0321/ats-scrapers) — 169 stars, 47
forks, around 500 commits.

It covers Greenhouse, Lever, Ashby, Workday, SmartRecruiters, SuccessFactors,
Oracle, iCIMS and ADP Workforce Now, **plus first-party adapters for Amazon, Apple,
Google, TikTok and Uber**. No API key. The usage pattern is direct —
`GreenhouseScraper("company").fetch()` — rather than going through a hosted dataset.

Read that list against the 22 employers the census could not reach: Amazon, Apple,
Google and TikTok are named explicitly, and Workday, Oracle, iCIMS and SuccessFactors
are where most of the remaining enterprises almost certainly live. **A large part of
the gap that would have justified an AI scraper may be covered by a deterministic
library that already exists.**

That has to be verified, not assumed. The right next action is to test it against
the specific employers in question rather than to adopt it on the strength of a
README.

The caution is ordinary supply-chain caution: it is a young package with a small
maintainer base, and it would be running inside the container. Pin the version, read
what it actually sends, and treat it as a source of adapters to learn from even if it
is not taken as a dependency.

## Does Vedetta already exist?

Two honest answers.

**[changedetection.io](https://github.com/dgtlmoon/changedetection.io)** is the closest
existing thing and it is good. Self-hosted, Docker, documented to run in around
128 MB of RAM, monitors JSON API responses with path filters as well as pages, has a
REST API, and notifies by email among many other channels. Its own documentation
names watching careers pages for new postings as a use case.

Pointed at the 33 confirmed feeds it would produce a working "something changed"
notifier in an afternoon, with no code written.

What it does not do is everything that makes Vedetta worth building: it diffs text,
it does not understand a posting. It cannot label a posting with "asks for 5+ years"
or "French required", cannot rank against a rulebook, cannot de-duplicate against the
existing application trackers, cannot tell a new posting from any change in the JSON,
and cannot shape a digest that stays readable when a single employer publishes 418
roles.

So it is a genuine alternative for the *watching* half and no help at all for the
*triage* half — which is the half the operator's own September incident says is where
the value is.

**Job aggregators that already scrape ATS platforms** exist in quantity —
[open-source scrapers and aggregator projects](https://scrapfly.io/blog/posts/best-open-source-job-scrapers)
indexing large numbers of companies across Greenhouse, Lever, Ashby and Workday, and
[python-jobspy](https://github.com/speedyapply/JobSpy) for the big job boards. The
aggregators are the wrong shape: they optimise for breadth across thousands of
companies, where Vedetta is deliberately narrow and personal. `python-jobspy` targets
LinkedIn, Indeed, Glassdoor and similar, which ADR-0005 excluded and which a standing
rule excludes outright in the case of one of them.

## Recommended sequence

1. **Build the deterministic adapters.** Four of them cover 32 of the 33 confirmed
   employers. This is the product.
2. **Evaluate `ats-scrapers` against the 22 unreached employers.** Cheap, bounded,
   and likely to shrink the problem substantially.
3. **Count what is left.** If it is three employers, write three small parsers. If it
   is fifteen, the AI-extraction question becomes real.
4. **Only then** consider a local model, and look for the *shape* that fits this
   hardware: small and task-specific, around half a gigabyte, not general and large.

The reason for this order is not conservatism. It is that an AI scraper introduced at
step 1 would be solving a problem that steps 2 and 3 might have deleted, and it would
be doing so by spending the entire memory envelope on the minority of sources.
