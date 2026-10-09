# S01 — The problem, and the tensions worth deciding

**Date:** 2026-10-06
**Phase:** Brainstorming, ahead of step B (working backwards).
**Status:** Open. Nothing here is decided; the recommendations are arguments, not
outcomes.

> Personal material — employer names, application history, the operator's own
> eligibility constraints — is deliberately not in this file. It is summarised in
> the private half as `02-targeting-rules-digest.md`. This file stays at the level
> of the design problem so it can survive being read by someone else.

## The idea as stated

An application running on the operator's home server that watches the careers
pages of employers he cares about, and emails him when something new appears.

## What makes this a more interesting problem than it looks

The obvious reading — "poll some pages, diff them, send mail" — is wrong in one
specific way, and the evidence is in the operator's own records.

He is not starting from zero. There is a hand-maintained body of work: a tracker
of dozens of applications across dozens of employers with their outcomes, a
second tracker kept
deliberately separate for public-institution channels, a canonical rules file of
roughly 51 KB that encodes every standing eligibility decision, and a distilled
keyword strategy by role cluster. There is also an established workflow, driven by
an AI assistant, that takes a posting and produces a fit assessment, a targeted
CV, a cover letter and a tracker entry.

So the gap is **not** "he cannot find jobs" and **not** "he cannot apply". The gap
is the watch: noticing, reliably and without having to remember, that something
new has appeared at one of 51 employers.

That reframing changes what the app is. It is a **sensor feeding an existing
process**, not a replacement for it. Everything below follows from that.

### The failure mode has a date on it

On a specific day in September 2026, a *filtered* scan of one careers portal
missed an eligible vacancy with no gates. A second *unfiltered* pass of the same
portal found it, and an application went out the same day.

This is the governing constraint of the whole design. **The expensive error is the
false negative, and filtering is what produces false negatives.** A missed posting
is silent — nothing ever tells you it happened. An irrelevant posting, by contrast,
costs two seconds of reading.

That asymmetry should be visible in the architecture, not just in a comment.

## The tensions

### T1 — One adapter per hiring platform, or one scraper per company?

51 employers is a lot of scrapers to write, and a lot of scrapers to repair every
time someone restyles a page.

But most employers do not run their own careers software — they rent it. A probe
run during this session confirmed that two platforms already in the operator's
history answer unauthenticated HTTP GETs with clean JSON: stable posting IDs,
titles, locations, publication dates. 45 and 72 live postings respectively, no
authentication, no browser.

**Recommendation: adapters per platform.** One adapter reaches every employer
hosted on that platform, so coverage grows per platform rather than per employer.
A generic HTML adapter stays as the fallback of last resort.

*The honest caveat:* this is proven for two platforms. The large direct employers
in the operator's history run their own portals, and each has to be checked
individually. Several of the public-institution portals are session-based web
applications and are probably the hardest sources in the set. **Coverage will be
uneven, and the design should treat an unreachable source as a visible, reported
condition rather than as silence.**

### T2 — Filter, or rank?

The tempting design sends only good matches. The September incident says that is
precisely the design that fails.

**Recommendation: never suppress.** Everything from a watched employer reaches the
digest. Scoring decides *order and prominence*, never visibility. Gates are shown
as labels on a posting — "asks for 5+ years", "French required", "sponsorship not
stated" — so the reason for a low rank is legible and can be disagreed with.

The cost is a longer email. The benefit is that the app can be wrong about a
posting without that posting disappearing.

### T3 — What counts as "new"?

With stable platform IDs this is mostly a set difference, which is the reliable
case. Three details decide whether it feels right:

- **First run must be silent.** Seeding a watchlist should not produce an email
  with several hundred postings in it. Seed, then notify from the next run.
- **Re-posts and edits.** A changed title on the same ID is an edit; the same role
  reappearing under a new ID is a re-post, and a re-post is interesting.
- **Disappearance is also information.** A posting closing is worth recording, and
  arguably worth showing, though probably not worth an email.

### T4 — Is this posting actually open?

Some postings are continuous talent pipelines that state outright there is no
current opening. The operator already distinguishes these by hand and records
which is which, because conflating them inflates the sense of progress.

