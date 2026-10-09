# Vedetta

[matteomastore.com](https://matteomastore.com) &nbsp;·&nbsp;
[![tests](https://github.com/matteooxx/vedetta/actions/workflows/tests.yml/badge.svg)](https://github.com/matteooxx/vedetta/actions/workflows/tests.yml)

A self-hosted monitor for employers' **own** job boards. Once a day it reads the
careers listings of the employers you choose, works out what is genuinely new,
labels each posting with the facts that decide whether it is worth your time, and
sends you one email.

*Vedetta* is Italian for a lookout: the one who keeps watch and signals, and does
not decide what the signal means.

It watches employers' own boards, not job aggregators. No account anywhere, no API
key, no paid service, nothing published to the internet.

## The one idea worth knowing

**Nothing is ever hidden.** Labels decide the *order* of the digest, never what
appears in it. A posting the ranking dislikes is still there, further down, with the
reasons shown so you can disagree with them.

That is not a stylistic choice. A filter that wrongly drops a posting fails
*silently* — nothing ever tells you it happened — while an irrelevant posting costs
you two seconds of reading. The asymmetry is the whole design.

The same reasoning runs through the rest of it:

- **Every source is polled and every poll is recorded**, including failures and
  empty results. A source that breaks appears in the digest. Silence is never
  allowed to look like "nothing new".
- **An employer with no working route is listed as unwatched**, rather than simply
  being absent.
- **Several routes to the same employer are polled where they exist.** If one goes
  quiet while another still answers, that is a detected fault, not a closed job.
- **A posting that might be a duplicate is shown twice and flagged**, never merged
  away. Merging wrongly hides something; a duplicate costs a glance.

## Enrolment is a human act

A source is only polled once it has a `verified_on` date — meaning a person looked
at real postings from it and confirmed they belong to the employer they asked for.

This is not ceremony. While building this, two completely independent automated
methods each returned a *different company* than the one requested: one returned a
road-paving contractor in Florida as an asset manager, another returned a Brazilian
business school as a technology firm, and a third returned a vendor's demo board
whose single posting was titled "Test Position". All three looked like success —
HTTP 200, valid JSON, plausible row counts.

An employer silently bound to the wrong board produces a permanently empty feed that
is indistinguishable from a quiet employer. So automatic discovery may *propose*; a
human *enrols*.

## Install

Requires Python 3.11 or newer.

```sh
pip install -e .
cp config/profile.example.yaml   config/profile.yaml
cp config/settings.example.yaml  config/settings.yaml
cp config/watchlist.example.yaml config/watchlist.yaml
cp config/rules.example.yaml     config/rules.yaml
cp .env.example .env            # then chmod 600 .env
```

The shipped `*.example.yaml` files are used as a fallback when their real
counterparts are absent, so a fresh clone runs immediately against two real public
job boards.

```sh
vedetta init             # create the database, load the watchlist
vedetta run --stdout     # poll and print instead of sending
vedetta run              # poll and send the digest
vedetta check            # read-only integrity report
vedetta relabel          # re-apply rules and profile to postings already stored
vedetta outbox           # digests queued but not yet delivered
vedetta digest --list    # runs that found postings and reported none
vedetta dedupe           # postings stored twice, reported before anything changes
```

The first run after a watchlist change **seeds silently**: it records what already
exists and sends nothing, so adding an employer never produces an email with several
hundred items in it.

## The interface

The digest is the product; the interface is for the half of the work a daily email
cannot do. It runs as a long-lived process beside the scheduled run, reads the same
database and edits the same configuration files — there is no second store and no
import step.

```sh
pip install -e ".[ui]"
vedetta-web              # 0.0.0.0:5003, or set VEDETTA_WEB_HOST / VEDETTA_WEB_PORT
```

It holds nothing back that the digest shows, and adds four things:

- **Faceted filtering** over location, employer, technology, label, working pattern,
  age and your own triage, multi-select within a facet and intersected across them.
  Each facet counts its options as if it were not filtered itself, so picking Ireland
  never makes Poland read zero. Locations are a two-level tree — a country covers
  everything inside it, so picking one finds the postings that named only a city.
- **A triage ladder** — interested, applied, screening, interview, offer, rejected —
  kept as append-only history, so clearing a decision does not erase that it was made.
- **Insights** that are counted rather than asserted: which employers are actually
  hiring, which postings have been reposted, which have gone stale.
- **The configuration files, editable in the browser**, with comments preserved, a
  concurrent edit detected rather than overwritten, a timestamped backup on every
  write, and a **Check** button that validates without saving and then says what the
  change would do to the postings you already have. Each file also carries a prompt
  you can hand to your own assistant to write it from your CV — it is told to ask
  about anything your CV does not say rather than invent it.

Run it behind whatever you already trust. It has no authentication of its own, and
the author's own deployment binds it to localhost and publishes it over a private
network only.

## Configuration

Code holds mechanism; configuration holds your case. There is nothing about any
particular person or job market in the source.

| File | What it holds |
| --- | --- |
| `config/profile.yaml` | what you can actually take on: where you may legally work, which seniority, which technologies you claim, which kinds of role you are after |
| `config/watchlist.yaml` | which employers, on which platforms, with which identifiers and verification dates |
| `config/rules.yaml` | what counts as a blocker, a warning or a good sign |
| `config/settings.yaml` | database path, digest time and recipients, ranking weights, which discovery techniques are enabled |
| `.env` | credentials only, never committed |

### Rules are data

A rule is a few lines of YAML with a human-readable explanation, and that
explanation is what appears next to the posting in your digest. If you cannot write
a one-line reason a person would accept, the rule is not ready.

```yaml
- id: language-gate
  kind: gate
  severity: blocking
  explain: "requires a language outside the profile"
  when:
    - '(?i)\b(fluent|required)\b[^.]{0,60}\b(french|german)\b'
  unless:
    - '(?i)\b(french|german)\b[^.]{0,50}\b(asset|a plus|nice to have)\b'
```

**The `unless` clause is the heart of it.** A language listed as *required* kills a
posting; the same language listed as *a strong asset* does not. Without that
distinction a language rule is wrong about half the time.

Two other keys matter:

- **`field: title | body | all`** — what the rule reads. The first real run labelled
  a "Senior Backend Engineer" as early-career, because the word "graduate" sits in
  almost every long job description's boilerplate. Level and cluster rules read the
  title; gates read everything.
- **`weight:`** — overrides the severity's default contribution. Use it so that
  being in a target role cluster outweighs merely being at the right level;
  otherwise an "Associate Renewals Manager" ranks alongside a "Cloud Engineer",
  which the first real run did in fact do.

Ranking is a plain sum over the labels. Deliberately arithmetic over visible facts
rather than a learned similarity, so the order can be explained in one line and
argued with.

## Platforms

One adapter serves every employer on a platform, so coverage grows per platform
rather than per employer.

| Status | Platform |
| --- | --- |
| Implemented | Greenhouse, SmartRecruiters, Workday, sitemap + schema.org `JobPosting` |
| Designed, not yet written | Ashby, Lever |

Those four reach 36 confirmed sources across 40 employers on the author's own
watchlist — 21 on Greenhouse, 6 through the sitemap path, 5 on SmartRecruiters, 4 on
Workday.

The sitemap path deserves a note: many careers sites publish `sitemap.xml` listing
every job URL, and their detail pages carry schema.org `JobPosting` markup because
Google for Jobs rewards it. That combination needs no API, no tenant and no
identifier — one request gives the whole set, and detail pages are fetched only for
URLs that are new. It is the only path here that does not care what software the
employer bought.

Its one catch: the pattern separating job pages from content pages **must be
configured per source**. A single global pattern was wrong in both directions within
one hour of testing — too loose it matched `careers-blog`, too strict it lost an
employer whose jobs live at `/careers/<uuid>`.

## What it deliberately does not do

- **Apply to anything.** It does not write CVs, fill forms or submit applications.
- **Judge fit.** It extracts and labels facts. Whether a posting is worth an
  application is a decision it leaves to you, because a label can be argued with and
  a verdict can only be trusted.
- **Scrape aggregators or social networks.** Employers' own boards only.
- **Expose anything.** It is a scheduled batch job that sends mail.

An optional external worker can be pointed at for *extraction and labelling* on
pages that resist deterministic parsing. It is off by default, the program is fully
functional without it, and it is never allowed to produce a verdict.

## Being a good citizen

`robots.txt` is read before a host is crawled. Requests identify themselves. One
poll per source per day, conditional where the platform supports it, and detail
pages fetched only for postings that are actually new — so on a quiet day an
employer costs a single small request.

## Licence

MIT. The adapter designs for several enterprise platforms were informed by reading
[`ats-scrapers`](https://github.com/kalil0321/ats-scrapers) (MIT), which is worth
your attention if you need breadth rather than a personal watchlist.
