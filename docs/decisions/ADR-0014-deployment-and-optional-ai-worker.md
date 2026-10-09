# ADR-0014 — The server is the host; AI processing is an optional external worker

**Date:** 2026-10-07
**Status:** Accepted
**Amends:** ADR-0006, which anticipated this question and named the condition

## Context

Two questions had been left open: where the application runs, and what happens if a
machine capable of running language models locally is acquired.

The operator has settled both. It runs on the home server. A Mac would be integrated
**from outside the architecture**, and only as AI processing — not as a new host.

## Decision

**The server is the only host.** It holds the application, the database, the
configuration and the scheduled run. It owns the mail path. Nothing about the design
assumes a second machine.

**AI processing is an optional external worker**, defined by an interface and absent
by default:

- The application calls it over HTTP for **extraction and labelling tasks only** —
  reading fields out of an unstructured page, or extracting gate wording.
- It is **disabled by default**, and the application must be fully functional without
  it. A worker that is absent, slow or failing degrades the result; it never breaks
  the run. Per ADR-0012, a worker that cannot be reached is **reported**, not silently
  skipped.
- It **never produces a fit verdict**. ADR-0006 stands: judgement stays with the
  operator and the assistant he already uses. The worker labels; it does not decide.
- It is one labeller among several, carrying its own provenance like any other.

## Why

- Keeping one host keeps the operational story intact. The server already has the
  snapshots, the mail configuration, the monitoring and the recovery runbooks. An
  application split across two machines inherits two failure domains and a network
  between them, in exchange for speed a daily JSON fetch does not need.
- Making AI an optional worker behind an interface means the capability can arrive
  later without a rewrite, and the project stays honest for other users — who will not
  have a Mac mini, and whose installation must work anyway.
- It also keeps the hardware question clean: the external worker is the *only* thing
  new hardware would plug into, which makes the value of that hardware easy to
  evaluate rather than assumed.

## The amendment to ADR-0006

ADR-0006 forbade a model call inside the application and gave the reason: judgement
would be unauditable and redundant. It also recorded the condition for revisiting.
That condition is now partly met, so the boundary is stated explicitly:

> **Permitted:** a model extracting or labelling, where the output is checkable field
> by field, carries provenance, and is one input among several.
>
> **Still forbidden:** a model producing a fit verdict, a ranking score, or any
> judgement that cannot be inspected and argued with.

The distinction is that extraction can be checked — a title is present or absent, a
date parses or does not — while a verdict cannot. ADR-0006 is amended, not reversed.

## Consequences

- The worker interface is part of the design from now on, even while nothing
  implements it. Designing it later is how it ends up entangled.
- Discovery remains a separate, occasional tool with its own budget. A headless
  browser belongs there, on the server, and does not need the Mac at all.
- The hardware register in the private notes is updated: the Mac's role is now scoped
  to exactly one interface, which makes most of that register's entries independent of
  it.
- If the Mac is ever acquired, nothing migrates. One optional endpoint gets an
  address.
