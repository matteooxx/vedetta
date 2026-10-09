# ADR-0012 — Redundant by design: every technique runs, nothing is the only path

**Date:** 2026-10-07
**Status:** Accepted
**Operator instruction:** implement every possible solution simultaneously, so that
the job-search logic has more than one verification and no single point of failure.

## Context

Up to this point the design assumed a tournament: evaluate the techniques, pick the
best one per employer, use it. The census and the discovery prototype then produced a
pattern that undermines that assumption.

Every single technique tried has been wrong in a way that looked like success:

- Our own slug probe matched vendor **demo boards** — HTTP 200, valid JSON, one
  posting titled "Test Position".
- The published library returned **three different companies** as three employers,
  one of them an asphalt contractor.
- Page fingerprinting identified a platform correctly but produced **no usable
  identifier** without a separate extraction step.
- An identifier guessed from a company name returned **zero postings** for an
  employer that in fact had 208.

Each technique also *succeeded* where another failed. Fingerprinting corrected four
of the library's errors; the library reached employers whose pages are JavaScript
shells that fingerprinting cannot read.

The important property is not that any one of them is better. It is that **their
failures are uncorrelated**.

## Decision

Run them all, keep the disagreements, and never let one technique be the sole path
to a conclusion.

### Discovery — every technique, every employer

Manifest lookup, careers-page redirect, HTML marker fingerprint, identifier
extraction, DNS CNAME, sitemap inspection, structured-data check, and — when it
exists — a headless-browser pass. Each produces a **candidate** carrying its evidence
and which technique produced it.

Candidates are then compared:

- **Agreement** across independent techniques raises confidence but still does not
  enrol anything.
- **Disagreement is a first-class output**, surfaced for a human rather than resolved
  by a scoring rule. Disagreement is exactly the signal that caught every false
  positive so far.
- **Enrolment is always a human act**, with sample postings shown.

### Monitoring — multiple routes per employer where they exist

An employer is not a single source. It is a set of sources, each enabled
independently. Where two routes to the same employer exist, both are polled.

This is what removes the single point of failure: if one route starts returning
nothing while another still returns postings, that is a **detected fault**, not
silence. Today the only way a dead route can be noticed is that a human eventually
wonders why a company has gone quiet.

Postings arriving from different routes are reconciled into one posting, and a
posting seen by one route but not another is flagged rather than averaged away.

### Labelling — independent labellers, accumulated not merged

Each label carries what produced it: a regular expression, a structured field from
the platform, or an optional external worker. Labels accumulate as evidence with
provenance. They are never collapsed into a single score that hides which labeller
said what, and they never become a verdict (ADR-0006).

### Run accounting — silence must be impossible

Every run records, per source, whether it succeeded, errored, or returned nothing.
The digest reports sources that failed and employers with no working route at all.

This is the mechanism that makes the whole policy real. Redundancy without reporting
just means failing in more places quietly.

## Why

The operator's instruction and the project's governing principle are the same
principle. The expensive error is the false negative; a false negative is silent; and
a single technique that fails silently produces exactly that. Multiple techniques
whose disagreements are reported convert silent failure into visible failure.

It also costs very little. These are HTTP requests against different hosts, run once
a day, for a few dozen employers.

## Consequences

- **More complexity in the data model**, and it has to be carried deliberately: an
  employer has many sources, a posting has many sightings, a posting has many labels,
  and every one of them records its provenance. This is the main input to the data
  model in step E.
- **The digest gets a health section.** Not decoration — it is where the redundancy
  pays out.
- **Reconciliation needs a rule** for when two routes disagree about whether a
  posting exists. Default: the union, flagged. Showing too much is the safe
  direction.
- Techniques can be enabled and disabled individually in configuration, per ADR-0013,
  so a user who wants only one path can have it.
