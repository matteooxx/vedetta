# Data model — step E

> **This is the design, not the schema.** It was written before any code, and the
> schema that shipped is `vedetta/db.py` — commented, migrated additively, and the
> only authority. Read this file for *why* the shape is what it is; read `db.py` for
> what the database actually contains.
>
> What diverged, as of 2026-10-09: eleven tables were designed and **sixteen** exist.
> `source_candidate` was never built — discovery proposes into the watchlist file
> instead, where a human confirms it, which ADR-0012 and the enrolment rule explain.
> Five tables arrived later and are documented in `db.py`: `posting_place` and
> `posting_skill` (a free-text column cannot be faceted), `place_meta` (which place is
> inside which, derived from the data), `run_event` (so a running poll can say where
> it has got to) and `triage_event` (append-only, so clearing a decision does not
> erase that it was made). A `mail_observation` table also exists in the author's own
> database as an orphan: the mailbox feature was built, removed at the operator's
> request, and the table it had created was left behind rather than dropped. It is not
> in the shipped schema.
>
> The event storming below needed no revision, which is the part worth noticing: the
> sixteen domain events in time order survived implementation unchanged.

**Date:** 2026-10-07
**Phase:** Step E of the design method (ADR-0004), reached with the real field shapes
of nine hiring platforms in hand rather than with assumptions.
**Shaped primarily by:** ADR-0012 (redundancy) and ADR-0013 (generic and publishable).

## Event storming — the domain in time order

Written as events because the entities fall out of them, and because the events are
what the digest and the health report are made of.

**Setting up a watch**

1. An employer is added to the watchlist.
2. Discovery runs for that employer. *Every* technique runs and each produces
   candidate sources carrying its evidence.
3. A human reviews the candidates with sample postings visible, and **confirms** one
   or more — or **rejects** them, with the reason recorded so the same wrong candidate
   is not proposed again.
4. A source is enrolled, stamped with who verified it and when.

**The daily loop**

5. A run starts.
6. Each enabled source is polled. It **succeeds**, **errors**, or **returns nothing** —
   three outcomes, never two.
7. Each item returned is a **sighting**.
8. A sighting is reconciled against known postings: a new posting, or another sighting
   of one already known, possibly through a different route.
9. A posting stops being sighted by a source that is otherwise healthy → candidate for
   **closed**.
10. Labellers run over new postings. Each attaches labels with its own provenance.
11. Postings are checked against the imported application history → **already applied**.
12. A source that has returned nothing for several runs while sibling sources for the
    same employer still work → **suspected fault**.
13. The digest is composed: ranked postings, then everything else, then the health
    section.
14. The run finishes and is recorded whether or not anything was sent.

**Afterwards**

15. The operator triages a posting: interested, dismissed, applied.
16. A posting reappears under a new identifier after having closed → **repost**
    (recorded; not acted on in the first release).

Three things in that list exist only because of ADR-0012 — events 6, 12 and the health
section of 13 — and they are the entire difference between a notifier that can be
trusted and one that goes quiet.

## Entities

```
employer ──1:N── source ──1:N── sighting ──N:1── posting ──1:N── label
    │                │                               │
    │                └──1:N── source_poll            ├──1:1── triage
    │                              │                 └──N:M── tracker_match
    └──1:N── source_candidate      └──N:1── run
```

The shape worth noticing: **an employer has many sources, and a posting has many
sightings.** Both plural facts are the redundancy of ADR-0012 expressed as structure
rather than as intention.

## Schema

SQLite, WAL mode. Written as the intent, not as final DDL.

