# Set vedetta up for me

**This file is a prompt. You are not meant to read it — your coding agent is.**

Open vedetta in whatever agent you use (Claude Code, Cursor, Copilot, Codex, an
assistant with filesystem access), attach your CV, and say:

> Follow `prompt.md` and set vedetta up for me. My CV is attached.

Then answer its questions. It writes the four configuration files, checks they work
against two real job boards, and shows you the result before anything is sent anywhere.

Everything below is addressed to the agent.

---

## Agent: your brief

You are configuring **vedetta**, a self-hosted monitor of job adverts published on
companies' own career sites. It polls a watchlist once a day, judges each posting
against its reader's profile, and emails one digest. It is not a job board and not a
recommender: it reads what employers publish and explains every verdict it reaches.

Your job is to turn a CV and a short conversation into a working configuration, so that
the person never has to read 2,000 lines of commented YAML.

### Before you ask anything

Read these, in this order. They are written to be read, and they contain the reasons
behind every field you are about to fill:

1. `README.md` — what the thing is, and the install commands.
2. `config/profile.example.yaml` — the file that decides whether a posting is workable.
   The comments explain regions, specificity and the traps. This is the one that matters.
3. `config/watchlist.example.yaml` — who to watch, and why `verified_on` exists.
4. `config/rules.example.yaml` — the 15 shipped rules: six gates, six role clusters, a
   note, a pipeline marker and an out-of-track filter.
5. `config/settings.example.yaml` — delivery, ranking weights, saved views.
6. `docs/data-model.md` — read at least the part about what is never deleted.

**Speak to the person in their own language.** Infer it from how they write to you. This
file is in English because the repository is; that is not a reason to make them read
English.

### Two rules you do not break

**The CV is theirs, not yours to spread.** Do not commit it, do not copy it into the
repository, do not paste it into a web search, an issue, a commit message or any
third-party service. Read it, use it, and leave it where it was. If you need to quote a
line back to them, quote it in the conversation only.

**Nothing in this project deletes a posting.** An excluded posting is counted,
explained, and one click away. That is the whole design: a filter that drops a posting
quietly fails with no trace. So when you are unsure whether something should block a
posting, make it a **warning instead of a blocker** — a visible warning they overrule
costs them ten seconds, a wrong exclusion costs them a job they never saw.

---

## What you produce

Four files in `config/`, copied from their examples and edited:

| file | what it decides |
|---|---|
| `profile.yaml` | whether a posting is workable **for this person** |
| `watchlist.yaml` | which employers get polled, and through which source |
| `rules.yaml` | what to spot in a posting's text, and how severely |
| `settings.yaml` | delivery, ranking weights, saved views |

Plus `.env` from `.env.example`, **left with empty values** unless they ask otherwise —
see *Where you stop*.

---

## What to read from the CV

Extract these, then **show the person what you extracted and let them correct it**. A CV
is a sales document; it overstates and it omits, and they know which is which.

- **Skills** → `profile.skills.have`. Only what they could honestly defend in an
  interview. Matching is whole-word and case-insensitive, so `AWS` catches `AWS Lambda`
  while `Java` does not catch `JavaScript`. Twenty entries is plenty; a hundred is a tag
  cloud that makes every posting look like a match.
- **Years of experience** → `experience.years` (descriptive) and, more importantly,
  `profile.max_years_experience` in `rules.yaml`, which is what the years gate actually
  reads.
- **Languages** → `identity.languages`, and check them against the `language-gate` rule
  in `rules.yaml`, which has its languages written into its own pattern.
- **Field and seniority** → which `cluster-*` rules to keep, drop or write. The shipped
  clusters are cloud/devops, software engineering, solutions architecture, presales,
  support engineering and AI. **If the person's field is not among them, do not bend an
  existing cluster to fit** — write new ones and follow `docs/adding-a-sector.md`.
- **Current location and recent employers** → context for the location questions below.
  Never conclude work authorisation from a CV: see the first question.

---

## What to ask

A CV cannot tell you any of this, and getting it wrong is what makes the digest useless.
Ask in small batches, with your own suggestion attached to each, so they can say "yes" to
most of it. Explain *why* you need each one — people answer better when the consequence
is visible.

**1. Where they can legally work.** The most important answer in the whole setup, and
the one a CV never states. A passport, a visa, a permit, a spouse's nationality. You are
filling four buckets:

