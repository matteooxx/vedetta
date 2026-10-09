# vedetta — project documentation

> **Working name.** The app has not been named yet, and its purpose has not been
> disclosed yet. `vedetta` is a placeholder; renaming the directory is a
> deliberate step recorded in `changelog.md` when it happens. See ADR-0002.

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

Action logs are **not** here — they record real commands against real
infrastructure, so they live in the private half, below.

## Where the site-specific material lives

Anything naming a host, an IP, a port, a filesystem path on the NAS, a disk
serial or a container name is **not** in this folder. It lives outside the
worktree in `mac-projects/private-ops/vedetta/`:

| File | Contents |
| --- | --- |
| `00-nas-context.md` | The live, verified state of the NAS this app will run on |
| `01-platform-envelope.md` | The constraints any app on this NAS must satisfy |
| `actions/LOG-*.md` | One file per executed action, with the real command output |

This split exists because this folder is a candidate for public publication and
the operator's standing rule for anything drawn from the NAS handbook is:
explain everything, keep resources and names private.

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
