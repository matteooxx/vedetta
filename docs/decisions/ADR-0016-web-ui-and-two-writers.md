# ADR-0016 — A web interface, with the configuration files still authoritative

**Date:** 2026-10-07
**Status:** Accepted
**Operator instruction:** a graphical interface running on the server to configure
every preference, **and** the ability to do the same by editing the project files
directly.

## Context

Two separate questions arrived together.

**Why is nothing on the server's Apps page?** Because the first release is a batch
job: a container that starts, runs for a few seconds and exits, triggered by cron.
The Apps page lists long-running services managed by the server's middleware. A
daily job packaged as one of those would be a container idling for 23 hours and 59
minutes, with a health check reporting that the idling is going well.

**The interface, however, is a service** — it has to be up whenever the operator
opens it. So it belongs on the Apps page, and that is where the visibility the
operator is missing will come from.

The harder question is the second instruction. Configuring from both a UI and the
files means **two writers to the same state**, which is where this kind of project
usually acquires a permanent, quiet inconsistency.

## Options considered for the two writers

**The interface writes to the database; files are import-only.** Simple to build and
the usual choice. Rejected: it makes the files second-class. An edit made in a file
would need an explicit import, a change made in the UI would never appear in the
file, and within a week nobody would know which one was true. It also contradicts the
instruction.

**Split authority** — files own structure, the database owns UI-settable values.
Rejected: the boundary would be arbitrary, and every new setting would require
deciding which side it falls on. That decision would be got wrong eventually.

**The files are the single source of truth and the interface is an editor for them.**
Chosen.

## Decision

### Deployment

- **`vedetta-ui`** is a long-running TrueNAS Custom App, visible on the Apps page,
  bound to **loopback** and published to the tailnet over HTTPS. Not on the LAN in
  clear, not on the internet.
- **The scheduled run stays a cron-triggered container.** It does *not* move inside
  the UI process.

That second point is deliberate and it costs an extra moving part. If the daily run
lived inside the UI service, a crashed or stopped UI would mean no digest — and,
worse, no digest is exactly what this project treats as a signal that something is
wrong, so the failure would be ambiguous at the moment it mattered. Keeping them
separate means the interface can be down all week without the watch missing a day.

The UI still offers a "run now" button, which runs the same code against the same
database.

### Configuration: the files win, always

- The UI **reads and writes the same YAML files**. There is no second copy and no
  import step.
- Writes are **comment-preserving**. The rule file's comments explain what the rules
  are for; a UI that silently stripped them would make the file worse every time it
  was touched.
- Every write is **guarded against a concurrent edit**: the UI records the file's
  hash when it renders the form and refuses to save if the file changed underneath.
  It shows what changed and lets the operator decide, rather than overwriting.
- Every write **validates first** — parse, then check the shape — and **keeps a
  timestamped backup** beside the file. A rule file that does not parse would silently
  disable every gate, so it must never be possible to save one.
- The database is **derived state**, rebuilt from the files on every run. Nothing of
  the operator's intent lives only in the database.

### Concurrency

Both the cron run and the UI's "run now" can write the same SQLite database. A run
takes a lock and a second attempt reports that a run is in progress rather than
interleaving.

## Why

- One source of truth means the two ways of configuring cannot disagree. Editing a
  file and editing through the UI are the same act performed with different tools.
- It keeps the project honest for anyone else: the files are the documented interface
  and work with no UI at all, which matters because a published tool should not
  require a browser to be configured.
- Comment preservation is what makes the file half genuinely usable rather than
  nominally supported.

## Consequences

- A comment-preserving YAML round-trip library is now a dependency of the UI. It is
  not a dependency of the daily run, which only reads.
- The UI needs a conflict screen, which is more work than a save button but is the
  part that makes two writers safe.
- A validation schema has to exist for all three configuration files. This is good:
  it was owed anyway, and it gives the file-editing path validation too, through
  `vedetta check`.
- The Apps page will show the interface, not the watch. The watch is a cron job, and
  the UI's dashboard reports when it last ran and what happened — so "is it working?"
  is answered in the UI rather than by the presence of a container.
- Source enrolment gets a natural home: the UI can show the candidate sources a
  discovery run proposed, with sample postings, and require a human to confirm each
  one. That rule was established twice over by independent false positives; until now
  it lived only in a YAML field.
