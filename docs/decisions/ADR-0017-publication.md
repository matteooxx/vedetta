# ADR-0017 — Published under MIT, documents included, pushed from the server

**Date:** 2026-10-09
**Status:** Accepted
**Completes:** ADR-0013 (generic and publishable)
**Supersedes the remainder of:** ADR-0002 (PC canonical, mirrored to the server)

## Context

ADR-0013 required this project to be generic and publishable **from the first line**
rather than retrofitted, on the grounds that retrofitting never happens. Publication
was the test of that claim, and it was passed rather than argued: nothing had to be
torn apart. The mechanism was already in code and the case already in configuration,
so the audit found no architectural work — only four smaller things, discussed below.

ADR-0015 had moved the storage to the server in two phases and left Phase 2 as a
future step. By 2026-10-09 the server held everything that mattered and the PC held a
stale duplicate of the documents plus a clone used only to push. Keeping it would have
meant two copies drifting, which is exactly what ADR-0015 existed to prevent.

## Decision

**Public, under MIT, at `github.com/matteooxx/vedetta`.** `pyproject.toml` had
declared MIT since the first commit with no file to back it up; GitHub reads the file.

**The documents are published with the code.** All 27 of them: the sixteen decision
records, the data model, the changelog, the three brainstorming sessions, the
competitive review and the backlog. The code shows what was built; the records show
why, including what was tried and rejected. Publishing one without the other would
halve what the repository is worth to a reader.

**The private half stays private and moves to the server.** One directory beside the
repository, outside the git worktree, mode 700: the machine's layout, the hardware
horizon, the operator's own targeting rules, the watchlist candidates and the action
logs. The split is by directory and not by judgement, because almost every action on
this project touches the server and a case-by-case rule would drift.

**The server pushes, not the PC.** Authenticated by a **deploy key**, not a personal
access token. A deploy key is bound to one repository by construction: if the machine
were taken over, the key could write to this repository and to nothing else on the
account. A token is scoped only by how it was configured, and a configuration can be
widened by whoever holds it — the difference between a limit that is structural and a
limit that is a setting. The private half of the key never leaves the machine, lives
outside the worktree so no commit can carry it, and GitHub's host keys are pinned from
the vendor's HTTPS API rather than accepted from whatever answers first.

**Nothing publishes automatically.** The daily run commits nothing and the interface
commits nothing. A commit on the server is private until somebody runs the push.
Publishing is the one action in this project that cannot be taken back, and it should
not be a side effect of a scheduled job.

**Every push that adds files is audited over the whole history, not the working tree.**
A push publishes every commit, so a clean checkout proves nothing.

## What the audit found, and why it is recorded here

Two of the four things existed **only in history**, which is the part worth
remembering:

1. A timestamped backup of a real configuration file, swept into an early commit
   before `.gitignore` covered that shape. No credential in it — every secret field
   was empty, as designed — but somebody's working file nonetheless.
2. The runner named one absolute path on the machine.

Both were rewritten out of all commits before the first push, which costs nothing
beforehand and a forced rewrite afterwards.

The path turned out to be a **bug as well as a disclosure**: the runner now derives its
own root, so a stranger's clone works where it stands instead of only on the machine it
was written for. Every privacy fix on this project has had that shape — the thing that
made the code specific to one person was also the thing that made it worse.

The fourth was on no checklist. The documents quoted the author's own job-search
statistics as evidence that the problem was real: how many applications, and how many
had gone unanswered. The evidence survives as a shape rather than a figure. A
prospective employer reading this repository has no business learning how many times
its author has been ignored.

## Alternatives rejected

**Code only, documents withheld.** A leaner repository, and the usual choice. Rejected:
the decision records are the half a technical reader values, and withholding them would
leave every "why is it like this?" unanswered in a project whose whole discipline is
answering exactly that.

**A personal access token instead of a deploy key.** Simpler to create. Rejected for
the scoping reason above.

**Push from the PC.** It already held the credential. Rejected: it requires a second
copy of the project to exist, which is what ADR-0015 was for.

**Automatic push after every commit.** Rejected. See the decision.

## Consequences

- The repository is the public face of the project and the changelog is part of it, so
  a changelog entry is now writing for strangers. That is a feature: a claim that
  cannot be verified live does not survive being written down for someone else.
- Pushing needs the key. If it is ever lost, generate a new one on the server and paste
  the public half again; there is no reason to copy it anywhere for safekeeping.
- Anything added to `docs/` is published the moment it is pushed. The private half is
  the default home for anything naming the machine, and the directory rule makes that
  decision for us rather than leaving it to attention.
