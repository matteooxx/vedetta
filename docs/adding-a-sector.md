# Using vedetta for another kind of career

**Date:** 2026-11-13. **Question this answers:** what do I change to use vedetta for a
different line of work?

Every behaviour below carries its `file:line` as of the end of Phase 2. Commands in
code blocks are the ones shown by `vedetta/cli.py`; section 2 says exactly which I ran.

## 1. What is configuration and what is code

ADR-0013 states the principle: *code contains mechanism, configuration contains the
case* (`docs/decisions/ADR-0013-generic-and-publishable.md:24`), with the table at
`:27-34`. For a new career that means you edit files, not Python:

| What | Where | Read at |
| --- | --- | --- |
| Level words that accept or reject (`accept_level`, `reject_level`) | `profile.yaml` | `vedetta/profile.py:263-273`; shipped example `config/profile.example.yaml:30-34` |
| Skills you have / want to watch | `profile.yaml` `skills.have`, `skills.watch` | `configstore.py:142` |
| Locations | `profile.yaml` `locations.*` | `configstore.py:139-141` |
| Role clusters and gates | `rules.yaml`, rules with `kind: cluster` / `gate` | e.g. `tests/fixtures/nontech/rules.yaml:7-28` |
| Whether a cluster match is required | `profile.yaml` `tracks.require_match` | `configstore.py:143` |
| The years number | `rules.yaml` `profile.max_years_experience`, read by the years gate | `configstore.py:147`, `labels/engine.py:69`, `:133-135` |

The mechanism stays in code: the rule engine, the adapters, reconciliation, run
accounting. `tests/test_nontech_fixture.py` runs a synthetic nursing, retail and catering
configuration through the real code with no change under `vedetta/`
(`test_nontech_fixture.py:1-12`).

**Read its limit first:** the fixture was written by someone who knows the tech side of
this project, not nursing, retail or catering. It proves the *code* is not in the way. It
does **not** prove those rules would be any good for a nurse or a chef
(`test_nontech_fixture.py:3-6`).

## 2. Verdicts are a cache: changing the rules is not enough

A posting is judged once, when first seen, with the configuration of that moment
(`run.py:473-489`), and the labels are stored. Edit `rules.yaml` or `profile.yaml` and
postings already collected keep their old verdicts until you run:

```
vedetta relabel
```

`relabel` judges every stored posting again (`run.py:580-587`); the command is
`cli.py:8`, installed as `vedetta` (`pyproject.toml:20-21`). It takes the run lock, so it
refuses while a run is in progress (`cli.py:226-235`). Triage decisions are never touched
(`run.py:589`; test `tests/test_relabel.py:269`). The interface has a button for it
(`web/app.py:475`).

What changed with P4:

- A posting with a row in `posting_text` is judged again, whole, on the text first sight
  read (`run.py:626-633`). **`relabel` is idempotent**: with the configuration unchanged,
  a second pass changes nothing (`tests/test_relabel.py:455-466`).
- A posting with **no** stored text (collected before the table existed, or from a
  platform whose `raw` has no body) used to lose every label its body had given. It no
  longer does: rule B, *what cannot be recomputed is not deleted* (`run.py:591-606`,
  `tests/test_relabel.py:469-494`). `relabel` prints how many were judged this way
  (`cli.py:240-241`).
- **The limit of rule B for a new sector:** it keeps labels the posting *already had*
  (`run.py:635-639`). A rule you add today does not reach the body of a posting that has
  no stored text; it is judged on the title (`run.py:641`). `vedetta backfill-text`
  (`cli.py:245-273`; reports only, `--apply` writes) rebuilds the text for Greenhouse
  postings alone (`backfill.py:3-9`, `:78-80`).

Commands I ran for this page: `python -m vedetta.cli --help`, `... relabel --help` and
`... backfill-text --help`. I did **not** run `relabel` or `backfill-text` against a
database; their behaviour above is from the code and from the tests, which I ran
(`tests/test_relabel.py -k "unchanged or recoverable or cluster_found or gate_found or
kept_label or first_sight"`: 13 passed).

## 3. Known limits, measured

`tests/test_nontech_fixture.py` ends with five `xfail` tests, **deliberately not strict**:
each is a place where the first real non-tech user will hit a wall, a measurement and not
a to-do list; when one starts passing it shows as XPASS (`:8-11`, `:201-202`). I ran the
file: 14 passed, 5 xfailed.

1. **Level ranges** (`:204-212`). `level_verdict` looks for each listed word or phrase as
   whole text inside the title, so `band 6` is not found in "Band 5-7", and a profile that
   accepts band 6 does not see an advert open to bands 5-7. (With `band 5` listed,
   "Band 5-7" is accepted, by chance: the lower end matches.)
2. **A level declared outside the title** (`:215-224`). `level_verdict` reads the title
   only; the Greenhouse adapter puts title, location and description in the text, and a
   structured field such as metadata `Level: Band 6` stays in `raw`, which nobody reads.
   In health care the level is often only there.
3. **Department and contract type** (`:233-246`, two tests: `department`,
   `contract-type`). A rule reads only `title`, `body` or `all` (`labels/engine.py:94-102`)
   and `apply()` receives only title and text, so a rule with `field: department` never
   fires on a department held in `raw`. In non-tech sectors it is often the best signal.
4. ~~**An unknown `field` is not an error**~~ — **fixed on 2026-11-17** (`5609799`).
   Until that day an unknown `field` fell back silently to `all`
   (`labels/engine.py:102`), so `field: department` read title and description
   together and fired on any mention in the text: a wrong and plausible result
   instead of an error. Rules are now **refused when they are compiled**, at the same
   point where an invalid regex already fails the run, so the interface and the daily
   run refuse in the same words — and the message names the rule, the offending value
   and the allowed ones. It also says what cannot be done: a rule reads the title and
   the advert's text, and cannot be narrowed to a department, a contract type or any
   other structured field. Not to be confused with `compare.field`, which names a
   profile number and is not a scope.

Three limits, four tests, because item 3 is parametrized over two fields. This is the
whole list; this page adds none and removes none.

The fourth limit is kept above, struck through, rather than deleted: a guide that
quietly drops a limit it once documented leaves the next reader unable to tell a
defect that was fixed from one that nobody ever noticed. What changed is the
behaviour, and the date and the commit say when.

## 4. Warning about the shipped lists

`config/profile.example.yaml` has `associate` among the accept words (`:30`) and `manager`
among the reject words (`:33-34`). Sensible in software; **harmful in retail**, where
"Store Manager" and "Sales Associate" want the opposite treatment. The fixture shows it is
configuration, not code: with the two words in the right lists, Store Manager is rejected
and Sales Associate accepted; swapped, both invert
(`test_nontech_fixture.py:175-197`). Rewrite both lists for your trade before trusting
the workable count.

Separate from the limits above, and not a sector limit: a title holding words from
**both** lists used to read `accept`, because `accept_level` was tested first. **Fixed on
2026-11-17** (`68b2b0c`): `reject_level` is tested **first**, so "Associate/ Vice
President" is rejected on `president` even though `associate` is an accept word. The
strict `xfail` that pinned it is gone. For a sector this is the behaviour to count on
when a title carries a junior word and a senior one at once — the senior one decides.
