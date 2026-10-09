# ADR-0015 — The PC copy is temporary; the server becomes the only home

**Date:** 2026-10-07
**Status:** Accepted
**Supersedes the permanent half of:** ADR-0002

## Context

ADR-0002 chose the PC as the canonical location, mirrored to the server, because it
matched the operator's existing flow for every other project.

The operator has now said that is acceptable **for now**, and that in future
everything must live exclusively on the server.

## Decision

Two phases, with the end state designed for from the start.

**Phase 1 — now.** Planning documents stay on the PC and are mirrored to the server.
Nothing has been built yet, so nothing is at risk.

**Phase 2 — when code exists.** The server holds everything: source, configuration,
runtime data, and the git repository with its remote. The PC keeps at most a working
clone, with no authority. The private notes move to the server's dataset, outside any
published tree.

## What has to be true now so Phase 2 is cheap

These are the real content of this decision. A migration that was not designed for is
a rewrite.

- **No absolute paths from either machine** anywhere in code or configuration. Paths
  come from configuration with sensible relative defaults.
- **No assumption that the tracker files are on the same machine**, or on a Windows
  filesystem. The reader takes a path from configuration (ADR-0010, generalised by
  ADR-0013) and treats the file as data that may be absent.
- **The repository must be clonable and runnable on the server** without a
  PC-shaped step. The build runs there; it is where the container is produced.
- **Private material never enters the published tree**, regardless of which machine it
  sits on. The public/private split is a property of the repository, not of the
  filesystem — which is what makes it survive the move.
- **Line endings and file mode** are set so a Windows-authored file does not appear
  modified on the server. The operator's other projects already hit this: comparisons
  there need `core.filemode=false`. Fix it in `.gitattributes` from the first commit
  instead of working around it forever.
- **Git identity is set per repository** before the first commit. The global identity
  on the PC is a student address and has already sent commits out under the wrong
  author in another project.

## Why phases rather than moving now

Editing over SSH for every revision is friction during the phase where the documents
change several times an hour, and the server's handbook directory is `root:root` 755,
so writes over the file share are refused. Phase 1 costs nothing while there is no
code. The moment there is code, the balance reverses: the code has to build and run on
the server anyway, so that is where it should live.

## Consequences

- A migration step is owed, and it is recorded here rather than remembered: move the
  tree into the server dataset, create the dataset and its snapshot task, set the git
  remote, verify a clean build and a clean run, then delete the PC copy's authority
  (not necessarily the files).
- Until then, every document and every file written must satisfy the constraints
  above. They are cheap now and expensive later.
- The daily snapshot task on the app's dataset, specified in the platform envelope,
  becomes the protection for the planning documents too once they move.
