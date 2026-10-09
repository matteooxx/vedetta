# What comparable tools do, and what is worth taking

**Date:** 2026-10-07
**Status:** Proposal. Every claim about data availability below was checked against
the live platforms rather than assumed, and the checks are reported — including the
ones that came back negative.

---

## The field, briefly

| Tool | What it is | What it does that Vedetta does not |
| --- | --- | --- |
| [JobOps](https://github.com/dakheera47/Job-Ops) | Self-hosted pipeline, Docker, SQLite. The closest cousin. | Scores fit 0–100 with a model, tailors a CV per role, and **watches the mailbox for recruiter replies** |
| [Huntr](https://huntr.co/product/job-tracker) | Hosted tracker, Kanban board, browser autofill | A pipeline with **stages**, not three flags |
| [Teal](https://huntr.co/blog/huntr-vs-teal) | Hosted, keyword gap analysis per posting | Shows which of a posting's terms your CV does not use |
| [JobFunnel](https://github.com/PaulMcInnis/JobFunnel) | CLI scraper to CSV, YAML config, nightly cron | **Archived read-only since December 2025** |
| [changedetection.io](https://github.com/dgtlmoon/changedetection.io) | Generic page/JSON watcher | Nothing relevant; assessed earlier in S02 |

Two observations worth more than the feature lists.

**The incumbent is dead.** JobFunnel is still the top result for open-source job
scraping and has been archived since December 2025, so it no longer tracks board
changes. That is the clearest argument that this niche has no maintained tool — and
also a warning about what happens to one that depends on scraping boards whose shape
keeps moving. Vedetta's adapter-per-platform structure is the right answer to exactly
that decay.

**JobOps is the same idea with the opposite philosophy.** It scores with a model,
rewrites the CV, and reaches into the inbox. Vedetta deliberately does none of those.
Three of those four choices should stay as they are; the fourth is the single best
idea in this review.

---

## Worth taking

### R1 — Watch the job mailbox for outcomes — **BUILT, THEN REMOVED 2026-10-07**

> **Built, and then removed the same day at the operator's request.** The code worked
> — read-only IMAP, rules not a model, no message bodies stored, proposals a human
> accepted — and it is gone because reading a mailbox was not wanted. That is a better
> reason to delete code than most.
>
> **The gap it addressed is real and remains open**: more than half of the recorded
> applications sit with no outcome at all, and mail is still the only channel where an
> outcome reliably
> lands. If it is ever revisited, the four limits below are what made it defensible and
> should be the starting point rather than an afterthought.
>
> A useful consequence of the removal: the application now holds **no credential of
> any kind**. The digest goes out through the machine's own mail configuration, so
> there is nothing to create, rotate or leak.

**The gap it fills is real and measurable.** The operator's private-sector tracker has
**50 rows sitting at "Candidato" with no recorded outcome** out of 92. Some of those
are silent rejections, some are still live, and from the tracker alone there is no way
to tell. JobOps connects Gmail and auto-detects interviews, offers and rejections.

Mail is also the one channel where an outcome *always* arrives. A posting closing tells
you nothing about your application; a rejection email does.

**Recommendation: build it, but as a separate read-only component**, and keep it on
Vedetta's side of the line:

- It **reports observations**, it does not update the trackers. ADR-0007 keeps those
  hand-curated and authoritative, and a program guessing "rejected" from a phrase and
  writing it in would corrupt months of careful prose.
- It classifies with **rules over sender and subject**, not a model — the same
  reasoning as ADR-0006. "Unfortunately" plus a known ATS sender is a rule anyone can
  read and correct.
- It matches a message to a posting by employer name and posting URL, and says
  *unmatched* rather than guessing.

**The honest cost:** this needs read access to a mailbox. That is a genuine expansion
of scope and of what a compromise of this application would mean, and it is the first
feature here that would be a real decision rather than a default. Scoped narrowly —
one dedicated mailbox, read-only credentials, no message bodies stored, only the
derived observation — it is defensible. Unscoped, it is not.

### R2 — Employer activity over time — **DONE 2026-10-07**

**Costs nothing: the data is already in the database.** The `sighting` table records
which postings each source showed on each run, so posting counts per employer per week
are a query, not a collection problem.

What it answers, which no tool in the table above does: *who is actually hiring right
now.* An employer that went from four open roles to nineteen in a month is a different
prospect from one that has had the same six for a year — and that is exactly the kind
of judgement the operator currently makes from memory.

Pairs naturally with R6 below: an employer whose postings never close is probably
running pipelines rather than filling roles.

### R3 — Salary, extracted from the text — **DEFERRED by the operator, 2026-10-07**

> **Not being built.** The operator's ruling: the directive is not yet live on any
> European portal, so a rule that fires only on US roles earns nothing. Revisit when
> a European posting in the watchlist actually carries a range — the inverse label
> (an EU posting with no range stated) becomes worth having at the same moment.
> The investigation below stands as the record of why it is not feasible yet.

I checked this properly, because the legal context suggests it should be easy and it
is not:

| Source | Structured salary field? |
| --- | --- |
| Greenhouse board API (`content=true`) | **No** |
| SmartRecruiters posting API, listing and detail | **No** — no `compensation` key |
| schema.org `JobPosting` on a live Cisco page | **No** — `baseSalary` absent |
| In the description **text** | **Yes, 13 of 40** postings sampled |

And every one of those thirteen was a dollar amount on a US role, driven by American
state pay-transparency law rather than by Europe.

The [EU Pay Transparency Directive](https://eures.europa.eu/salary-ranges-are-changing-recruitment-your-company-ready-2026-10-02_en)
(2023/970) had to be transposed into national law by **7 June 2026**, and
[LinkedIn began enforcing](https://www.auditsocials.com/blog/linkedin-salary-transparency-compliance-2026-eu-pay-transparency-directive-mandatory-salary-ranges-job-postings)
salary ranges on EU-facing postings in February 2026. So the ranges are legally owed
and are **not yet showing up in these employers' feeds**.

**Recommendation:** implement it as a **rule**, not a field — a `money` rule kind that
extracts a range from the text and attaches it as a label. That works today at roughly
a third coverage, needs no adapter changes, and gets better on its own as compliance
arrives.

**And the inverse is the more interesting label:** an EU-located posting with **no**
range stated is now out of step with the directive. That is worth seeing — as a
negotiating datum, and as a small signal about the employer.

### R4 — Pipeline stages instead of three flags — **DONE 2026-10-07**

Huntr's central idea, minus the Kanban. The current `interested / applied / dismissed`
has no sense of progress, so the interface cannot answer "what is in flight".

**Recommendation:** an ordered status with the date it changed — *interested → applied
→ screening → interview → offer / rejected*. Not the drag-and-drop board: that would
need keyboard alternatives for no real gain.

**Scope boundary:** Vedetta's state should stop at *applied*. After that the operator's
tracker and his assistant workflow take over, and R1 is what feeds the later stages.

### R5 — Keyword gap against the CV — **DONE 2026-10-07**

Teal's distinctive feature. Extract the posting's technology terms and show which ones
do not appear in the operator's CV.

Worth taking because **it stops at showing**, which keeps it inside ADR-0006. Cheap
version: a term list in `profile.yaml`, diffed against capitalised and known-technology
tokens in the posting. No model, no judgement, auditable.

### R6 — Repost and staleness detection — **DONE 2026-10-07**

Already in the deferred list from the first brainstorm, and cheaper now that
`closed_run` and the content hash exist.

Two signals, both from data already held:

- **A repost**: a posting closes and an equivalent one appears under a new key. If it
  is a role the operator was rejected for, that is worth knowing.
- **Staleness**: a posting open for 90-plus days is usually a pipeline rather than a
  vacancy, whatever it says about itself.

### R7 — Saved views — **DONE 2026-10-07**

Already **B4** in the main backlog; the competitive review reinforces it. Every tool
surveyed has saved searches, and Vedetta already puts all filter state in the URL, so
this is a named-bookmark feature rather than new machinery.

---

## Deliberately not taking

| From | Why not |
| --- | --- |
| **AI fit score 0–100** (JobOps) | ADR-0006. A label can be argued with; a score has to be trusted. The one documented failure in this whole workflow came from trusting a filter. |
| **Automatic CV tailoring** (JobOps, Teal) | The operator already has a careful, honest CV workflow that declares gaps by name rather than hiding them. A generated rewrite would be a downgrade, and it is out of scope by design: the tool notices, the human decides and acts. |
| **Application autofill** (Huntr, Simplify) | Same boundary. It also means holding credentials for dozens of ATS accounts. |
| **Aggregator and social-network scraping** (JobOps, JobFunnel) | ADR-0005, plus a standing rule against automating one particular network because the account is worth more than the coverage. |
| **Kanban drag-and-drop** (Huntr) | The stages are worth stealing (R4); the interaction is not. |

---

## Agreed order, 2026-10-07

R3 is deferred; everything else is approved.

1. **R2, employer activity** — pure query over data already held.
2. **R6, repost and staleness** — two queries, two signals currently invisible.
3. **R7, saved views** — small, and the groundwork is done.
4. **R4, pipeline stages** — a schema change and a small interface change.
5. **R5, keyword gap** — a term list and a diff.
6. ~~**R1, mailbox watching**~~ — built, then removed at the operator's request.
