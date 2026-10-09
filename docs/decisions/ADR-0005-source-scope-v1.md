# ADR-0005 — Which sources the first release covers

**Date:** 2026-10-06
**Status:** Accepted

## Context

Three families of source were on the table: the careers pages of employers the
operator already tracks, the public-institution portals he applies through on a
separate channel, and general job aggregators.

A live probe (see the ATS feasibility log in the private half) established that
the hiring platforms behind the employer careers pages answer unauthenticated
requests with clean JSON. The institution portals are session-based web
applications and were not probed. Aggregators were not probed either.

## Options considered

**Employer careers pages only.** Chosen.

**Employers plus the EU institution portals.** Covers the channel where eleven
applications are currently open. Rejected for the first release: these are the
hardest sources in the whole set, and putting the hardest work first risks the
easy, already-proven majority never shipping.

**Employers plus aggregators.** Widest coverage. Rejected: aggregators are where
the noise lives, they defend aggressively against automated access, and their
listings duplicate the careers pages the app already reads — so the first thing
the feature would require is a de-duplication layer against sources that are
already covered.

## Decision

The first release watches **employer careers pages only**, through one adapter per
hiring platform rather than one scraper per employer.

Institution portals and aggregators are not cancelled — they are later adapters
behind the same interface. The adapter boundary is what makes deferring them cheap.

## Why

- It is exactly what the operator asked for.
- It is the part that has been verified rather than assumed.
- Adapters amortise: one platform adapter reaches every employer hosted on it, so
  the first two adapters already cover several employers in the existing history.

## Consequences

Coverage will be **uneven**, and that must be visible rather than silent. An
employer whose platform has no adapter yet, and a source that fails to respond,
are both conditions the app has to report — not absences the operator has to
notice on his own. This follows directly from the false-negative principle in S01.