```sql
-- WHO we watch. Configuration-derived, not authored in the database.
CREATE TABLE employer (
  id            INTEGER PRIMARY KEY,
  key           TEXT NOT NULL UNIQUE,      -- stable slug from configuration
  display_name  TEXT NOT NULL,
  channel       TEXT NOT NULL,             -- free-form; the user defines the taxonomy
  homepage      TEXT,
  careers_url   TEXT,
  enabled       INTEGER NOT NULL DEFAULT 1,
  notes         TEXT
);

-- HOW we reach them. Many per employer, on purpose.
CREATE TABLE source (
  id             INTEGER PRIMARY KEY,
  employer_id    INTEGER NOT NULL REFERENCES employer(id),
  platform       TEXT NOT NULL,            -- greenhouse | workday | phenom | ...
  identifier     TEXT NOT NULL,            -- slug/tenant, EXTRACTED, never guessed
  endpoint       TEXT,                     -- resolved URL when not derivable
  discovered_by  TEXT NOT NULL,            -- which technique proposed it
  evidence       TEXT,                     -- JSON: what justified it
  -- For platform='sitemap': the pattern that separates job pages from content pages.
  -- This MUST be per-source. A single global pattern was proven wrong in both
  -- directions within one hour (LOG-20261007-07): too loose matched
  -- 'careers-blog', too strict lost an employer whose jobs live at /careers/<uuid>.
  job_url_pattern TEXT,
  job_url_exclude TEXT,
  verified_on    TEXT,                     -- NULL = never human-confirmed = never polled
  verified_note  TEXT,                     -- e.g. the sample titles that were checked
  enabled        INTEGER NOT NULL DEFAULT 1,
  health         TEXT NOT NULL DEFAULT 'unknown',  -- ok | empty | error | suspect
  UNIQUE (employer_id, platform, identifier)
);

-- Candidates that were proposed and NOT accepted. Kept so they are not re-proposed.
CREATE TABLE source_candidate (
  id            INTEGER PRIMARY KEY,
  employer_id   INTEGER NOT NULL REFERENCES employer(id),
  platform      TEXT, identifier TEXT, endpoint TEXT,
  discovered_by TEXT NOT NULL,
  evidence      TEXT,
  sample        TEXT,                      -- the titles a human actually saw
  outcome       TEXT NOT NULL,             -- pending | confirmed | rejected
  reason        TEXT,                      -- WHY rejected — 'returned an asphalt contractor'
  seen_at       TEXT NOT NULL
);

CREATE TABLE run (
  id          INTEGER PRIMARY KEY,
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  trigger     TEXT NOT NULL,               -- schedule | manual | backfill
  seeding     INTEGER NOT NULL DEFAULT 0,  -- 1 = silent first run, sends nothing
  digest_sent INTEGER NOT NULL DEFAULT 0
);

-- One row per source per run. ALWAYS written, including on failure.
CREATE TABLE source_poll (
  id          INTEGER PRIMARY KEY,
  run_id      INTEGER NOT NULL REFERENCES run(id),
  source_id   INTEGER NOT NULL REFERENCES source(id),
  outcome     TEXT NOT NULL,               -- ok | empty | error
  http_status INTEGER,
  item_count  INTEGER,
  duration_ms INTEGER,
  error       TEXT,
  UNIQUE (run_id, source_id)
);

-- The canonical posting, independent of how many routes saw it.
CREATE TABLE posting (
  id             INTEGER PRIMARY KEY,
  employer_id    INTEGER NOT NULL REFERENCES employer(id),
  title          TEXT NOT NULL,
  title_norm     TEXT NOT NULL,            -- for reconciliation
  location       TEXT,
  location_norm  TEXT,
  url            TEXT,
  published_at   TEXT,                     -- from the platform when supplied
  first_seen_run INTEGER NOT NULL REFERENCES run(id),
  last_seen_run  INTEGER NOT NULL REFERENCES run(id),
  closed_run     INTEGER REFERENCES run(id),
  is_pipeline    INTEGER,                  -- talent pool rather than an opening
  dup_of         INTEGER REFERENCES posting(id),  -- suspected duplicate, NOT merged
  raw            TEXT                      -- the platform payload, kept verbatim
);

-- Every time a route saw a posting. The audit trail for redundancy.
CREATE TABLE sighting (
  id           INTEGER PRIMARY KEY,
  run_id       INTEGER NOT NULL REFERENCES run(id),
  source_id    INTEGER NOT NULL REFERENCES source(id),
  posting_id   INTEGER NOT NULL REFERENCES posting(id),
  platform_key TEXT NOT NULL,              -- the platform's own id: the strong key
  content_hash TEXT NOT NULL,              -- detects edits
  UNIQUE (run_id, source_id, platform_key)
);

-- Labels accumulate. They never collapse into one opaque score.
CREATE TABLE label (
  id          INTEGER PRIMARY KEY,
  posting_id  INTEGER NOT NULL REFERENCES posting(id),
  rule_id     TEXT NOT NULL,               -- from the rule file; not a code constant
  kind        TEXT NOT NULL,               -- gate | cluster | geography | pipeline | note
  severity    TEXT NOT NULL,               -- blocking | warning | info | positive
  value       TEXT,                        -- the extracted value, e.g. "5"
  explain     TEXT NOT NULL,               -- human-readable, from the rule
  produced_by TEXT NOT NULL,              -- rules | platform_field | ai_worker
  confidence  REAL,
  created_at  TEXT NOT NULL
);

CREATE TABLE triage (
  posting_id INTEGER PRIMARY KEY REFERENCES posting(id),
  state      TEXT NOT NULL,                -- interested | dismissed | applied
  note       TEXT,
  decided_at TEXT NOT NULL
);

-- Imported read-only from the user's own tracker files. Never written back.
CREATE TABLE tracker_entry (
  id            INTEGER PRIMARY KEY,
  source_file   TEXT NOT NULL,
  employer_name TEXT NOT NULL,
  role          TEXT,
  status        TEXT,
  applied_on    TEXT,
  imported_at   TEXT NOT NULL
);

CREATE TABLE tracker_match (
  posting_id       INTEGER NOT NULL REFERENCES posting(id),
  tracker_entry_id INTEGER NOT NULL REFERENCES tracker_entry(id),
  confidence       REAL NOT NULL,
  PRIMARY KEY (posting_id, tracker_entry_id)
);
```

### Four decisions embedded in that schema

**`verified_on IS NULL` means never polled.** The human-confirmation rule from the
discovery work is enforced by the schema, not by remembering it. A source that no one
has looked at cannot contribute postings.

