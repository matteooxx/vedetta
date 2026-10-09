# Current state

**Last updated:** 2026-10-09 (twenty-third revision — published)

## Phase

**All four design steps are complete, the first release is deployed, and the project
is published** at `github.com/matteooxx/vedetta` under MIT. It is now in operation,
and the work ahead is breadth (more adapters) and tuning (the rule file), not design.

The publication is the test ADR-0013 set for itself in the first week: generic and
publishable from the first line, not retrofitted. Nothing had to be torn apart to do
it, which is the answer. The private half — one machine's layout, one person's
targeting rules — stays on the server and is not in the repository.

Design, step A of four. The method is A → B → E → D (ADR-0004):

| Step | What it is | Status |
| --- | --- | --- |
| **A** | Constraints-first: define the platform envelope the NAS imposes | **Done** — `private-ops/vedetta/01-platform-envelope.md` |
| **B** | Working backwards: press release + FAQ, to cut scope | **Draft 1 complete** — `working-backwards.md`. Five open items before it becomes the plan |
| **E** | Event storming: domain events → entities → schema | **Complete** — `data-model.md`: 16 domain events, 11 tables, reconciliation rules, three configuration files |
| **D** | Walking skeleton: thinnest end-to-end slice, deployed | **Complete and running.** Dataset, snapshot task, container, cron job. Verified live; details in `actions/LOG-20261007-08` |

C (funnel interview) is held in reserve: if B leaves gaps, the gaps get targeted
questions rather than a full interview.

## What is known about the app

A job-search monitor: it watches the careers pages of employers the operator cares
about, detects new postings, and emails him about them.

The reframing that came out of brainstorming: the operator is not missing a way to
find or to apply for jobs — he has a mature, hand-maintained process for both. He
is missing **the watch**. So this is a sensor feeding an existing workflow, not a
replacement for it. Details in `brainstorm/S01-problem-and-design-tensions.md`;
the personal targeting rules it has to apply are digested privately in
`private-ops/vedetta/02-targeting-rules-digest.md`.

Technical feasibility of the core mechanism was probed live and holds: the hiring
platforms tested answer unauthenticated requests with clean JSON carrying stable
posting IDs and publication dates, so no headless browser is needed. Evidence in
`actions/LOG-20261006-03-ats-feasibility.md`.

## What is decided

| ADR | Decision |
| --- | --- |
| 0001 | Documentation system: handbook-style, one file per decision and per action |
| 0002 | Location: PC canonical under `mac-projects/projects/`, mirrored to the NAS |
| 0003 | Language: English for documents, Italian for conversation |
| 0004 | Design method: A → B → E → D, with C in reserve |
| 0005 | Sources: employer careers pages only in the first release, via per-platform adapters |
| 0006 | The app labels deterministically; no model call inside it, and no fit verdict |
| 0007 | Existing trackers are read one-way; the app never writes to them |
| 0008 | One email digest per day at a fixed hour; silent first run; nothing ever hidden |
| 0009 | The project is named **Vedetta** — the lookout who sights and signals, and does not decide |
| 0010 | The trackers reach the server as a synced copy whose tables the app parses |
| 0016 | A web interface as a Custom App; the configuration files stay the single source of truth |
| 0011 | `ats-scrapers` is a reference implementation and discovery aid, not a dependency |
| 0012 | **Redundant by design** — every technique runs, disagreements are surfaced, silence is impossible |
| 0013 | **Generic from the first line** — mechanism in code, the case in configuration; publishable |
| 0014 | The server is the only host; AI is an optional external worker. Amends ADR-0006 |
| 0015 | The PC copy is temporary; the server becomes the only home. Supersedes part of ADR-0002 |

## What is proposed but not yet decided

These came out of step A and need the app idea, or an operator ruling, before
they can become ADRs. They are listed in full in the platform envelope:

- Which port the app binds, and whether it is tailnet-only or also LAN-visible
- Whether the app holds data the operator would miss, which decides how hard the
  export path has to work — **there is no off-site backup of this NAS**
- Whether the app needs outbound internet access or any third-party credential
- Resource ceiling (the envelope proposes a default; it is not binding yet)

## Where to look next

`competitive-review.md` compares Vedetta against JobOps, Huntr, Teal and JobFunnel.
**Five of the six approved items are in place**: Signals, saved views, the triage
ladder, the technology comparison, and repost and staleness detection. Mailbox reading
was built and then removed at the operator's request. Salary extraction was declined —
the EU directive is not live on any European portal yet.