- `preferred` — where they actively want to be;
- `acceptable` — where they can work without anyone sponsoring them;
- `conditional` — workable **only if** the employer sponsors. Flagged, never hidden;
- `excluded` — not workable.

Use the **region** names where they fit: `EU`, `EEA`, `Schengen`, `Europe`,
`North America`, `Asia`, `Middle East`, `Africa`, `Oceania`, `Americas`. For someone
with EU citizenship the boundary is legal, so `EU` is right and `Europe` is wrong —
Europe includes the UK and Switzerland, where they would need sponsorship, and those
belong in `conditional` by name. A specific rule beats a region, which is what keeps the
visa warning on a London posting when `EU` is acceptable.

**2. Remote, and how far they would actually move.** `remote_counts_as_acceptable`
decides whether "Remote" with no country attached counts as workable. Ask whether a
posting in an acceptable country but a city they would never move to is still of
interest — the answer is usually yes, because remote and hybrid are negotiable.

**3. What they are looking for, which is not always what they have done.** Someone whose
CV says sysadmin may be aiming at SRE, or leaving the field entirely. The clusters follow
the target, not the history.

**4. Which levels to accept and which to reject.** `accept_level` and `reject_level` are
matched **word by word against the posting title**. Two traps worth naming: reject is
tested first and wins, so `Associate Renewals Manager` is senior and not junior; and a
word in `reject_level` hides every posting whose title contains it, so `manager` is a
blunt instrument in a field where everything is called manager.

**5. Deal-breakers.** For each, ask whether it should **block** a posting or only
**warn**: a security clearance they cannot get, a live coding test, on-call, contract
versus permanent, a required language they do not speak, a degree they do not have. The
answers become `exclude_if`. Default to warning. The shipped profile blocks
`no-target-track`, `location-excluded`, `level-too-senior`, `language-gate`,
`visa-not-sponsored`, `enrolment-required` and `out-of-track-sales`, and deliberately
leaves `seniority-threshold`, `clearance-required`, `coding-test-gate`,
`location-conditional`, `location-unknown` and `talent-pipeline` as warnings. Verify that
list against the file rather than this one: `exclude_if` is the whole of it, and anything
not named there is a warning by definition.

**6. `tracks.require_match`: on or off.** On, a posting must match one of their role
clusters to be workable. It is the single most effective setting here and the most likely
to be wrong, because it fails whenever the clusters are too narrow. Recommend **on**, and
tell them to read the excluded list for a week before trusting it.

**7. Who to watch.** See below — this is the part that takes the longest and the part
they will get most out of.

**8. Where the digest should go.** Record it in `settings.digest.to` or leave it for
`VEDETTA_MAIL_TO`. Do not set up delivery: see *Where you stop*.

---

## The watchlist: propose, then verify, then ask

The CV tells you their field, level and area. It does not tell you which employers to
watch, and an empty watchlist makes vedetta an empty inbox.

**Propose first.** From the CV and their answers, draft **15 to 30 employers** who
plausibly hire this person in the places they can work, and show the list with a line of
reasoning each. Expect them to cut half of it and add names you would never have found —
that is the point of showing it rather than guessing silently.

**Then find each one's real source.** For every employer they keep, work out how their
careers site actually publishes postings, in this order of preference:

1. **A known applicant tracking system.** Exactly four platforms have an adapter in
   this build: **`greenhouse`**, **`workday`**, **`smartrecruiters`** and **`sitemap`**.
   Check for yourself rather than trusting this line — `python -c "from vedetta.run
   import ADAPTERS; print(sorted(ADAPTERS))"` — because the list grows. The first three
   have proper endpoints and are cheap to poll; find the tenant or board identifier on
   their careers page. **A platform with no adapter cannot be polled**, and the poll
   reports `this build has no adapter for '<name>'` rather than pretending the employer
   is quiet. If an employer uses one of those, your options are `sitemap` or
   `docs/adding-an-adapter.md`.
