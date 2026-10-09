# ADR-0004 — How the design phase is run

**Date:** 2026-10-06
**Status:** Accepted

## Context

The operator asked for a design process to be agreed **before** disclosing what
the app does, and explicitly asked for options that do not depend on the idea.
That constraint is the useful part of this decision: it forces the work that can
be done without the idea to be identified and finished first, instead of waiting.

## Options considered

**A — Constraints-first (the platform envelope).** Start from the infrastructure:
resource budget, port, exposure model, where data lives and how it is protected,
where secrets live, how the image is built and rolled back. Produces the envelope
any app on this NAS must fit inside.
*For:* executable immediately, with no knowledge of the idea. Rules out, up
front, the choices the platform cannot support. Reusable for the next app.
*Against:* says nothing about the product. Insufficient on its own.

**B — Working backwards (press release and FAQ).** Write the announcement of the
finished app and its FAQ first, then derive scope from it.
*For:* forces an answer to who it is for and why, which is the cheapest way to
cut features. The operator knows the method from an AWS internship.
*Against:* stays upstream of the technical work and has to be translated after.

**C — Funnel interview.** Structured rounds: problem, person and scenario, scope
and anti-scope, data, constraints, definition of done.
*For:* leaves no gaps; most complete.
*Against:* the slowest route to anything running, and risks designing at length
before any contact with reality.

**D — Walking skeleton.** Design the thinnest end-to-end slice — one page, one
endpoint, one row written to disk — and deploy it for real.
*For:* surfaces the platform risks (image build, mounts, uid/permissions, the
reverse-proxy path, health checks) on day one rather than at the end.
*Against:* builds the wrong thing quickly if the idea is not yet in focus.

**E — Event storming.** List domain events in time order, derive entities,
commands, screens and the database schema from them.
*For:* the strongest fit for a stateful, data-holding app.
*Against:* requires the idea to be defined already.

## Decision

Run **A → B → E → D**, with **C held in reserve**.

A happens now, without the idea. B starts the moment the idea is disclosed and
exists to prune, not to expand. E turns the pruned scope into a data model. D
takes the thinnest slice of that model all the way to a running deployment before
any breadth is added.

If B leaves real gaps, they get targeted questions — not the full C interview.

## Why

- A is the only step that can run under the operator's stated constraint, so
  running it now converts waiting time into finished work.
- Putting B before E and D means scope is cut while cutting is still free.
- Putting D last but not *too* last matters: the platform has known, repeatedly
  observed failure modes around locally built images, and finding them with a
  trivial app is much cheaper than finding them with a full one.

## Consequences

The platform envelope produced by A becomes a constraint on B. If the idea turns
out not to fit the envelope, the envelope is revisited explicitly in a new ADR —
it is not quietly bent.

## Reversing this

Free at any point. The order is a plan, not a commitment; a step can be dropped
by superseding this ADR.
