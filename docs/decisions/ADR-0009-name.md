# ADR-0009 — The project is named Vedetta

**Date:** 2026-10-06
**Status:** Accepted

## Context

The project had been running under the placeholder `new-nas-app` since the
documentation scaffold was created, with the rename recorded as a pending action.

## Options considered

| Candidate | Argument | Outcome |
| --- | --- | --- |
| **Vedetta** | Italian for a lookout — the one who keeps watch and signals, without deciding what the signal means | **Chosen** |
| *Rassegna* | A daily press review, which is literally the shape of the output | Rejected |
| *Watchpost* | English, consistent with the documentation language and the operator's public repositories | Rejected |
| *Bollettino* | A periodic impersonal dispatch — accurate but bureaucratic in tone | Rejected |

## Decision

The project is **Vedetta**. Directories renamed from `new-nas-app` to `vedetta` in
both the publishable and private halves, with internal references updated.

## Why

The name states the boundary that ADR-0006 draws. A lookout sights and reports; it
does not decide whether to engage. That is exactly the division of labour here: the
app watches and labels, the operator and his assistant judge. A name that describes
the product honestly is a small, permanent reminder of the scope — and this project
has already set aside several features precisely because they crossed that line.

Italian over English despite ADR-0003 setting English for documents: that ADR
governs prose, not proper nouns, and the tool is a personal one.

## Consequences

A future public release would ship under this name, which is not an English word.
Acceptable: the README can carry a one-line gloss.

## Reversing this

Another directory rename and another reference pass. Cheap, but it costs a
changelog entry each time, so it should not happen again.
