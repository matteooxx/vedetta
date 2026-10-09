# ADR-0002 — Where the project files live

**Date:** 2026-10-06
**Status:** Superseded by ADR-0015 and ADR-0017 (2026-10-09)

> The decision below put the canonical copy on the operator's PC and mirrored it to
> the server. That is now reversed in full: the server holds the only copy, there is
> nothing on the PC, and the public repository is pushed from the server itself. The
> reasoning here is kept because it was right for the situation it was made in — the
> project had no code, no data and no deployment, and a PC working copy was the fastest
> way to start. ADR-0015 moved the storage; ADR-0017 removed the last PC copy.

## Context

The app will run entirely on the operator's TrueNAS SCALE NAS. The documentation
and, later, the source have to live somewhere that is editable day to day,
survives a failure, and does not leak the infrastructure's identifiers if the
project is ever published.

The operator already runs an established flow: a working copy on the Windows PC
under `mac-projects/projects/<name>/`, fast-forwarded to an archive on the NAS
after each working session, with publication to GitHub as a separate, explicitly
confirmed step. Site-specific operational material is kept in
`mac-projects/private-ops/<name>/`, outside the publishable worktree.

## Options considered

**NAS-only, in the app's own dataset.** Attractive because the files would live
where the app runs and inherit the daily ZFS snapshot. Rejected: the handbook
directory on the NAS is `root:root` 755, so SMB writes from the PC are denied and
every edit has to go over SSH; and it sits outside the git flow the operator
already uses for every other project.

**A neutral staging folder until the app has a name.** Rejected: it only defers
the decision and adds a move later.

**PC canonical, mirrored to the NAS.** Chosen.

## Decision

- Canonical: a working copy on the PC, under the `projects/` directory of the
  operator's existing project archive
- Publishable documentation: `docs/` inside that folder
- Site-specific material: a sibling `private-ops/` directory in the same archive,
  outside the publishable worktree
- Mirrored to the server archive at the end of a working session, by the same
  fast-forward the other projects use

> The two absolute paths that stood here were replaced on 2026-10-09. They named the
> PC's account and the layout of a personal Documents directory, which is the same
> class of disclosure as a path on the server, and the publication audit had swept for
> the latter and not the former. The paths are still in this file's earlier history;
> the exposure is an account name already inferable from the public one, and rewriting
> a published branch was judged not to be worth it. The audit pattern list in the
> private half now covers both shapes.

`vedetta` is a placeholder. When the app is named, the directory is renamed
and the rename is recorded in `changelog.md`.

## Why

- It is the flow already in use, so nothing new has to be learned or maintained.
- The public/private split is enforced by directory, not by remembering. The
  operator's standing rule for anything derived from the NAS handbook is to
  explain everything but keep hosts, addresses, ports, paths, serials and service
  names private; a split by directory makes a leak require a deliberate copy.
- The PC copy is editable without SSH; the NAS copy inherits the pool's
  redundancy and snapshots.

## Consequences

- Nothing in `docs/` may name a host, an IP, a port, a NAS path, a disk serial or
  a container name. Those belong in `private-ops/`.
- Before the first commit in this repo, check `git config --local user.email`.
  The global identity on this PC is a student address and has previously sent two
  commits out under the wrong author.

## Reversing this

Cheap: move the directory. Only the mirror step and any git remote would need
redoing.
