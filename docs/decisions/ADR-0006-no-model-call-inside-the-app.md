# ADR-0006 — The app labels; it does not judge

**Date:** 2026-10-06
**Status:** Accepted

## Context

The eligibility gates that matter are textual and some of them are nuanced. A
language listed as *required* kills a posting; the same language listed as a
*strong asset* does not. A seniority threshold is usually a number. A hidden
requirement for active university enrolment is a sentence.

A language-model pass would read that nuance well. It would also add an outbound
credential, a recurring cost, and a dependency capable of reaching different
conclusions on two consecutive runs over the same text.

## Options considered

**Deterministic rules only.** Regular expressions and the structured fields the
platforms already supply. Chosen.

**A model pass inside the app.** Rejected — see below.

**No scoring at all, purely chronological.** Rejected: with 51 employers the
digest becomes long and undifferentiated, and the operator would be doing the
triage the app was built to help with.

## Decision

The app extracts and **labels**: years of experience demanded, languages required
versus preferred, sponsorship statements, role-cluster keywords, and whether the
posting is a continuous pipeline rather than a real opening. It ranks by those
labels.

It does **not** call a language model, and it does not attempt a fit verdict.

## Why

The decisive argument is not cost or reliability — it is redundancy. There is
already a capable assistant in this workflow, the one that writes the targeted CVs
and cover letters, and it does the nuanced judging well and with the operator
present. Reimplementing that judgement inside the app would mean building a second
opinion that is weaker, unsupervised, and then having to decide how much to trust
it.

Deterministic labelling is also **auditable**. When a posting is ranked low, the
reason is a visible label the operator can disagree with. A model's verdict is a
sentence he would have to take on faith — and the one documented failure in this
workflow was caused by trusting a filter.

## Consequences

- Nuance that regular expressions miss will land in the digest unlabelled, ranked
  neutrally. Per tension T2 in S01 that is the safe direction to fail in: it stays
  visible.
- No third-party credential is needed. This closes the platform envelope's open
  question 4 with "none".
- If labelling later proves insufficient, the right next step is to prepare
  material for the assistant more deliberately — not to put a model in the loop.
