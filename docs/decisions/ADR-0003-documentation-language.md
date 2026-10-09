# ADR-0003 — Documentation language

**Date:** 2026-10-06
**Status:** Accepted

## Context

The operator is an Italian speaker and the working conversation is in Italian.
The precedent on the NAS is mixed: the agent handbook (`safety.md`,
`architecture.md`, `api.md`, `runbooks.md`) is in English, while the user-facing
guides written specifically for the operator to read — the portfolio how-to, the
desktop access and recovery guides — are in Italian.

## Options considered

**Italian throughout.** Faster for the operator to read and reason in, and
consistent with the desktop guides. Rejected by the operator.

**Mixed: Italian for thinking material, English for technical reference.**
Rejected: the boundary is judgement-based, so in practice files drift and end up
inconsistent.

**English throughout.** Chosen by the operator.

## Decision

All project documents are written in English. The working conversation stays in
Italian.

## Why

- Consistent with the NAS agent handbook, which is the body of text this project
  is most likely to be read alongside.
- No translation pass is needed if the project is ever published, and no second
  copy drifts out of date.

## Consequences

Anything quoted from the operator in Italian — a requirement, a rejection, a
preference — is kept in the original and translated beside it, not replaced. The
exact words matter when a later session is deciding what was actually asked for.

## Reversing this

Possible but it means retranslating everything written up to that point. Decide
once.
