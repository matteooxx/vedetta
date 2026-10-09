# ADR-0011 — `ats-scrapers` is a reference and a discovery aid, not a dependency

**Date:** 2026-10-07
**Status:** Accepted

## Context

`ats-scrapers` (MIT, PyPI) advertises 63 hiring platforms plus first-party adapters
for several large employers. It was evaluated against the 40 employers our own census
could not reach.

Results: it resolved 35 and fetched live postings for 16, which would take total
coverage from 33 employers to 49. That is a real contribution.

It also returned a Brazilian business school as IBM, a road-paving contractor in
Florida as BlackRock, and a garden-pergola retailer as an Irish IT consultancy. And
page fingerprinting subsequently **corrected four of its answers** and found two
employers it did not know at all — including one whose true identifier is
`mistral.ai`, which returned 208 postings where the library's guessed name returned
zero.

Separately: it declares `httpx`, `pandas` and `pydantic`, but imports `bs4` without
declaring it.

## Options considered

**Adopt as a runtime dependency.** Fastest path to coverage. Rejected.

**Reimplement from scratch, ignoring it.** Rejected: its Workday, Eightfold, Phenom,
iCIMS and Oracle scrapers encode genuinely expensive knowledge, and the licence
permits learning from them.

**Use as a reference implementation and an interactive discovery aid.** Chosen.

## Decision

Not a runtime dependency. Used in two ways instead:

1. **Reference implementation.** Its adapters for the hard enterprise platforms are
   read and reimplemented in the project's own shape. MIT licence, attributed.
2. **Discovery aid.** Run interactively, outside the application, as one of several
   techniques producing a *candidate* platform and identifier — which a human
   confirms before it is written into the watchlist.

## Why

- `pandas` inside a container is a heavy dependency for a daily job that parses JSON.
- An undeclared import is a signal about release discipline, not just an
  inconvenience.
- Decisively: its manifest is **not safe as an authority**. Three of nineteen live
  results were different companies entirely. Taking it as the source of truth for
  what to poll would mean betting the project's core promise on data of that quality.

Note what this does *not* say: the library is good work and its coverage breadth is
real. It is being declined as an *authority*, not as a source of knowledge.

## Consequences

- Platform adapters are written in this project, informed by its code, with
  attribution in the repository.
- It becomes one input to the discovery process defined in ADR-0012 — never the only
  one, and never a path to automatic enrolment.
