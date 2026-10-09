# vedetta — project documentation

> **Published.** The project is named Vedetta (ADR-0009) and its source, these
> documents included, is public at
> [`github.com/matteooxx/vedetta`](https://github.com/matteooxx/vedetta) under MIT
> since 2026-10-09. See ADR-0017. The note that used to stand here said the app had
> no name and no disclosed purpose, which stopped being true in the first week.

This folder is the full record of how the app was planned and built, written so
that a future AI session — or the author six months from now — can reconstruct
every decision without asking. It follows the same convention as the
operator's own server handbook, which predates this project.

## Read order

1. **`decisions/`** — one file per decision, numbered. Read them in order; later
   ADRs may supersede earlier ones, and a superseded ADR says so in its header.
2. **`state.md`** — where the project stands right now. Rewritable; always
   current, never historical.
3. **`brainstorm/`** — exploration sessions. Unpruned thinking, including ideas
   that were dropped and why.
4. **`changelog.md`** — append-only, one line per change, newest last.

Four more, which the read order above used to leave out entirely:

5. **`working-backwards.md`** — the press release and FAQ written before the code, to
   cut scope. A design artefact: it describes what was *intended*, and where that
   diverged the changelog says so.
6. **`data-model.md`** — the step-E event storming and the first schema. Also a design
   artefact; the schema that actually shipped is `vedetta/db.py`, which is commented
   and is the only authority. The file's own header says what differs.
7. **`competitive-review.md`** — what comparable tools do, and the two ideas worth
   taking from them.
8. **`improvements-backlog.md`** — what is worth building next, what was done, and
   what is deliberately not being done, each with the reason.

Action logs are **not** here — they record real commands against real
infrastructure, so they live in the private half, below.

## Where the site-specific material lives

Anything naming a host, an IP, a port, a filesystem path on the server, a disk
serial or a container name is **not** in this folder. It lives in a `private-ops/`
directory beside the repository on the server, outside the git worktree, where no
commit can reach it. It was on the operator's PC until 2026-10-09; ADR-0015 moved it,
and the project now has exactly one home.

| File | Contents |
| --- | --- |
| `00-nas-context.md` | The live, verified state of the NAS this app will run on |
| `01-platform-envelope.md` | The constraints any app on this NAS must satisfy |
| `actions/LOG-*.md` | One file per executed action, with the real command output |

This split exists because this folder **is** published, and the operator's standing
rule for anything drawn from the server handbook is: explain everything, keep
resources and names private.

The first publication tested that split and it held - nothing had to be torn out. The
audit still found four things, and two of them existed **only in the git history**,
where a clean working tree proves nothing because a push publishes every commit. The
procedure and the audit patterns are recorded in the private half.

## Standing rules for this folder

- **A rejected option stays written**, with the reason it was rejected. Without
  that, the same option gets re-proposed three months later.
- **Evidence over assertion.** An action log records what the command actually
  printed. If something could not be verified, the log says so instead of
  implying success.
- **No secrets, ever** — not even in the private half. Secrets live only in the
  app's runtime env file on the NAS, mode 0600.
- Decisions are numbered `ADR-NNNN-<slug>.md`, actions `LOG-YYYYMMDD-NN-<slug>.md`,
  brainstorm sessions `SNN-<topic>.md`.
- **The split is by directory, not by judgement.** Action logs go to the private
  half unconditionally, because almost every action on this project touches the
  NAS and a case-by-case rule would drift.
