# ADR-0013 — Generic from the first line: nothing personal is hard-coded

**Date:** 2026-10-07
**Status:** Accepted
**Operator instruction:** the project will be published on GitHub as a personal
project, so there must be no hard-coded searches — everything flexible, so that any
user can model it for their own case.

## Context

Everything learned so far is specific to one person: 51 employers, a rulebook of
language and sponsorship and seniority gates, two application trackers in a
particular Markdown shape, a role taxonomy in four clusters, a geography preference.

That specificity is the project's greatest asset and, if it ends up in the source, its
fatal flaw as a publishable tool. Retrofitting configurability is also notoriously
expensive: it tends to mean rewriting the parts that were written fastest.

The instruction arrives early enough to cost almost nothing. It would have been
expensive in a month.

## Decision

**Code contains mechanism. Configuration contains the case.** The repository ships
examples and no real data.

| Belongs in code | Belongs in configuration |
| --- | --- |
| Platform adapters (how to talk to Greenhouse, Workday, Phenom…) | Which employers, on which platforms, with which identifiers |
| The label *engine* — how a rule is expressed and applied | The actual rules: which languages block, which seniority wording matters, which role words count |
| Discovery techniques | Which techniques are enabled |
| Digest rendering | Where it is sent, at what hour, in what language |
| Tracker reader *interface* | Which tracker files exist, and their format |
| Reconciliation and run accounting | Thresholds and preferences |

Concretely:

- **A declarative rule file.** Gates, role clusters and geography are data — patterns
  with a name, a severity and a human-readable explanation — not `if` statements. The
  repository ships `rules.example.yaml`; the real one lives outside it.
- **A watchlist file**, same treatment. The repository ships two or three well-known
  public employers as examples, never the operator's 51.
- **Tracker reading is a pluggable reader** behind an interface, with the Markdown
  pipe-table reader as one implementation among possible others. ADR-0007 and
  ADR-0010 are now specific *configurations* of a general capability, not the design
  itself.
- **No personal data in the repository.** No employer list, no application history, no
  names, no addresses, no mailbox, and nothing drawn from the home infrastructure —
  no hostnames, IP addresses, ports or filesystem paths. That rule already exists for
  this operator's other published work; it now applies here from the first commit.
- **Secrets only in the runtime environment file**, never in the repository, with a
  committed `.env.example` listing the names and no values.
- **English in code, identifiers and documentation**, per ADR-0003. The digest's
  output language is configuration.

## Why

- The cost of doing this now is close to zero and rises steeply with every file
  written.
- It makes the project genuinely useful to someone else, which is the stated goal and
  also what makes it worth publishing at all.
- It forces a clean separation that is valuable even with one user: rules that live in
  a data file can be edited and reviewed without touching code, and a rule file is a
  far better artefact than a function full of regular expressions.
- A published repository is also a portfolio piece. A tool that only works for its
  author reads as a script; the same tool with a rule engine and an adapter interface
  reads as engineering.

## Consequences

- **A configuration schema has to be designed deliberately**, and it is now part of
  step E alongside the database.
- **The rule language needs a real design.** It must express "this language is
  required" versus "this language is an asset", a seniority threshold, a phrase that
  marks a continuous pipeline rather than an opening. Too weak and the operator's
  nuance is lost; too strong and it becomes a programming language. This is the
  hardest piece of the whole project and should not be rushed.
- **Documentation splits**: a public README explaining the mechanism to a stranger,
  and private notes carrying the operator's own case.
- **The default configuration must be honest.** An example watchlist should contain
  employers anyone can verify, so a new user's first run actually returns something.
- ADR-0002's public/private directory split now has a second reason behind it, and the
  private half becomes the home of the operator's real configuration rather than only
  of infrastructure notes.
