# Working backwards — press release and FAQ

**Date:** 2026-10-06
**Phase:** Step B of the design method (ADR-0004).
**Status:** Draft 1. Written as if the first release had already shipped, which is
the point of the exercise: anything that cannot be said plainly here does not
belong in the first release.

The app has no name yet. It is called "the watcher" throughout; naming is an open
item.

---

## Press release

### The watcher tells you what opened today, and nothing else asks for your attention

**A daily email that covers every employer you care about, so that noticing stops
being your job.**

The watcher is a small application running on a private home server. Once a day it
reads the careers listings of a set of employers chosen by its single user, works
out what is genuinely new since yesterday, labels each posting with the facts that
decide whether it is worth pursuing, and sends one email. Nothing is published to
the internet; nothing leaves the user's own machines.

**The problem it solves is narrower than it first appears.** Its user is not short
of ways to find jobs, and not short of a way to apply for them: he has a tracker of
dozens of applications across dozens of employers with their outcomes, a written
rulebook of his
own eligibility constraints built up over months, and a working assistant-driven
process that turns a posting into a fit assessment, a targeted CV and a cover
letter. What he does not have is a reliable way of **noticing**. Checking 51 careers
pages by hand is not a task anyone does every day for long, and the day it gets
skipped is the day something is missed — silently, with nothing to indicate it
happened. That has already occurred once, in September 2026, when a filtered search
of a single careers portal passed over an eligible vacancy that a second,
unfiltered pass found an hour later.

**The watcher is built around that specific failure.** It never hides a posting. It
reads every listing from every watched employer, and the labels it attaches —
"asks for 5+ years", "French required", "sponsorship not stated", "talent pool, not
an opening" — decide what appears at the top of the email, never what appears in it
at all. A posting the watcher ranks badly is still three lines further down, where
its user can disagree with the machine in a second. The asymmetry is deliberate: an
irrelevant posting costs two seconds of reading, while a missed posting costs
everything and announces nothing.

"I had the whole process working except the part where I notice," its user said.
"The CVs, the cover letters, the record of what I sent and what came back — that is
all in place and it is good. What I could not do was check fifty-one careers pages
every morning, and the one time a filter decided something for me, it decided
wrong. I wanted something that looks everywhere and tells me what it saw, not
something that thinks on my behalf."

The watcher runs entirely on hardware its user already owns, costs nothing to
operate, holds no account with any third party, and needs no credential beyond the
mailbox it sends from.

---

## FAQ

### What exactly arrives in the email?

Everything new from watched employers since the previous run, ordered by how well
it matches, with the reason for its position shown as labels. Below that, anything
that closed. The mail arrives even on a day when nothing is new, so that a missing
email always means a fault rather than a quiet day.

### How does it know what is new?

The hiring platforms most employers rent supply a stable identifier and a
publication date for each posting. "New" is therefore a set difference on a primary
key, not a guess based on comparing text. When an employer's platform offers no
such identifier, a hash of the posting's normalised content stands in, which is
weaker and is treated as such.

The first run against any new employer is silent: it records what exists and sends
nothing, so adding an employer never produces an email with two hundred items in
it.

### Does it decide whether a job is a good fit?

No, and this is deliberate. It extracts facts — years demanded, languages required
as opposed to preferred, statements about sponsorship, whether the posting is a
continuous pipeline rather than a real opening — and it shows them. The judgement
about whether a posting is worth an application stays with its user and the
assistant he already uses for that, which does it well and does it with him
present. See ADR-0006.

### Why not have a model read the postings and score them properly?

Because it would be a second opinion that is weaker than the one already available,
running unsupervised, and its user would then have to decide how much to trust it.
A deterministic label can be argued with; a model's verdict has to be taken on
faith. The one documented failure in this workflow came from trusting a filter.

### Does it apply to jobs?

No. It does not write CVs, does not fill forms, and does not submit anything. The
boundary is firm: the watcher notices, the existing process decides and acts.

### Does it update the application trackers?

It reads them so that a job already applied to is not presented as new. It never
writes to them. Those files are hand-maintained, carry prose that a program would
flatten, and are deliberately split into two channels — a split no schema invented
here would preserve faithfully. See ADR-0007.

### Which employers does it watch?

Whichever ones its user lists. The initial list comes from the employers already
in his trackers, because that list already encodes months of judgement about who is
worth the effort.

### Does it scrape job boards?

No. It reads employers' own careers listings. Aggregators duplicate those listings,
add noise, and defend aggressively against automated access. One large professional
network is excluded outright by a standing rule, because automating it risks the
account and the account is worth more than the coverage.

### Is it polite to the sites it reads?

It identifies itself honestly in its requests, reads each source once a day rather
than continuously, and uses conditional requests so that an unchanged listing costs
the server almost nothing. At one request per employer per day the load is
negligible — which is a reason to be unhurried about it, not a reason to skip the
question of whether a given endpoint is meant to be read this way.

### What happens when a source breaks?

It is reported, in the same email. An employer whose platform has no adapter yet,
and a source that returned an error, are both visible states. Silence is never
allowed to look like "nothing new" — that would recreate the exact failure the
whole design is organised around.

### What does it cost to run?

Nothing beyond electricity already being spent. It runs on an existing home server
with substantial spare capacity, needs no browser, no paid API and no subscription.

### Is any of this exposed to the internet?

No. It is reachable only over the user's private network. This is a standing rule
of the server it runs on, not a choice made here.

### What happens to the data if the server dies?

The postings themselves are disposable — they can be re-fetched. What matters is
the accumulated record of what was seen when, and the user's own triage decisions
about each posting. That is why an export the user can pull down and verify is part
of the first release rather than a later addition: the server it runs on has local
snapshots and **no off-site backup at all**.

---

## What the first release deliberately does not include

Each of these was discussed and set aside with a reason. They are recorded so they
are not re-proposed as new ideas.

| Not building | Why not |
| --- | --- |
| A web interface | A configuration file and an email prove the whole loop end to end. The interface is worth building once there is something to triage, and it is the natural second release. |
| Immediate alerts for priority employers | A small addition once the digest exists, but it adds a category to maintain before there is evidence that a day of delay has ever cost anything. |
| Public-institution portals | Session-based web applications, the hardest sources in the set. Putting the hardest work first risks the easy, already-proven majority never shipping. A later adapter. |
| Follow-up reminders on silent applications | 50 applications sit without a recorded outcome and the elapsed time is already in the tracker, so this is attractive and cheap. It is also a different product. Later. |
| Re-post detection | A company reopening a role its user was rejected for is a real signal. Still later. |
| Writing to the trackers | ADR-0007. Not "later" — decided against. |
| Any model call inside the app | ADR-0006. Not "later" — decided against, with a stated condition under which it would be revisited. |

---

## Open items before this draft can become the plan

1. **The name.** Candidates: *Rassegna* (a daily press review, which is what the
   email is), *Vedetta* (lookout), *Watchpost*, *Bollettino*. Renaming the project
   directory is a recorded action, so it is cheap but not free.
2. **The hour the digest is sent.**
3. **How the app reads the trackers**, given they live on the user's PC and the app
   runs on the server: a pushed copy, a read-only share, or an explicit export step.
4. **Which platform adapters come first**, which depends on which platforms the 51
   employers actually use — currently unverified for all but two.
5. **What the watchlist entry looks like**: employer, platform, platform identifier,
   channel, and whether anything else is genuinely needed.
