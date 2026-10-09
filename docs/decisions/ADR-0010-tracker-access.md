# ADR-0010 — How the app reaches the application trackers

**Date:** 2026-10-06
**Status:** Accepted
**Depends on:** ADR-0007, which settled that access is read-only and one-way

## Context

ADR-0007 established that the app reads the two existing application trackers so
that a posting already applied to is not presented as new, and never writes to
them. It left the mechanism open: the trackers are Markdown files on the
operator's PC, and the app runs on the server.

## Options considered

**A synced copy on the server, whose tables the app parses.** Chosen.

**An export step producing structured data.** The operator's existing
application workflow would emit a small machine-readable file that the app
consumes. A cleaner contract, and no parsing of human prose. Rejected for now: it
adds a step that has to be remembered during a workflow that is already working,
and a step that is remembered only sometimes is worse than a copy that is
occasionally stale, because its absence is silent.

**No reading at all.** Rejected in ADR-0007.

## Decision

The two tracker files are copied into the app's dataset on the server. The app
parses their Markdown tables to extract employer, role and status.

Parsing was proven during the design session: 92 rows were extracted from the
264 KB private-sector tracker with a few lines of Python, and the two files use
regular pipe tables throughout.

## Why

- It works today, against the files as they actually are, with no change to a
  workflow that is functioning.
- It keeps the coupling as loose as ADR-0007 intends: the app reads a copy and
  can be deleted without touching anything.
- The cost of staleness is mild and self-correcting — a stale copy means a posting
  already applied to might appear once more, which costs a glance.

## Consequences

- **Parsing must be forgiving and loud.** These are hand-maintained files whose
  shape will drift. If parsing fails, the app reports the failure in the digest
  and falls back to showing everything. It must never respond to a parse error by
  suppressing postings, because that converts a small problem into the exact
  failure mode this project is organised against.
- The copy needs refreshing. How — manual, scheduled, or folded into the existing
  mirror step — is not yet decided and is an open item.
- The two files stay separate in the app's model, carrying the private and
  institutional channels as distinct, per ADR-0007.
- If the files ever stop being regular Markdown tables, the structured-export
  option above is the fallback, not a rewrite of the parser.