`improvements-backlog.md` holds 18 proposed improvements in priority order. Four adapters are done — Greenhouse, sitemap, SmartRecruiters and Workday — covering
36 confirmed sources across 39 employers. Next are **B2b** (country-less schema.org
addresses slipping past the location exclusions), **B3** (showing which rule produced
an exclusion and on what text), and a decision on the three large boards deferred for
request-volume reasons.

## Immediately actionable

1. **Nothing is blocked.** Mail needed no credential in the end: the digest is
   delivered through the machine's own mail configuration, which already works and
   already sends the server's alerts. The application holds no secret of any kind —
   nothing to create, rotate or leak.
2. **Three queued digests are waiting for the next scheduled run** to deliver them:
   runs 18 and 19, rebuilt after the fact because they were never reported, and run 20,
   queued normally. Delivery is the runner's job and it retries, so this needs nothing
   doing — it is noted because an unsent digest is the one failure the reader cannot
   discover by reading their digests.
3. **Decide what to do about the older unreported runs.** `vedetta digest --list` names
   nine runs that found postings and reported none; seven are from the enrolment days,
   483 workable postings between them, and they are better left as database history than
   mailed as news. The operator may disagree, and one command each rebuilds them.
4. **B8, B9, B10 and B2b are all done** (2026-10-09). The location rules now reach
   everything the platforms give them anything to work with: 21 of 415 workable
   postings have no location verdict, down from 184 of 416, and 16 of those 21 have a
   location field reading "N/A" or "LOCATION".
5. **Nothing is blocked.** The remaining backlog is B3, C1b, C2, C4, C5, C6 —
   convenience and polish, none of it load-bearing. B2b, B8, B9, B10, B11, C3, C7 and
   C8 are done.

## The method that is worth keeping

The twentieth revision changed how postings are judged, which is the most dangerous
kind of change here: it can exclude a posting the reader would have taken, and an
exclusion is silent by nature. So the change was **predicted against the live database
before it was allowed to touch it** — every open posting judged under both the old and
the new configuration, the moves counted, and every posting that would go from workable
to excluded listed individually with the reason that decided it.

That run found five defects the test suite had passed, one of which would have let a
whole continent in. It cost one script and two minutes. Any future change to the
judging rules should do the same thing, and the script is worth keeping for it.

## The lesson from the eighteenth revision

Redundancy was designed across the adapters, where two platforms can disagree about a
posting and the disagreement gets surfaced. It was never designed across the two ways a
run can start, and that is exactly where the project's own cardinal failure got in: a
run from the interface recorded 117 postings and queued no digest, so the postings
stopped being new and nobody was ever told. It was found by chance, while checking that
a notice rendered.

Two things follow, and they are worth applying to whatever is built next here:

- **A second opinion has to cover the paths, not only the data.** Two sources agreeing
  about a posting is worth nothing if one of the two routes through the code silently
  skips the step that reports it.
- **Duplicated logic is the vector.** The digest code was correct throughout. One of its
  two callers simply never called it, and a unit test suite of 180 tests could not see
  that, because every unit worked. The fix was one shared function, and the test that
  would have caught it is a test of the wiring.

## The lesson from the nineteenth revision

Both of these are about tests, and both cost real data rather than time.

- **A test can only confirm a format it did not invent.** Two of them failed this way
  in two days. A reader of `blocked_by` was written to parse JSON, and its test wrote
  the row itself, in JSON, and passed — the application stores a `"; "`-joined string,
  so it raised on the first real database. Then a duplicate finder was keyed on
  employer, title and URL slug, and its test gave the two openings *different* slugs,
  so it never asked the question the implementation got wrong: Cisco posts one title in
  several cities under the same slug, and that version would have folded real openings
  together.
- **A flag that disables a safety behaviour must be set deliberately, never inferred.**
  `partial` blocks closures, which is correct. The first version inferred it from any
  adapter note existing, and the sitemap adapter has a note it emits on every single
  run. Cisco would never have closed a posting again — silent, permanent, and exactly
  the failure class this project is organised against, arriving inside the fix for
  another one.

The pattern across both revisions: the mechanisms here are sound and the wiring between
them is where the losses come from. Four defects in two days, every one of them at a
join — two callers of one function, two meanings of one flag, two formats for one
column, two rows for one job.

## Open risks carried from the platform

- The NAS has **no off-site backup**. Local ZFS snapshots are the only recovery
  window. Any app that accumulates data the operator cares about needs its own
  export path, designed in, not bolted on.
- Custom cron scripts for existing apps live on the single-disk boot pool, whose
  SSD is near end of life. A new app should keep its scripts on `tank` instead.
- The platform has a recurring Docker image-store corruption failure mode (F-27)
  which has repeatedly cost locally built images their tags. It is now
  automatically recovered, but a new app's deploy design must survive it.