**`source_poll` is always written.** Including on error, including on empty. This is
the row that makes silence impossible — the digest's health section is a query over
this table, and an absent row is itself a detectable fault.

**`dup_of` points at a suspicion, it does not merge.** When reconciliation is unsure
whether two sightings are the same job, both postings survive and one is flagged.
Showing a duplicate costs a glance; merging wrongly hides a posting, and hiding is the
failure this project exists to prevent.

**`rule_id` is a string from a file.** Not an enum in code. That is ADR-0013 made
structural: adding a gate is editing a data file.

## Reconciliation

In strength order. Weaker rules never override stronger ones.

1. **Same source, same `platform_key`** → the same posting. Exact, and the normal case.
2. **Different sources, same employer, identical normalised title and location** →
   the same posting. Normalisation is conservative: case, whitespace, punctuation, and
   bracketed suffixes like `(m/f/d)` or `(x/f/m)`, which the census showed are common.
3. **Different sources, same employer, similar title** → two postings, one marked
   `dup_of`. Flagged for a human, never merged automatically.
4. **A posting absent from a source whose poll outcome was `ok`** → candidate for
   closed, but only after it is also absent from every *other* healthy source for that
   employer. A posting missing from one route while another still sees it is a **source
   fault**, not a closure. This is precisely the single-point-of-failure case ADR-0012
   exists to catch.

## Configuration

Three files. The repository ships `.example` versions of each and no real data.

**`watchlist.yaml`** — who, where, and the evidence trail:

```yaml
employers:
  - key: example-corp
    display_name: Example Corp
    channel: private            # the user defines their own channels
    careers_url: https://example.com/careers
    sources:
      - platform: greenhouse
        identifier: examplecorp
        verified_on: 2026-10-07
        verified_note: "checked 3 titles, all plausible for this employer"
      - platform: workday       # a second route, deliberately
        identifier: examplecorp/External
        verified_on: 2026-10-07
```

**`rules.yaml`** — the part that must not become code. The `unless` clause is the heart
of it: it is what separates a blocking language requirement from a desirable one, which
is the distinction the operator's own notes identify as decisive.

```yaml
profile:
  languages: [it, en]
  work_authorisation: [eu]
  max_years_experience: 2

rules:
  - id: language-gate
    kind: gate
    severity: blocking
    explain: "Requires a language outside the profile"
    when:
      - matches: '(?i)\b(fluent|fluency|native|proficient|required)\b.{0,40}\b(french|german|spanish|dutch|portuguese)\b'
      - matches: '(?i)\b(french|german|spanish|dutch|portuguese)\b.{0,30}\b(required|mandatory|essential|compulsory)\b'
    unless:
      - matches: '(?i)\b(french|german|spanish|dutch|portuguese)\b.{0,40}\b(asset|a plus|advantage|nice to have|desirable|beneficial)\b'

  - id: seniority-threshold
    kind: gate
    severity: warning
    explain: "Asks for more years than the profile has"
    extract: '(?i)(\d{1,2})\s*\+?\s*years?\b'
    compare: { operator: gt, field: max_years_experience }

  - id: talent-pipeline
    kind: pipeline
    severity: info
    explain: "A continuous pipeline, not a current opening"
    when:
      - matches: '(?i)(talent (pool|community|pipeline)|no open requirement|spontaneous application)'

  - id: cluster-cloud-devops
    kind: cluster
    severity: positive
    explain: "Cloud / DevOps / SRE cluster"
    when:
      - matches: '(?i)\b(cloud|devops|sre|site reliability|platform) engineer\b'
```

**`settings.yaml`** — digest hour and timezone, mail destination, which discovery
techniques are enabled, the optional AI worker's address (absent by default), tracker
file paths and reader type, and the ranking weights.

### Two notes on the configuration

**Timezone is explicit, not inherited.** The server runs in UTC, so a fixed cron hour
drifts by an hour across the European daylight-saving change — which is three weeks
away. The digest hour is stored with its zone and resolved at run time.

**Ranking weights are configuration, not a model.** A posting's position is a
transparent sum over its labels, so it can be explained in one line in the digest and
disagreed with. Per ADR-0006 and H-3 in the hardware register, an embedding distance
would be a judgement wearing a numeric disguise; a weighted label sum is arithmetic
over facts a human can see.

## What step D should build first

The walking skeleton, in the order that surfaces risk earliest:

0. Two adapter kinds, because they cover different halves of the population:
   **Greenhouse** (22 employers, a JSON API) and **sitemap + structured data**
   (platform-independent, 6 employers confirmed and the most likely path for the rest).
1. Start with Greenhouse alone for the skeleton; add the sitemap adapter immediately
   after, since it is what makes coverage grow without per-platform work.
2. `run` → `source_poll` → `sighting` → `posting`, with a silent seeding run.
3. Three rules from a file, producing labels.
4. A digest email with a health section, sent to a real mailbox.
5. Deployed as a container on the server, bound to loopback, with a daily schedule.

One employer, one platform, three rules, one email. Everything after that is breadth
on a skeleton that has already been proven to stand up.
