# ADR-0008 — One digest per day, at a fixed hour

**Date:** 2026-10-06
**Status:** Accepted

## Context

The operator asked to be notified by email when new postings appear. How often is
a product decision, not a technical one.

## Options considered

**A daily digest at a fixed hour.** Chosen.

**A digest plus immediate mail for a priority set of employers.** Rejected for now,
but only for now: it is a small addition once the digest exists, and it answers a
real case. It was not taken in the first release because it adds a category to
maintain before there is any evidence that a day of delay has cost anything.

**Immediate mail for every new posting.** Rejected. With 51 employers this is the
most direct route to the notifications being muted within a month.

**Weekly.** Rejected: on competitive postings a week is material.

## Decision

One email per day, at a fixed hour, containing everything new since the previous
run. The first run after a watchlist change seeds silently and sends nothing.

Structure follows the false-negative principle: strongest matches first, then
everything else from watched employers below them — present, not hidden.

## Why

Postings are not perishable on an hourly scale. Attention is. A notifier that
arrives too often gets silenced, and a silenced notifier has failed completely,
whereas a notifier that arrives a few hours late has failed hardly at all.

A fixed hour also makes absence meaningful: if the mail does not arrive, something
is wrong, and that is itself a health signal.

## Consequences

- The digest has to be worth opening every day even when nothing exciting is in it,
  which puts real weight on how it is laid out.
- A day with no new postings still sends a short mail rather than nothing, so that
  silence keeps meaning failure rather than quiet.
- The hour is not yet chosen. It is an open item.