**Recommendation:** detect and label, never hide. A pipeline posting is still worth
submitting to; it just is not an opening.

### T5 — How are the gates evaluated?

The gates are textual and the nuance is load-bearing: a language listed as
*required* kills a posting, the same language listed as a *strong asset* does not.
A seniority threshold is usually a number, which is easy. A hidden enrolment
requirement is a sentence, which is not.

Two layers are possible:

- **Deterministic rules** — regular expressions and structured fields. Cheap,
  predictable, offline, auditable. Catches the numeric and keyword gates well and
  the nuanced ones badly.
- **A language-model pass** — catches nuance, costs money, needs an outbound
  credential, and introduces a dependency that can fail or change its mind.

**Recommendation: deterministic first, and consider not building the second layer
at all.** There is already a capable assistant in this workflow — the one that
writes the CVs. The app can prepare the material and let the human-plus-assistant
step do the judging, rather than reimplementing judgement in the app and then
having to trust it. A model call inside the app is a tempting default; here it
might be redundant.

### T6 — Where does this app stop?

The existing workflow already does the hard, careful part: fit assessment, targeted
CV, cover letter, tracker entry. It is good, it is tuned, and it is honest about
declaring gaps.

**Recommendation for the seam:** the app finds, de-duplicates, ranks, labels,
notifies, and remembers what the operator decided about each posting. It does
**not** write a CV, and it does **not** write into the existing trackers. It may
*read* them, one-way, so that something already applied to is not resurfaced as
new.

The argument for one-way: those trackers are hand-curated, carry nuance in prose,
and are the operator's record of his own judgement. A program writing into them
would degrade them, and the separation between the two trackers is itself a
deliberate decision that a program would be likely to flatten.

### T7 — Instant alerts or a daily digest?

Instant feels responsive and is how this kind of tool usually gets built. It is
also how it gets muted, and a muted notifier is a notifier that has failed.

**Recommendation: one digest per day at a fixed hour**, with the option of
immediate mail for a small, explicitly marked priority set. Job postings are not
perishable on an hourly scale; attention is.

### T8 — A web interface, or just a configuration file?

A watchlist of 51 employers edited as a file over SSH is friction, and friction
decides whether a tool is still in use in three months.

**Recommendation:** a small private web interface eventually — manage the
watchlist, triage the inbox, mark interested / dismissed / applied. But **not in
the first slice.** The first deployment should prove the loop end to end with a
configuration file and an email, because that is what makes the platform risks
surface early.

### T9 — What must not be touched

One source is excluded by a standing rule and should be written into the design
rather than rediscovered: automating one particular professional network risks the
account, and the account matters more than the coverage. Other large job boards
are aggressive about blocking automated access and are not worth the fight,
especially as the assistant already has separate connectors for some of them.

More generally: identify the client honestly, respect the published crawl rules,
poll daily rather than continuously, and use conditional requests. At one request
per employer per day the volume is negligible — but "negligible" is a reason to be
unhurried, not a reason to skip the question of whether a given endpoint is meant
to be polled at all.

### T10 — Does it fit the platform envelope?

Comfortably, if T1 holds. JSON over HTTPS needs no headless browser, which is what
would otherwise have blown the memory ceiling. 51 employers polled once a day is
an insignificant amount of work for the hardware.

The one envelope item that does apply with full force: **the server has no
off-site backup.** The valuable data here is not the postings — those can be
re-fetched. It is the operator's accumulated triage decisions and the record of
what was seen when. That needs an export path designed in, per the envelope.

## Questions that need the operator, not more thinking

1. Does the watchlist seed from the employers already in the trackers, or is it
   curated fresh?
2. Watched-employer careers pages only, or also aggregators and job boards?
3. Should public-institution channels be in the first release, given they are the
   hardest sources, or deliberately deferred?
4. Is the one-way boundary with the existing trackers right, or should the app
   eventually write into them?
5. Daily digest hour, and is there a priority set that justifies immediate mail?
6. Does the app ever call a language model, or does it stop at preparing material?