2. **`sitemap`**, which needs no API, no tenant and no identifier: the careers site's
   `sitemap.xml` plus `JobPosting` markup on the detail pages. It is the one that does
   not care what software the employer bought, and it is the answer for every employer
   whose platform has no adapter. It needs **`job_url_pattern` set per source** — there
   is no global pattern that separates job pages from blog pages, and a single one was
   wrong in both directions within an hour of testing. Check that the sitemap actually
   lists **adverts**: a corporate sitemap full of marketing pages and blog posts is a
   dead end, and two were found that way.
3. **Nothing.** Say so, and leave the employer in the watchlist **without
   `verified_on`**. It is then stored, never polled, and listed in the digest under
   `NOT WATCHED` — so the gap is visible instead of silent.

**Then verify, and let them confirm.** `verified_on` means *a human looked at real
postings from this source and confirmed they belong to this employer.* This is not
ceremony: during design, two independent automated discovery techniques each returned a
different company for the same employer, one of them a road-paving contractor returned as
an asset manager.

So for each source: fetch a handful of real postings, **show the person the titles**, and
write `verified_on` only once they say the postings look right. Put what you saw in
`verified_note` — `"209 postings, titles consistent with the company"` is the shape.
**Do not write that date on your own judgement.** The field exists precisely because
automated confidence was wrong.

Respect `robots.txt` while you do this, and do not hammer a careers site to satisfy
curiosity: one listing request per employer is enough to show titles.

---

## Then check your work, without sending anything

In order. Stop at the first thing that is not what you expected, and say so.

```sh
pip install -e .
vedetta init             # creates the database, loads the watchlist
vedetta check            # read-only: integrity, object count, quick_check
vedetta run --stdout     # polls for real, prints the digest instead of sending it
```

**`vedetta run --stdout` is the one that tells you whether the configuration is any
good.** Read the output with the person:

- **`SOURCE HEALTH`** — every source that failed, and why. A `FAILED` line with
  `429 and no Retry-After` is a refusal and not an outage; `unreachable` is the network.
  Fix the identifiers that are wrong before going further.
- **the excluded count and its reasons** — this is where a bad profile shows. If
  `matched none of your target role clusters` excludes almost everything, the clusters
  are too narrow. If a country appears that they *can* work in, a location bucket is
  wrong.
- **the workable list** — read three or four aloud. If they would not apply to any of
  them, the profile is wrong, not the postings.

**The first run after a watchlist change seeds silently**: it records what already exists
and sends nothing, so adding an employer never produces an email with four hundred items
in it. Tell them this, or they will think it is broken.

Then iterate on the profile **without committing to it**:

```sh
python tools/predict-profile.py CANDIDATE.yaml
```

It judges every stored posting against both the saved profile and a candidate one and
**writes nothing**. The table that matters is the last one: the postings that would go
from workable to excluded, each with the rule that decided it. That is the expensive
direction — an exclusion is quiet, and a posting they would have taken does not come
back. Use this for every profile change from here on.

---

## Where you stop

Do not do these. They depend on the machine, they involve credentials, or they are the
person's decision and not yours:

- **Mail delivery.** Leave `transport: host` and `.env` empty. Explain the two options:
  `host` hands the digest to the machine's own mail configuration and needs no credential
  of its own, which is why it is the default; `smtp` needs a mailbox and an app password.
- **Scheduling.** No cron, no systemd timer, no scheduled task. Tell them the command
  (`vedetta run` then `vedetta outbox`) and the hour in `settings.digest`, and let them
  wire it to their own machine. The shipped `run-vedetta.sh` is written for one specific
  TrueNAS host and is an example, not an installer.
- **Docker, reverse proxies, exposing the interface.** Out of scope here.
- **Writing `verified_on` without their confirmation.** Covered above, and the most
  important of these.
- **Deleting or rewriting anything in `runtime/`.** The database holds their own triage
  decisions and is not reconstructible.

---

## How to report back

Short, and in their language. Six things:

1. the four files you wrote, and the one-line reason for each non-obvious choice;
2. what `vedetta check` returned;
3. the poll result: how many sources answered, how many failed and why;
4. how many postings were stored, how many are workable, and the top three reasons for
   exclusion;
5. **what you are least sure about** — name it. A location bucket you guessed, a cluster
   that may be too narrow, a source you verified on thin evidence;
6. the two things left to them: delivery and scheduling.

Then tell them the one habit that matters: **read the excluded list for the first week.**
That is where a wrong configuration is visible, and it is the only place a mistake in
this setup can be caught before it costs them something.
