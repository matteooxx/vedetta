# ADR-0007 — The app reads the existing trackers; it never writes to them

**Date:** 2026-10-06
**Status:** Accepted

## Context

The operator keeps two application trackers, deliberately separate: one for the
private sector with 92 rows, one for public-institution channels with 11. They are
not tables of data — they carry prose: declared gaps, the exact wording used in a
cover letter, why a deviation was accepted, which form field was missed and how.

The separation between the two is itself a decision, made because the channels
have different states, timelines and eligibility rules, and mixing them would make
both unreadable.

## Options considered

**One-way, read-only.** Chosen.

**Read and write back.** The app would append a row when a posting is marked
applied. Rejected: a program writing into those files would degrade exactly what
makes them valuable — the prose — and would sooner or later flatten the two-channel
separation, which no schema the app invents is going to preserve faithfully.

**No integration at all.** Rejected: the app would keep re-surfacing postings the
operator has already applied to, which is noise he would have to filter by hand
every single day.

## Decision

The app **reads** both trackers to learn what has already been applied to, and
keeps its own triage state — interested, dismissed, applied — in its own database.
It never writes to either tracker file.

## Why

- The trackers are the operator's record of his own judgement. They are curated by
  hand and they work.
- Read-only is the cheapest possible coupling: if the app is deleted tomorrow,
  nothing of value is touched.
- The failure mode of reading wrongly is mild — a duplicate is shown. The failure
  mode of writing wrongly is corruption of months of hand-written context.

## Consequences

- The app must parse a human-maintained Markdown table without being brittle about
  it. If parsing fails it reports the failure and falls back to showing everything,
  rather than silently suppressing.
- The two-channel separation is carried into the app's own model as a property of
  each watched employer, not invented fresh.
- Marking something applied stays a manual act in the tracker, done through the
  existing assistant workflow. The app's own state is a convenience, not the record.
- The trackers live on the operator's PC, not on the server. How the app reads them
  is an open question: a copy pushed to the server, a read-only share, or an export
  step. It needs deciding before this ADR can be implemented.
