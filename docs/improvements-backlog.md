# Improvement backlog

**Date:** 2026-10-07
**Status:** Proposal. Ordered by value per unit of work. Items marked **done** were
implemented in this pass; everything else is a recommendation, not a commitment.

Drawn from re-reading the codebase, a pass against the
[Web Interface Guidelines](https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md),
and from what comparable tools do — [Huntr](https://huntr.co/product/job-tracker) and
[Teal](https://huntr.co/blog/huntr-vs-teal) for the pipeline and gap-analysis
patterns, and the wider
[job-tracker field](https://prentus.com/blog/we-found-the-5-best-job-tracker-tools-on-the-market).

---

## Done in this pass

### A1 — `profile.yaml`, and the workable / excluded split **done**

The reported problem: the postings list showed everything, including roles ruled out
on paper by seniority, location or visa, so it could not be worked from.

The resolution keeps both the usability and the principle: **nothing is deleted.** A
posting excluded by the profile is counted, explained, and one click away, and the
count is always on screen. A filter that drops a posting quietly is the failure the
project exists to prevent; a fold behind a visible number is not.

Result on live data: **4,617 postings → 273 workable.**

### A2 — Three bugs found by running it **done, except the second: that claim is false**

- Two `style` attributes on the triage buttons, so the chosen state never rendered.
- `accept_level` was tested before `reject_level`, which read "Associate Renewals
  Manager" as junior.
- The profile labelled the right *level* as a `cluster`, so `tracks.require_match`
  was satisfied by "Trainee Accountant". The same mistake had just been corrected in
  `rules.yaml` and was reproduced in the profile module.

> **Correction, 2026-11-13 — the second bullet is a false statement, not history.** This
> entry and the changelog entry dated 2026-10-07 ("Running it found three bugs: ...
> `accept_level` tested before `reject_level`") both say the bug was *corrected*. **It was
> not.** What I can verify from the working tree:
>
> - `vedetta/profile.py:267-272` still tests `accept_level` (`:267-269`) before
>   `reject_level` (`:270-272`);
> - `tests/test_profile_level_and_tracks.py:69-75` is a *strict* `xfail` that asserts the
>   opposite order and says in its own comment "Commit c499800 announced this as fixed; the
>   code was never changed".
>
> What the operator verified with `git log -L265,275:vedetta/profile.py` (I could not run
> git in this pass, so this part is theirs, not mine): it returns **a single commit,
> `c499800`, dated 6 October 2026**. That is the commit that *introduced* the function, and
> its own message lists this bug among the three "found and corrected". The code at that
> commit is identical to today's. There was no later fix to point at.
>
> The correction arrives with **P1b**, which reverses the order (reject first); until
> then the bug is open and a title holding words from both lists reads `accept`. When P1b
> lands, the strict `xfail` above must be removed or the suite goes red; that is intended.

### A3 — `vedetta relabel` **done**

Labels are a cached judgement. Without this, editing `rules.yaml` or `profile.yaml`
appeared not to work: stored postings kept their old verdicts and anything just
un-excluded stayed hidden — the silent-failure shape again.

### A4 — Additive schema migrations **done**

`CREATE TABLE IF NOT EXISTS` does nothing to an existing table, so the new columns
needed `ALTER TABLE`. Additive only, by design: a start-up path must not be able to
run a destructive migration over the operator's triage decisions.

### A5 — Interface pass **done**

Card layout instead of a dense table; a visible focus ring everywhere; labels on
every control; human dates ("Today", "13 days ago", "23 Jul 2026") instead of raw ISO
strings; empty states that say what to do next; `aria-live` on flash messages; a
`beforeunload` guard on the configuration editor; a busy state on *Run Now*; skip
link, `color-scheme`, `theme-color`, tabular numerals, `prefers-reduced-motion`,
`content-visibility` on long lists.

---

## Recommended next, in order

### B1 — The sitemap adapter **done**

Six employers enrolled with verified per-source URL patterns: Cisco, Philips,
Mastercard, BlackRock, Yelp, Temporal. Verified live on the smallest of them — first
pass 60 seconds for 66 postings, second pass **0.9 seconds** with zero detail fetches,
zero false closures and a stable content hash.

Two decisions worth remembering:

- **A first pass runs with no detail-page budget.** Capping it would leave the
  remainder to arrive as "new" tomorrow and be mailed as news when it is history.
- **A page with no `JobPosting` markup is skipped, not guessed at** from its HTML. A
  posting with an invented title is worse than a missing one, because it looks right.

Also fixed a latent defect found while writing it: a minimal re-sighting (a URL the
adapter already knows, emitted so the posting is not marked closed) would have written
the hash of an empty payload, making every sitemap posting look edited the moment edit
detection exists. The previous hash is carried forward instead.

### B2 — Workday and SmartRecruiters adapters **done**

Nine employers enrolled: Version 1 (the best structural fit on the candidate list),
ARHS, Palantir, Seven Senders and Ogury on SmartRecruiters; Zendesk, Workday,
Guidewire and Zalando on Workday. Four platforms now cover **36 confirmed sources
across 39 employers**.

Both needed a second request per posting for the advert text, so the known-keys and
detail-budget pattern moved onto the base `Adapter` interface and the platform special
case in `run.py` went away.

**Two Workday traps, both found by running it**, and both producing a quietly partial
result — the worst kind here, since a board returning a third of its postings looks
exactly like a smaller board:

- `total` is reported on the **first page only**; every later page says `0`. Trusting
  it per page stopped the loop after two pages and returned **40 postings of 127**.
  A short read now raises rather than returning quietly.
- The listing hides multi-site postings behind **"2 Locations"** — 42 of 127 on the
  first board tested — which carries no place at all, so a third of the board could not
  be filtered by the facet that matters most. The detail document has the real
  locations and now replaces the count.

**Deliberately deferred:** Sopra Steria (2,068 postings), Devoteam (942) and Salesforce
(1,513). Each means thousands of detail requests against someone else's server on a
first pass. That is a decision to take, not a default to inherit.

### B3 — A "why is this excluded?" view per posting

The exclusion reason is shown, but not which rule produced it or what the matching
text was. When the filter is wrong, that is the information needed to fix it, and
right now it means reading YAML and guessing.

Cheap: the label already records `rule_id` and `produced_by`. Store the matched
substring too.

### B4 — Saved views

The segmented control covers workable / excluded / everything. What is missing is
"Ireland only", "no sponsorship needed", "early career". The URL already carries the
state, so this is a named-bookmark feature rather than new machinery.

### B5 — Digest grouping by employer

Twenty-one employers in one flat list reads poorly. Grouping, with the count per
employer, matches how the decision is actually made.

### B6 — A triage pipeline rather than three flags

Huntr's central idea is a board: saved → applied → interview → offer. The current
`interested / applied / dismissed` has no sense of progress. Worth stealing the
*stages*, not the Kanban: a status with an order, and the date it changed.

This overlaps with the existing application trackers, so it needs care — ADR-0007
keeps those authoritative and read-only. The right scope is probably "up to applied",
after which the tracker takes over.

### B7 — Keyword gap analysis

Teal's distinctive feature: compare a posting against your CV and show which of its
terms you do not use. Useful, and it stops at *showing* rather than judging, so it
stays inside ADR-0006.

Cheap version: extract the posting's capitalised technology terms and diff them
against a list in `profile.yaml`.

---

### B2b — Country-less addresses defeat the location exclusions **done**

Found while verifying the sitemap adapter. schema.org addresses often give a city and
a region with **no country** — "Seattle, Washington" — so a profile whose exclusions
are country names does not match, the location is judged *unknown*, and the posting
stays workable. That is the safe direction by design, but it means a US-only board can
read as workable.

Still open, and now the whole of what is left of B10. Measured on 2026-10-09: 16
postings in the workable list name a US city and no country — "San Francisco",
"San Francisco, California", "NYC, Remote; San Francisco, California".

The adjacent half of this *is* fixed: a profile excluding "United States" used to
catch "Austin, Texas, United States" and miss "Denver, Colorado, USA", because
location rules were matched by raw substring against whatever spelling the reader had
written. Fragments are now judged by their canonical place names too, which took 94
postings out of the workable list. What remains needs a city to imply a country, which
is a different kind of knowledge.

Done on 2026-10-09, together with a region vocabulary the operator asked for, and the
two turned out to answer different halves of the same measurement. Before any of it,
**184 of 416 workable postings had no location verdict at all** - 44%, and a rule
naming countries could reach none of them. The causes, counted rather than guessed:

| cause | count | answered by |
| --- | --- | --- |
| a city and no country — "San Francisco", "Bengaluru", "Toronto" | 95 | city to country |
| no place at all, only a region — "Home based - Worldwide", "APAC" | 63 | the region vocabulary, and nothing else ever |
| nothing usable — "N/A", "LOCATION" | 16 | nothing; correctly unknown |
| a country nobody listed — Greece, Hungary, the UAE | 10 | the blocs |

**Regions and blocs.** `EU`, `EEA`, `Schengen`, `Europe`, `North America`,
`South America`, `Americas`, `Asia`, `Middle East`, `Africa`, `Oceania` can each be
written where a country was. `EU` is twenty-seven countries including the ones the
hand-written list had missed - Greece, Hungary and Bulgaria were all arriving as
*unknown* and counting as workable. The live profile went from thirty-nine excluded
countries to five lines.

For a reader with an EU passport the useful boundary is legal rather than geographic,
which is why the blocs are there: `Europe` includes the United Kingdom and
Switzerland, where this reader needs sponsorship, and those stay named individually
under `conditional`.

**A region in a posting gets a derived verdict**, not a configured one: it is worth
the best verdict among the countries in it, which is the rule already used for a
posting with several locations. A role open to all of EMEA can be done from Milan, so
it reads acceptable; APAC contains nothing acceptable, so it reads excluded. Capped
below `preferred`: a worldwide-remote role is not *in* Dublin, it merely allows it.

**A specific rule beats a region.** With `EU` acceptable and `United Kingdom`
conditional, a London posting reads conditional. Without that ordering the broad rule
erases the visa warning on the narrow one, and the reader applies for a job needing
sponsorship without knowing.

**City to country** runs only where a location names no country, and the label says
what was inferred and from what: "outside where you can work (United States, inferred
from San Francisco)". Thirteen cities are left out of the table by name, with the
reason written beside them - London is in Ontario as well as England, Birmingham in
Alabama, Georgia is a country as well as a state. US state names are in, because they
arrive constantly in schema.org addresses; two-letter state codes that collide with a
country code are not, because CA is Canada before California.

Result: **21 of 415 workable postings now have no location verdict**, and 16 of those
name nothing a human could place either.

The third option below was not taken and is not needed:

- ~~Fall back to the posting URL's host or the employer's country.~~ The weakest of
  the three, and the measurement says it would now reach five postings.

## Worth doing, lower urgency

### C1 — Per-source HTTP conditional requests

`ETag` and `If-Modified-Since` are already in the README as a claim and are not
implemented. An unchanged board should cost a 304, not a full payload. On 21 sources
it is politeness rather than performance, which is reason enough.

### C1b — Redeploy the interface automatically after a rebuild **new**

The interface is a long-running container, so it keeps whatever image it started
with. Build new adapters and its *Run Now* still uses the old ones — which reported
fifteen healthy sources as failing. It now warns about itself, which is the important
half, but the warning is a consolation prize for a step that should not be manual.

The build script should redeploy `vedetta-ui` after a successful image build. Cheap,
and it removes a class of confusing output entirely.

### C2 — Retire employers removed from the watchlist

An employer deleted from the configuration stays in the database and keeps appearing
as unwatched — the test "Example Corp" still does. The digest should distinguish
"configured but unreachable" from "no longer configured".

### C3 — A rule tester in the interface **done, see below**

Paste a posting's text, see which rules fire and why. The rule file is the part most
likely to be wrong and currently the only way to test a change is to run the whole
watch and read the output.

### C4 — Tracker import

ADR-0010 settled how the application trackers reach the server; nothing reads them
yet, so a posting already applied to is still presented as new.

### C5 — Digest in HTML

Plain text is honest and legible, and a short HTML version with the labels as chips
would be easier to scan on a phone. Keep the text part — never send HTML only.

### C6 — A real secret key for the interface

`app.secret_key` falls back to `os.urandom(32)`, so every restart invalidates the
flash-message session. Harmless today, wrong if sessions ever matter. Read it from
the environment file.

### B8 — A board that changes while being read is not a broken board **done**

The Workday adapter refuses a short listing: it keeps the first page's declared total
and raises if fewer postings arrive, because 40 of 127 once came back silently. Run 20
reported `listing stopped at 387 of 388 postings`. One posting had been taken down
between the first page and the last, which is a large board behaving normally, and the
run reported "1 source failing" over it.

Nothing is lost — that source's postings are simply skipped for the run and arrive on
the next one, still unseen and still new, and three of the last six Workday polls were
clean. The cost is to the reader: a failure notice that is usually nothing teaches the
reader to skip failure notices, and then a real one goes past unread.

Done as its own outcome rather than by widening the tolerance. A poll is now `ok`,
`empty`, **`partial`** or `error`, and `partial` has to behave correctly in both
directions at once: the postings are kept and reported, and nothing may be closed on
the strength of an incomplete listing. The second half is the one that matters — a
posting absent from a short listing may still be open, and the shortfall gives no way
to tell which posting it was.

The tolerance is two postings or one percent, whichever is larger, and the fault the
guard was built for (40 of 127) still fails it by a wide margin. The digest calls it
SHORT, with the shortfall spelled out, and deliberately keeps it out of the subject
line: a large board loses a posting mid-walk often enough that putting it there would
teach the reader to skim the subject.

Adapters gained a general `notes` channel for this — something that went oddly without
going wrong, recorded against the poll in its own column rather than in `error`.

### B9 — "asks for more years than you have: 40" **done**

Several Cisco postings carry that label. No posting asks for forty years of
experience; the extraction is reading a number from something else on the page — "40
hours", a 401(k), a percentage. It is a `warn`, so it costs attention rather than
opportunities, but it is wrong often enough to be noise. The extraction needs a
plausible upper bound and a tighter pattern around the number.

### B10 — A source answering in the wrong language **done, and it was worse than this**

Cisco's sitemap is being read from its French-Canadian site, so locations arrive as
`Krakow, Pologne` and `États-Unis d'Amérique`. City names survive it, which is why the
location rules still work on the Polish postings; country names do not, so a posting in
the United States reads as "location unclear - shown rather than guessed away" and
counts as workable. That is the safe direction to fail in, and it fills the digest.
Two parts were planned: pin the source to an English locale, and teach the place
extractor the country names it was meeting. Both done. But the cause turned out to be
ours, and the damage larger than the symptom.

Cisco's `robots.txt` declares two sitemaps, `/ca/fr/sitemap_index.xml` and
`/global/en/sitemap_index.xml`. The adapter reads robots.txt and follows what it finds,
which is right for `sitemap-jobs.xml` beside `sitemap-pages.xml` and wrong for two
translations of one board. So **every Cisco opening was stored twice** — 2,752 rows for
1,376 real jobs — under two URLs, with its location in two languages that
reconciliation had no way to match. The digest reported the same opening twice, in two
languages, as two new jobs.

Three fixes, at three different depths:

- the adapter follows **one translation per sitemap**, chosen by the source's
  `language` (English by default), and says in a note which it skipped and how to
  override. Two sitemaps count as translations only if they end in the same file name
  *and* at least one carries a language code as a path segment, so `/sitemap.xml`
  beside `/news/sitemap.xml` keeps both. `sitemap_include` / `sitemap_exclude` were
  added alongside the existing job-URL filters.
- the Cisco source's `job_url_pattern` is pinned to `/global/en/job/`. The job URL is
  the tightest place to pin it: a French URL cannot be recorded whichever sitemap
  served it, and if Cisco moves the path the source returns nothing and says so.
- `vedetta dedupe` folds the pairs already stored. 863 of them, proven two ways —
  matching normalised places, or a matching job identifier read from the URL with its
  trailing language marker removed. The identifier proof exists because Cisco
  translates the *city* too, and Bruxelles does not normalise to Brussels; without it
  two thirds of the real pairs stood. Nothing is deleted: the duplicate is linked
  through `dup_of` and closed.

The place extractor now reads country names in seven languages and folds accents for
matching while keeping them for display — "Zurich" is matched, "Zürich" is shown. It
also turned out that the *profile* was matching location rules by raw substring, so a
profile excluding "United States" caught "Austin, Texas, United States" and missed
"Denver, Colorado, USA" entirely. Fragments are now judged by their canonical place
names as well.

What is left is in B2b, and it is the same symptom from a different cause: a posting
whose location is "San Francisco, California", with no country at all. 16 of those are
still in the workable list.

### B11 — The location filter as a tree **done**

The flat list held 102 values at three levels in one column ordered by count: `EMEA`
beside `Ireland` beside `Dublin`, 14 shown and the rest reachable only by searching.
Dublin is inside Ireland, so picking both found nothing that Ireland alone had not,
and the numbers read as though they contradicted each other.

Underneath it, the country counts were simply wrong. They counted only the postings
that wrote the country's name, so Germany said 11 while Berlin alone had 17. Rolled
up over everything inside it Germany is 24, and that is the number a reader is asking
for when they click it.

Four designs were mocked up against the real data before choosing one, and the
operator picked the tree. Research (Algolia, UXmatters) favours separate lists per
level over a hierarchical menu, because a menu cannot be searched and cannot hold two
branches at once; the tree here keeps every level independently multi-selectable,
which is the part that matters.

- **the hierarchy is a table**, `place_meta`, rebuilt by every run and every relabel
  beside the places themselves. Two sources for a parent: the table in `regions.py`,
  then co-occurrence in the postings for what it cannot place — London and Dublin are
  deliberately absent from the table, their names being ambiguous, and they are the
  two largest values in the facet. Co-occurrence needs a **majority and at least two
  sightings**: with a plurality it put "Oeiras" under Poland on the strength of one
  posting that listed two places.
- **selecting a country now finds what is inside it.** This was a query change, not a
  display change: without it the rolled-up count would have been a lie.
- **one row per place.** Milan and Milano, Genoa and Genova, Newcastle and Newcastle
  Upon Tyne, Dublin and County Dublin were separate options with a fraction of the
  count each, and a reader who picked one silently missed the rest.
- **regions are their own tier**, labelled "open to a whole region", and they stay
  literal: `EMEA` means a posting advertised for EMEA, not every European posting,
  or the row would mean nothing.
- **no JavaScript, and no `<details>` either.** A link inside a `<summary>` is
  ambiguous across browsers — a click may toggle the disclosure instead of following
  the link. A visually hidden but focusable checkbox with a CSS sibling rule has
  neither problem, and the row stays an ordinary link, which is what keeps every
  filtered view a URL.

Mockups: `claude.ai/artifact/7EnAErCD5a3aSPtYE15mBr` (private to the operator).

### C3 — A rule tester in the interface **done, as a Check button**

Wanted as "a box where you paste a rule and see what it matches". It arrived in a
more useful shape: a **Check** button beside Save on every configuration page, which
validates the box without writing anything and then answers the only question worth
asking first — *what would this do to the postings I already have?*

- **profile**: every open posting judged twice, by the file on disk and by the box.
  A table of verdicts before and after, and then the postings that would **stop being
  workable**, listed individually with the rule that decided each one. That is the
  expensive direction, so it is never summarised into a number.
- **rules**: which rules were added, changed or removed, and how many posting titles
  each new or changed rule matches. A rule reading **0** is the most useful thing the
  check says: a pattern can be perfectly valid and still match nothing on this
  reader's own board, and there was no other way to find that out short of saving and
  relabelling.
- **settings**: a key-level diff.

The reasoning lives in `vedetta/predict.py` and `tools/predict-profile.py` now calls
it, so there is one copy. The command line stays for a candidate file that is not in
the configuration directory yet.

### C7 — A prompt for writing the files with your own AI **new, done**

Writing `profile.yaml` from a blank page is what stops people using a tool like this,
and an assistant that has read the reader's CV can do most of it in a minute. Each of
the three generatable files now carries its own prompt, built by `vedetta/prompts.py`
and shown under the editor, with a plain-text page at
`/config/<name>/prompt.txt` for selecting it whole — a copy button would need script
and this interface has none.

Three things make the difference between a prompt that helps and one that produces a
plausible, wrong file:

1. **It carries the schema**, generated from the example file on disk rather than
   hand-written, so it cannot describe keys the code does not read. A model given the
   exact keys does not invent keys.
2. **It forbids guessing in the first rule**, not the last: collect every gap into one
   list of questions, ask them all at once, wait — and leave a key out rather than
   fill it in. This project's rule about silence, applied to the thing that configures
   it.
3. **It says where the personal half comes from.** A reader opening a fresh chat has
   an assistant that knows nothing about them, so the prompt asks for a CV to be
   attached and treats anything the assistant remembers as a bonus rather than a
   premise.

A second version of each prompt appends the reader's current file, for updating rather
than starting again. It is offered separately and says plainly that it carries their
own configuration into whatever assistant they paste it into — their data and their
call, but a choice they make rather than one made for them.

**No prompt for the watchlist**, deliberately. An assistant asked for a company's
hiring-platform identifier produces one that looks right, and during this project's
design two independent automated sources each returned a different company than the
one asked for. Those identifiers are confirmed by a human looking at real postings and
nothing else; the page says so where the prompt would have been.

### C8 — A key nothing reads is refused **new, done**

`location:` where the code wants `locations:` parsed perfectly, saved cleanly, and
silently stopped every location rule from applying. Nothing in the interface would
ever have said so. It is the likeliest mistake in a file written by hand or by a
language model, and it was invisible until the keys the code actually reads were
written down in `configstore.KNOWN_KEYS`. They are now refused on save, with the
nearest real key suggested.

Writing them down found two more things immediately. `trackers` is documented in the
shipped settings example and read by nothing — C4 — so it is listed as reserved rather
than silently tolerated, where whoever implements C4 will find it. And `extract` had
become a list of patterns while the rules validator still compiled it as a single
string, so **from that day the rules file could not be saved from the interface at
all**: it raised a TypeError rather than reporting anything. No test had ever put a
shipped example file through `validate`. Two now do, one from each side, so the keys
and the examples cannot drift apart.

---

## Found during Phase 2, not fixed (2026-11-13)

Six findings, and a seventh found while closing D1. D1–D5 are not changes in behaviour
made by P1–P4; D6 is a limit of rule B as P4 and P4b wrote it. Each was read in the
code, and where a fact comes from the operator's look at production rather than from
this repository, it says so.

### D1 — `placetree.derive` settles tied votes by the order of a `set` **done 2026-11-13: a tie leaves no parent**

For a place with no table parent, the parent country is the one with the most
co-occurrence votes (`vedetta/placetree.py:61-72`, `:80-86`). The countries of one posting
are collected in a `set` (`:66`) and iterated to add the votes (`:71`), and
`Counter.most_common(1)` (`:81`) returns, among equal counts, the one inserted first. A
`set` of strings iterates in an order that depends on the process's hash seed, so on a tie
the chosen country differs **between processes, on identical input**.

The operator ran it with three different `PYTHONHASHSEED` values: the parent of 10 to 21
places changed between them. Reproduced on the production copy with seeds 1, 2 and 3:
21, 10 and 20 places differ pairwise, 24 in all. `rebuild` runs at the end of every run
and every relabel (`run.py:528`, `:667`), so it happens daily. It can take
postings out of a view filtered by country, because selecting a country matches what is
inside it (B11 above).

**Not an effect of P4**: the code is the B11 code, pre-existing. It deserves its own patch.

**Closed: a tie is not a majority for either country, so the place gets no parent.** The
winner must now have more votes than the runner-up (`placetree.py`, `derive`), and the
place sits at the top of the location filter under its own name instead of under a
country nothing in the data preferred. The other way, the alphabetically first country,
was deterministic too but wrong more often than right. On production there are 27 ties:
21 are between a real country and one produced by D7 below, the other 6 come from
postings listing several countries at once (Hong Kong beside Singapore, a pan-European
list). Alphabetical order would have put Ciudad Mexico under Germany, five US states
under Israel, San Mateo under Canada and Slovaquie under Belgium, permanently and
without a sign that it was a guess.

Measured on the production copy against its stored `place_meta`: 800 places had a parent,
773 now; the 27 that lose it are exactly the tied ones, and none changes to another
country. 235 postings name one of them, 2 of them in the default view. **5 postings
drop out of a view filtered by country, none of them in the default view** (open,
workable), because the others also name the country themselves. Of those 5, four were in
the wrong country (Brussel under Germany, Slovaquie twice under Greece, a Ho Chi Minh
posting under Hong Kong) and one in the right one (San Mateo under the United States).
Three processes with different hash seeds now give an identical tree. The test that
proves it starts a process per seed, since one process cannot change its own.

### D2 — `discovered_by` is never updated and `evidence` is never written

**Closed 2026-11-13: both fields now travel in both branches of the upsert** (`vedetta/config.py`, `sync_watchlist`: `evidence` added to the `INSERT`, `discovered_by` and `evidence` added to `DO UPDATE`). `evidence` was already an admitted watchlist key (`configstore.py:183`), so nothing about the shape of the configuration changed. It appears in no source of the live watchlist yet, so the column stays empty in production until the operator writes it. Test: `test_discovered_by_and_evidence_reach_the_database_on_insert_and_update` (`tests/test_source_params.py`); the older test that pinned the old behaviour ("a photograph, not an endorsement") now expects the new value.

`sync_watchlist` inserts `discovered_by` (`vedetta/config.py:165-166`, `:180`) but leaves it
out of the `DO UPDATE` list (`:169-176`), so an edit in the watchlist never reaches an
existing row; a test pins this and calls it "a photograph, not an endorsement"
(`tests/test_source_params.py:201-204`). `evidence` is a column (`vedetta/db.py:41`) that
appears nowhere in the insert (`config.py:164-185`) at all. The watchlist validator
accepts both keys (`configstore.py:181-182`), so an operator can write them, see them
saved, and believe the database follows. **P3 does not fix either.**

### D3 — Workday and SmartRecruiters, with the detail budget spent, record the posting without its body

When `spent` reaches `detail_budget` the adapter skips the second request and still emits
the posting: Workday builds its text from `[title, location]` only (`workday.py:73`,
`:75-95`); SmartRecruiters from title, location and labels (`smartrecruiters.py:62-79`).
That posting is new, so its thin text is stored (`run.py:473-484`); from then on its key
is known, so later runs emit a re-sighting for it (`workday.py:66-69`,
`smartrecruiters.py:54-57`) and **the body is never read**. Rules scoped to the body, and
the skill line, never see it, and `relabel` keeps judging the stored thin text
(`run.py:626-633`). No note is left on the poll: the two notes in `workday.py` (`:159`,
`:177`) are about the listing, not the budget. The budget is 150 on a source that has been
seen before, none on a first pass (`run.py:131`).

The sitemap adapter does the right thing: past the budget it skips the posting, so it
arrives, whole, on a later run (`sitemap.py:112-116`).

### D4 — `raw` is cut at 200,000 characters *after* serialisation

`json.dumps(item.raw)[:200000]` (`vedetta/run.py:260`) can end in the middle of a value, so
the stored text is no longer JSON. After P4 `relabel` does not read `raw` any more
(`run.py:626`), so this no longer corrupts labels, but the cell stays unreadable;
`backfill-text` counts such Greenhouse rows apart as `unreadable` (`backfill.py:34`,
`:82-84`) and the suite builds one on purpose (`tests/test_relabel.py:449-451`).

The operator checked production: **no `raw` there is today unreadable or truncated.** That
is not visible from this repository.

### D5 — A live `greenhouse` source has the wrong identifier and fails every run

Reported from the operator's production watchlist (the identifier is private
configuration and is not in this repository): the source fails on every run with
`board 'doctolib' not found (404)`. The message is the one the adapter raises for a 404
(`vedetta/adapters/greenhouse.py:42-47`), recorded as an `error` poll
(`run.py:134-138`), so it is a daily failure line in the digest. This is
**configuration, not code**: the identifier is wrong, not the employer quiet.

### D6 — A kept `seniority-threshold` is not compared with the threshold again

Found by the independent review of P4. For a posting without a row in `posting_text`,
`relabel` keeps the labels its body gave (rule B, `vedetta/run.py`, `relabel`, point 3).
`_kept_label` (`run.py`, below `relabel`) carries the old `value` and rewords the label
as the rule is now, but does not compare that value with the current limit. Raise
`max_years_experience` (the `profile` block of `rules.yaml`) and `seniority-threshold`
stays on those postings even where the stored value is now at or under the new limit.
Lowering it does not add the label either: since P4b a rule that reads the body is not
judged without a text at all, and `seniority-threshold` is `field: body`.

Not fixed in P4b, on purpose: one cause per patch. Today the rule is not in
`exclude_if`, so the effect is on the score only, and no posting is hidden by it. It
becomes a hiding bug the day `seniority-threshold` goes into `exclude_if`. The repair
would re-apply `compare` to the kept `value` - for the removing direction only, which is
the one the stored value can decide.

### D7 — A word inside a place name is read as a country code **done 2026-11-13: CA, DE, IL and IN are a country only glued to a city**

Found while closing D1. `places._places_in` looks every word of a fragment up in
`ALIASES` (`vedetta/places.py`, the token loop), and `ALIASES` holds two-letter country
codes (`:81`, `:88`, `:90`). So "Ciudad de Mexico" yields Germany from `de`, "San Mateo,
CA" yields Canada, and a list of US states yields Israel from `IL` and India from `IN`.
These are the false votes behind 21 of D1's 27 ties on production, and they also
put the postings themselves into the Germany, Canada, Israel and India filters. Whether
they reach a location exclusion has **not** been checked. One cause per patch: not
fixed with D1.

**They did reach the verdict, in the direction that lets postings in.** Germany is in
the EU, so a `de` that is a preposition ("Distrito Capital de Bogota, Colombia") or
Delaware ("USA, DE, Remote") made the posting acceptable as "EU, via Germany". The other
three countries are all excluded by the live profile, and best-verdict-wins meant they
could only add an exclusion where nothing else had a verdict.

**Closed.** `ca`, `de`, `il` and `in` are no longer in `ALIASES`
(`vedetta/places.py`). They count as a country only glued to a city by a dash,
"CA-Toronto", "IN-Bengaluru" - the "GB-London" shape, where a leading code cannot be a
state or a word (`COUNTRY_ONLY_WHEN_GLUED`, used in `extract`). Elsewhere `CA` and `IL`
stay as unrecognised places, and `in` and `de` join `NOISE` as the prepositions they
are: without that, "Remote in Canada" became a place called "In Canada" and lost its
country. The short codes that collide with nothing (`us`, `uk`, `gb`, `nl`, ...) are
untouched.

Measured on the production copy (16,933 postings with a location), against the code
before the patch, with the live profile:

- 594 postings lose Canada, Germany, Israel or India from their places. In 512 nothing
  else in the posting said that country (599 invented countries: Canada 266, Germany
  204, Israel 99, India 30). The other 82 were real uses - "Bengaluru, KA, in",
  "Berlin, BE, de", "Toronto, CA" - and every one also names a city the table places,
  so the country is still inferred and the verdict is unchanged. Stated beforehand as
  927 / 202 / 85 / 8; those counted occurrences of the codes, these count postings
  whose places actually change.
- **153 verdicts change, every one from acceptable to excluded; none in the other
  direction.** All 153 were acceptable as "EU, via Germany" and are now judged on the
  country they name: Colombia 77, Chile 24, Panama 18, United States 13, Mexico 7,
  South Korea 4, Australia 4, Brazil 3, Argentina 3. 47 are open; **all 47 were
  already `workable=0`** for another gate, so the default view does not change. 4 had
  `workable=1`, all closed (Cisco: two in Seoul, two in Mexico City). None has a triage
  decision.
- Place tree: 21 places recover a parent (San Mateo and five state codes under the
  United States, Ciudad Mexico under Mexico, Distrito Capital Bogota under Colombia,
  ...), 4 lose one: Republique Coree, which was under Germany, and KA, MH and UP, which
  were under India by co-occurrence with the "in" now gone. Translation pairs found by
  `dedupe`: unchanged.

Not fixed, same family, one cause per patch: `be` is Belgium in "Berlin, BE, de" (the
Land of Berlin, 23 postings) and Italian province codes collide too ("Cuneo, CN, Italy"
is China, "Frosinone, FR, Italy" is France). Measured, none changes a verdict today,
because each posting also names its real country or city. And "Chicago, IL & New York"
now yields a place called "IL New York", because `&` does not split.

---

## Deliberately not doing

| Not doing | Why |
| --- | --- |
| Authentication on the interface | Unnecessary while it is reachable only through the tailnet, which is already authenticated. Needed the moment it binds to the LAN. |
| Automatic application / autofill | What Simplify does. Out of scope by design: the tool notices, the human decides and acts. |
| Scraping aggregators or social networks | ADR-0005, plus a standing rule against automating one particular network. |
| A fit score from a model | ADR-0006. A label can be argued with; a score has to be trusted. |
| Kanban drag-and-drop | The stages are worth stealing (B6); the drag interaction is not, and it would need keyboard alternatives for no real gain. |
