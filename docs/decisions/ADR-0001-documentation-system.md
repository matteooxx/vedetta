# ADR-0001 — Documentation system

**Date:** 2026-10-06
**Status:** Accepted

## Context

The operator asked that every decision and every executed action be written to
its own markdown file, so that a future AI session starts with the complete
history of how the app was planned and built rather than re-deriving it.

There is a working precedent on the operator's own infrastructure: the agent
handbook on the NAS. It uses a README that imposes a read order, a rewritable
`state.md`, an append-only `changelog.md`, and separate files for operational
recipes and for traps already paid for. The operator trusts it and reads it, and
several AI sessions have already been bootstrapped from it successfully.

## Options considered

**One running design document.** Simplest to write, and a single file is easy to
search. Rejected: it grows into something nobody re-reads, and it loses the
distinction between a decision that is still binding and one that was reversed.

**A decision log plus an action log, handbook-style.** More files, more
discipline required. Chosen.

**An issue tracker or a project board.** Rejected: it lives outside the repo, it
does not travel with the code, and an AI session cannot read it without
credentials.

## Decision

Mirror the NAS handbook convention:

```
docs/
  README.md              index and read order
  state.md               current state, rewritable
  changelog.md           append-only
  decisions/ADR-NNNN-<slug>.md
  brainstorm/SNN-<topic>.md
```

Action logs live in the private half (`private-ops/<name>/actions/`), not here —
see ADR-0002. They quote real commands against real infrastructure, so putting
them anywhere near a publishable worktree would make the public/private boundary
a judgement call on every single file.

An ADR records: context, the options considered, the decision, why, and what it
costs to reverse. An action log records the command run and what it actually
printed. A superseded ADR is not deleted — its status line is changed and it
names the ADR that replaced it.

## Why

- A rejected option that is written down with its reason does not come back.
- An action log with real output is evidence. A summary written from memory is
  not, and this project will be worked on by sessions that cannot see each
  other's terminals.
- Matching a convention the operator already reads means the files will actually
  be read.

## Reversing this

Costs nothing but the files already written. The convention is not load-bearing
for any running system.
