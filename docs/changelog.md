# Changelog

Append-only. One line per change, newest at the bottom.

- 2026-10-06 — Project documentation created. Scaffold, ADR-0001 through
  ADR-0004, and the step-A platform envelope. No application code exists yet and
  the app idea has not been disclosed.
- 2026-10-06 — Idea disclosed: a job-search monitor that watches employers' careers
  pages and emails new postings. Brainstorming session S01 opened with ten design
  tensions. Feasibility of the central mechanism probed live against two hiring
  platforms and confirmed. The operator's existing targeting rules, trackers and
  application history read and digested privately — they turn out to be the
  matching rulebook the app needs, already written.
- 2026-10-06 — Four product decisions taken (ADR-0005 to ADR-0008) and step B
  drafted as a press release and FAQ. Scope pruned: seven candidate features
  explicitly deferred or rejected with reasons. Five open items remain before the
  draft becomes the plan, the first of which is the name.
- 2026-10-06 — Named **Vedetta**; project directories renamed from the placeholder.
  Tracker access decided (synced copy, parsed). Platform census run over 78
  employers in two passes: 33 confirmed reachable, and four adapters cover 32 of
  them. Five automatic matches turned out to be vendor demo boards, which settles
  that watchlist entries must be human-confirmed rather than auto-discovered.
  Twenty-six new European employers proposed with verified feeds.
- 2026-10-07 — Researched local AI scraping and prior art (brainstorm S02). Finding:
  an AI scraper would help only with the unstructured minority of sources, and
  `ats-scrapers` (MIT, PyPI) may remove most of that gap deterministically — it
  names first-party adapters for four of the employers the census could not reach.
  changedetection.io assessed as a real alternative for the watching half and no
  help for the triage half. Simone Rizzo'''s models evaluated and found not
  applicable here. No decision taken.
- 2026-10-07 — Evaluated `ats-scrapers` against the 40 unreached employers. It
  resolves 35 and fetches live postings for 16 of them, taking total coverage to 49
  employers across five core adapters. Three of its matches were different companies
  entirely, one of them a road-paving contractor returned as BlackRock. The residual
  gap turns out to be discovery rather than extraction, which weakens rather than
  strengthens the case for a local AI scraper. Recommendation: reference
  implementation and discovery aid, not a runtime dependency.
- 2026-10-07 — Researched and prototyped discovery (brainstorm S03). Fingerprinting an
  employer's real careers page identified 9 of 24 employers that had defeated both our
  own probe and the library, corrected 4 of the library's wrong answers and found 2 it
  did not know. Confirmed live: one employer on a different platform entirely (127
  postings) and one under an unguessable identifier (208 postings, where a guess
  returned zero). Phenom emerged as a five-employer platform. Running total of
  employers confirmed reachable: 51. Resource limits relaxed on the operator's
  instruction, and a hardware-horizon register opened to separate what is deferred by
  hardware from what is deferred by decision.
- 2026-10-07 — Four structural directives from the operator recorded as ADR-0011 to
  ADR-0015, with ADR-0006 amended to permit extraction and labelling by an optional
  external AI worker while still forbidding fit verdicts. Step E completed: 16 domain
  events, an 11-table schema whose plural relations encode the redundancy policy, four
  reconciliation rules in strength order, and three configuration files with a rule
  language whose `unless` clause carries the required-versus-asset distinction. Step D
  scoped to one adapter, one employer, three rules and one email.
- 2026-10-07 — Remaining discovery techniques implemented and run together. Found a
  platform-independent path — sitemap plus schema.org JobPosting on detail pages — that
  needs no API, tenant or identifier, and confirmed it on six more employers including
  one the library had returned as a road-paving contractor. Total reachable: 57. DNS
  CNAME fingerprinting kept but recorded as a low-yield bonus (1 of 21). Two
  self-inflicted false results from a global job-URL filter, wrong in both directions,
  established that the URL pattern is per-source configuration; the schema now carries
  it.
- 2026-10-07 — **Step D deployed.** Dataset `tank/vedetta` with a 14-day daily
  snapshot task, a hardened container, a runner script kept in the dataset rather than
  on the dying boot pool, and a daily cron job at 05:00 UTC. Verified live through
  nine checks, including per-source seeding: 4275 existing postings recorded silently
  from 19 new sources while 0 were reported as news. Running it found three real
  defects a review had missed — cluster rules matching description boilerplate (a
  "Senior Backend Engineer" labelled early-career), a level signal outranking a role
  match (a renewals manager above an SRE), and seeding keyed off whether mail had been
  sent, which would have made a mail outage silent forever. All three fixed, with
  `field` scoping and per-rule `weight` added to the rule language. Mail credentials
  are the only thing standing between this and a working daily digest.
- 2026-10-07 — Web interface deployed as the `vedetta-ui` Custom App, so it appears on
  the server's Apps page; the watch stays a cron job on purpose, because a UI outage
  must not become a silent digest outage. The interface edits the same YAML files a
  person edits over SSH: one source of truth, with comment-preserving writes,
  concurrent-edit detection, validation before writing and a backup on every
  overwrite — 14 new tests, 26 in total. Configuration moved out of the git worktree to
  a directory the interface can write. Reachable over the tailnet only. A run during
  testing found 1 genuinely new posting.
- 2026-10-07 — Added `profile.yaml`: the structured facts about the reader (languages,
  work authorisation, level, geography) that decide whether a posting is workable.
  Resolves the reported problem — a list of thousands of postings mostly ruled out on
  paper — without breaking the never-hide principle: excluded postings are counted,
  explained and one click away, and the count is always on screen. Live result: 4,617
  postings, 273 workable. Also `vedetta relabel` (labels are a cached judgement, so
  editing the rules otherwise appeared not to work), additive schema migrations, and
  an interface pass against the Web Interface Guidelines. Running it found three bugs:
  duplicate `style` attributes hiding the triage state, `accept_level` tested before
  `reject_level`, and the profile labelling the right *level* as a role cluster — which
  let "Trainee Accountant" through as workable. Backlog of 18 further improvements
  written up in `improvements-backlog.md`.
- 2026-10-07 — Faceted multi-select filtering on the postings page. Location is now a
  queryable dimension: `vedetta/places.py` turns a free-text location into normalised
  places (a posting naming several appears under each), with remote and hybrid recorded
  as flags rather than places, and an unrecognised place kept rather than dropped —
  dropping it would make the posting unfilterable, which is a quiet way of making it
  invisible. Facets: location, employer, working pattern, published-within, label and
  triage, each multi-select, each counting its own options against all the *other*
  filters so a group showing zero means something. Values within a facet union; facets
  intersect. Everything is in the query string, so a filtered view is a shareable URL.
  Labels and employer names on each card are clickable filters. Added a *Re-apply
  Rules* button, since editing the profile without it appeared to do nothing.
  28 new tests, 54 in total.
  **Two known extraction defects, seen live and not yet fixed:** "Work From Home"
  leaves a spurious "Home" place (62 postings), and "N/A" splits into "N" and "A"
  (12 each). Both are noise entries in the location facet, not wrong filtering — add
  them to the NOISE set in `places.py`.
- 2026-10-07 — Cleared the two location-facet defects noted the day before, generally
  rather than case by case: a fragment under two characters is never a place, and
  home-based phrasing sets the remote flag instead of becoming a place called "Home".
  Then built the **sitemap + schema.org adapter**, the first path that does not care
  what software an employer bought: the sitemap is the posting list, so "what is new"
  is a set difference over URLs and detail pages are read only for genuinely new ones.
  Verified live — first pass 60 s for 66 postings, second pass **0.9 s** with zero
  detail fetches and zero false closures. Six employers enrolled with per-source URL
  patterns confirmed against their real sitemaps (Cisco, Philips, Mastercard,
  BlackRock, Yelp, Temporal); the remaining five seed on the next scheduled run. 71
  tests. New finding recorded as B2b: schema.org addresses often omit the country, so
  country-name exclusions miss them and the posting stays workable — safe by design,
  but it needs city and state names in the profile.
- 2026-10-07 — Mail recipient set to the operator's job address, with a **fallback
  transport** in the runner: Gmail SMTP needs an app password only he can generate, so
  until one is in place the digest goes out through the server's own already-working
  mail configuration. The fallback disappears the moment an app password is added.
  Then the **SmartRecruiters and Workday adapters**, taking the platform count to four
  and covering 36 confirmed sources across 39 employers; the known-keys and
  detail-budget pattern moved onto the base interface and the platform special case
  went away. Two Workday traps found by running it, both yielding a quietly partial
  board: `total` is reported on the first page only (40 postings returned of 127), and
  multi-site postings hide behind "2 Locations" with no parseable place (42 of 127).
  Both fixed; a short read now raises rather than passing for a small board. Also a
  runner defect: an interrupted run left a named container behind and the next run died
  on the collision — and the first fix for it would have killed a *live* run, because a
  missing lock file is not proof nothing is running. 95 tests.
- 2026-10-07 — The filter panel now scrolls independently: sticky positioning alone
  meant that once the facet list outgrew the viewport, reaching the bottom filters
  required scrolling past every posting. Separately, the dashboard was reporting
  fifteen sources as failing when none of them were: the interface container kept
  running an older image after the new adapters were built, so its *Run Now* really
  had no adapter for sitemap, SmartRecruiters or Workday — and "no adapter for
  platform X" reads exactly like a fault at the employer's end. The error message now
  says the source is fine and the image is stale, and the dashboard checks its own
  build against the configured platforms and warns when it cannot speak to one. A
  stale container was otherwise invisible until someone misread its output.
- 2026-10-07 — Surveyed comparable tools and wrote up `competitive-review.md`. Two
  findings shaped it. JobFunnel, still the top result for open-source job scraping, has
  been archived read-only since December 2025 — this niche has no maintained incumbent,
  and the way it died is an argument for the adapter-per-platform structure. And
  JobOps, the closest cousin, has one idea worth taking: it watches the mailbox for
  recruiter replies, which addresses a gap that is measurable here (more
  than half of the recorded applications sit with no outcome at all). Salary was investigated against the live
  platforms rather than assumed: despite the EU Pay Transparency Directive being due
  7 June 2026, **no** platform supplies it structurally — not Greenhouse, not
  SmartRecruiters, not schema.org on a live page — and it appears in the description
  text for 13 of 40 postings sampled, all US roles. So it is proposed as a rule, not a
  field, with the absence of a range on an EU posting as the more interesting label.
  Seven proposals, five rejections with reasons.
- 2026-10-07 — Five of the six approved review items built and deployed. **Signals**
  (`/insights`) derives who is actually hiring, reposts carrying what you decided last
  time, and postings open past 90 days — all from data already collected, fetching
  nothing. **Saved views** are named filter combinations living in `settings.yaml`,
  written through the editor's validate-and-back-up path with comments preserved.
  **Triage became an ordered ladder** with an append-only history that survives a
  clear, because three flags could not answer what is in flight. **Technology
  comparison** reports which of a posting's terms are on your list and which are not,
  as a new filterable facet — a difference, never a score. Salary extraction was
  declined: the EU directive is not live on any European portal yet. Mailbox watching
  is next and is blocked only on a Gmail app password. 132 tests.
- 2026-10-07 — Mailbox reading built, completing all six approved review items.
  Read-only IMAP (`select(readonly=True)` plus `BODY.PEEK`, so nothing is marked read
  or moved), classification by ordered rules over sender and subject rather than by a
  model, and only the derived observation stored — the table has no column for a
  message body, which is the guarantee rather than a promise. An observation proposes
  a stage and a human accepts or overrides it; nothing moves a stage on its own, and
  it never writes to the hand-written application records. An unmatched message is
  shown as unmatched, because a rejection attributed to the wrong employer is worse
  than one attributed to none, and matching is narrowed to employers actually applied
  to. Blocked only on a Gmail app password — the same secret that lets the digest
  send. 162 tests.
- 2026-10-07 — **Mailbox reading removed** at the operator's request, the same day it
  was built: module, routes, template, table, command, settings and tests. The code
  worked; it is gone because reading a mailbox was not wanted, which is a better reason
  to delete code than most. The gap it addressed remains open and is recorded as such.
  **Digest delivery moved to the machine's own mail configuration**, which already
  sends the server's alerts — so the application now holds **no credential of any
  kind**. The split that makes it work is also better than sending directly: the
  application queues the digest to an outbox and the runner delivers it and records the
  delivery, so an undelivered digest is retried rather than lost, and `vedetta outbox`
  makes the queue inspectable because a fault nobody can see is the kind this project
  is organised against.
  Seeding finished in the meantime: **8,876 postings, 446 workable, 28 of 36 sources
  polled.** The eight unpolled are the SmartRecruiters and Workday sources added after
  that run had already started. It failed only on its final step — on the SMTP
  authentication this change removes the need for.
  And a test file that should have existed already: removing the feature also removed a
  helper the other views used, and the entire interface returned 500 on every page while
  142 tests stayed green. The units were covered; nothing checked they were still wired
  together. `tests/test_web_routes.py` now walks every route, and was verified to fail
  when that helper is taken away again. 162 tests.
- 2026-10-08 — **Run Now reports its progress**, which the operator asked for: clicking
  it used to hold the request open for the whole run — a second on a quiet day, four
  minutes on a busy one — behind a blank page, where a slow run and a dead one looked
  identical. The run now happens in the background and the request redirects to a
  progress page. Two levels of reporting, because one is not enough: which source it is
  on, and how far through that source, since a sitemap source with 300 job pages to read
  otherwise shows nothing for twenty minutes. A heartbeat matters as much as the
  progress — a run whose process dies is still marked running in the database, so the
  page calls it interrupted once the heartbeat goes cold rather than leaving the reader
  to wait and see. Reporting can never fail a run: the reporter swallows its own errors
  and uses its own short-lived connection. 180 tests.
- 2026-10-08 — **A silent loss, found while checking that work.** The notice saying
  "the digest for this run is queued" did not appear on the finished page, and the
  reason was that it was true of nothing: a run started from the interface did the
  polling, the reconciling and the labelling, and then queued no digest at all. The
  postings were recorded correctly — which is what makes the loss permanent, because
  they are no longer new, so the next scheduled run finds nothing to report. Press the
  button, 117 postings arrive, and nobody is ever told about any of them.
  The expensive error is the false negative and a false negative is silent: that
  sentence has been the governing principle of this project since the first brainstorm,
  it is why every poll writes a row and why nothing is ever hidden rather than folded —
  and the defect arrived anyway, by the newest code path, in the one step no second
  source was watching. Redundancy was built across the adapters, where two platforms
  can disagree. It was not built across the two ways a run can start.
  Fixed by giving the two callers one shared function (`digest/dispatch.py`) instead of
  a copy each, so they cannot drift apart again. A run from the interface is also no
  longer marked finished until its digest is queued, because the progress page stops
  refreshing the moment the run ends and a digest queued after that is one the reader
  never sees mentioned.
- 2026-10-08 — **A lost digest can now be rebuilt** (`vedetta digest --run N`,
  `--list`). Everything a digest says is still on disk — `posting.first_seen_run` says
  which run saw a posting first, and the labels, places and skills were all stored — so
  a report can be reassembled and sent late, and late is a great deal better than never.
  `--list` shows which runs found postings and reported none, separating those from
  seeding runs, which report nothing by design and would otherwise bury the real losses.
  A rebuilt digest says so in its subject line and in its first paragraph: it looks
  exactly like a live one, and acting on it as current means applying to postings that
  may have closed weeks ago. Nine runs turn out to be in that state, 483 workable
  postings in total; the two from today (290 and 117 postings, 28 workable) have been
  rebuilt and queued. The rest are from the enrolment days, when sources were being
  added in batches, and are better left as database history than mailed as news.
  Two mistakes worth recording. The rebuilt reader read `blocked_by` as JSON; the
  application writes it as a `"; "`-joined string. It raised on the first real database
  and passed in the test, because the test had written the row itself, in the format the
  reader expected rather than the format the application produces — a test can only
  confirm a format it did not invent. And the suite had been quietly polling GitLab and
  Grafana Labs over the network since the first route test, because the shipped example
  watchlist has two verified sources in it; worse, that made the test run report itself
  as seeding, which hid the very behaviour the new test existed to check. Tests now use
  a configuration whose sources are deliberately unverified. 188 tests.
- 2026-10-09 — **Three fixes from the backlog: B8, B9, B10.** The third turned out to be
  the symptom of something much larger.
  **B8, a board that changes while being read.** A poll now has four outcomes, not
  three: `ok`, `empty`, `partial`, `error`. Workday's guard refuses a listing shorter
  than the total the board declared, because 40 postings of 127 once came back
  silently — and then a run reported `387 of 388`, one posting taken down during the
  minute it takes to walk a board twenty at a time. All 387 were thrown away and the
  digest said "1 source failing", which is how a reader learns to stop reading failure
  notices. `partial` has to behave correctly in two directions at once: the postings
  are kept and reported, **and** nothing may be closed, because a posting absent from a
  short listing may still be open and the shortfall says nothing about which one it
  was. Tolerance is two postings or one percent, whichever is larger; 40 of 127 still
  fails by a wide margin. The digest calls it SHORT and keeps it out of the subject
  line on purpose.
  **B9, "asks for more years than you have: 40".** Cisco was founded in 1984 and writes
  "40 years of innovation" into its own boilerplate. The rule used the largest figure
  it found, so one stray number outranked the real requirement beside it. The pattern
  now insists on the word *experience* in either order — which meant `extract` had to
  accept a list of patterns, since the two orders cannot share a capture group — and
  the gap between number and word allows no digit and no sentence end. Without that
  last part, "a 30 year old company seeking 6 years experience" reached the word from
  the 30, reported 30, and because matches do not overlap it swallowed the 6 that was
  the real requirement. `compare.ignore_above` drops an implausible figure as a second
  line of defence. The highest figure in the live database is now 20, which is a real
  requirement.
  **B10, a source answering in the wrong language — and the duplication underneath
  it.** The symptom was "Krakow, Pologne" and "Austin, Texas, Etats-Unis d'Amerique":
  city names survive a change of language, country names do not, so a posting in Texas
  read as "location unclear" and counted as workable. The cause was ours. Cisco's
  robots.txt declares two sitemaps, one French-Canadian and one English, and the
  adapter follows what robots.txt declares — right for `sitemap-jobs.xml` beside
  `sitemap-pages.xml`, wrong for two translations of one board. **Every Cisco opening
  was stored twice**: 2,752 rows for 1,376 real jobs, under two URLs, with locations in
  two languages that reconciliation had no way to match. The digest had been reporting
  the same opening twice, in two languages, as two new jobs. Yelp was doing it too,
  with three.
  Fixed at three depths. The adapter follows one translation per sitemap, chosen by the
  source's `language`, and says which it skipped; two sitemaps count as translations
  only if they end in the same file name *and* one carries a language code, so
  `/sitemap.xml` beside `/news/sitemap.xml` keeps both. Cisco's `job_url_pattern` is
  pinned to the English path, which is the tightest place to pin it. And
  `vedetta dedupe` folded the 863 pairs already stored, proven two ways — matching
  normalised places, or a matching job identifier with its trailing language marker
  removed. The identifier proof exists because Cisco translates the city as well, and
  Bruxelles does not normalise to Brussels; without it two thirds of the real pairs
  stood. Nothing was deleted: each duplicate is linked through `dup_of` and closed.
  Two more defects fell out of verifying this. The profile was matching location rules
  by raw substring, so a profile excluding "United States" caught "Austin, Texas,
  United States" and missed "Denver, Colorado, USA" entirely — 26 postings in a country
  the reader cannot work in sat in the workable list. Fragments are now judged by their
  canonical place names too. And every excluded posting read "matched none of your
  target role clusters; matched none of your target role clusters", because
  `blocked_by` recomputed a label the labeller had already added.
  One mistake of mine, caught live and worth recording because it was the same class of
  error as the thing being fixed. The first version inferred "the listing is incomplete"
  from *any* adapter note existing. The sitemap adapter then reported, correctly and on
  every run, which of two translated sitemaps it had followed — a complete listing with
  something worth saying — and Cisco was marked `partial` for it. Since `partial`
  blocks closures, **Cisco would never have closed a posting again**, silently, for a
  note that recurs forever. The two are now separate: `note(...)` says something
  happened, `note(..., incomplete=True)` says what may not be concluded from an
  absence.
  Verified live: run 22 from the interface, 34 ok and 2 short, 66 new postings, digest
  queued, no "failing" in the subject line. 254 tests.
- 2026-10-09 — **Regions, legal blocs, and a country from a city** (B2b, closed). The
  operator proposed a continent filter. Measuring first showed it would not fix B2b —
  a posting reading "San Francisco" names no country, so it names no continent either —
  but that it would fix something larger and half invisible. **184 of 416 workable
  postings had no location verdict at all**, 44%, and a rule naming countries could
  reach none of them: 95 named a city and no country, 63 named no place at all but a
  region ("Home based - Worldwide", "Home Based - APAC; Home based - EMEA"), 10 named a
  country nobody had listed, and 16 said "N/A". The 63 were reachable by nothing except
  a region vocabulary — `EMEA` and `APAC` were in the *noise* list and being discarded.
  `EU`, `EEA`, `Schengen`, `Europe`, `North America`, `South America`, `Americas`,
  `Asia`, `Middle East`, `Africa` and `Oceania` can now be written wherever a country
  could. The live profile went from thirty-nine excluded countries to five lines, and
  `EU` brought in Greece, Hungary and Bulgaria, which the hand-written list had missed
  and which were therefore counting as workable by accident. The blocs matter more than
  the continents here: `Europe` includes the United Kingdom and Switzerland, where this
  reader needs sponsorship, so those stay named individually under `conditional`.
  A region *in a posting* gets a **derived** verdict rather than a configured one — the
  best verdict among the countries in it, which is the rule already used for a posting
  with several locations. EMEA contains Italy, so a role open to all of EMEA reads
  acceptable; APAC contains nothing acceptable, so it reads excluded. Capped below
  `preferred`, because a worldwide-remote role is not *in* Dublin, it merely allows it.
  And a specific rule now beats a region: with `EU` acceptable and `United Kingdom`
  conditional, a London posting stays conditional, or the broad rule would silently
  erase the visa warning on the narrow one.
  City-to-country runs only where no country is named and says so in the label —
  "outside where you can work (United States, inferred from San Francisco)". Thirteen
  cities are excluded from the table by name with the reason beside them, because
  London is in Ontario as well as England and Georgia is a country as well as a state.
  **The method mattered more than the feature.** The change was predicted against the
  live database before it was allowed to touch it — every open posting judged under
  both the old and the new profile, with the postings that would move from workable to
  excluded listed individually, because that is the expensive direction. The prediction
  found five defects that the test suite had passed: `EU` matched as a substring inside
  "Eus\u00e9bio, Ceara, Brazil" and "Seoul Teugbyeolsi", making a Brazilian and two
  Korean postings acceptable; "South Africa" and "South Korea" lost their first word to
  the direction-word filter and became "Africa" and "Korea", the first of which had
  just become a region name and was about to start deciding continents; Georgia was
  excluding US postings as Asian; "Türkiye" and "IND.Pune" matched nothing. All five
  are now tests. A prediction run is cheap and it is the only thing that looks at the
  data the change will actually meet.
  Result: 21 of 415 workable postings have no location verdict, and 16 of those name
  nothing a human could place either. The count of workable postings barely moved;
  what changed is which ones — roughly 124 roles in the Americas, Asia and the Gulf out,
  96 in EU countries nobody had listed in. 320 tests.
- 2026-10-09 — **The location filter is a tree, and its counts are now true.** The
  operator noticed EMEA 26 beside Ireland 43 beside Dublin 37 and asked for the filter
  section to be reworked, with options to choose from. Four were mocked up against the
  real data; the tree was chosen, along with three fixes to the values.
  The diagnosis was worse than the symptom. Mixing three levels in one list ordered by
  count was the visible half: Dublin is inside Ireland, so picking both found nothing
  that Ireland alone had not. The invisible half was that the country counts only
  counted postings that wrote the country's name — Germany said 11 while Berlin alone
  had 17, and rolled up it is 24. So selecting a country had to start matching what is
  inside it, which is a change to the query and not to the display: otherwise the
  honest count would have been a lie.
  The hierarchy is a table rebuilt beside the places, not a calculation hidden in a
  query, so a reader can look at it and ask why Dublin sits under Ireland. The parent
  comes from the static table first and from co-occurrence in the postings second —
  London and Dublin are deliberately absent from the table, their names being
  ambiguous, and they are the two largest values in the whole facet. Co-occurrence
  requires a majority and at least two sightings; with a plurality it placed "Oeiras"
  under Poland on the strength of a single posting listing two places.
  Duplicate spellings now share a row: Milan and Milano, Genoa and Genova, Newcastle
  and Newcastle Upon Tyne, Dublin and County Dublin. Dublin still reads 37 rather than
  43, because all six County Dublin postings also name Dublin — the merge adds no
  postings, and saying 43 would have been the same kind of lie in the other direction.
  Built without JavaScript and without `<details>`: a link inside a `<summary>` is
  ambiguous across browsers, where a click may toggle the disclosure instead of
  following the link. A visually hidden but focusable checkbox with a CSS sibling rule
  has neither problem.
  One defect found while looking at the values, and it was not cosmetic:
  `New South Wales, Australia` was coming out as `['New', 'United Kingdom',
  'Australia']` — "South" discarded as a direction word and "Wales" resolved to a
  country, so **a Sydney posting read as British**, which for a reader needing a visa
  is the difference between two answers. The same family broke `South Carolina` into
  "Carolina" and `West Virginia` into "Virginia". A multi-word place name is now
  checked whole before anything is split. 351 tests.
- 2026-10-09 — **The configuration pages now help you write the files**, which is what
  stops people using a tool like this: the hard part was never the YAML, it is knowing
  what the keys mean. Each of the three generatable files carries a prompt to hand to
  the reader's own assistant, built from the example file on disk so it cannot describe
  keys the code does not read, with a plain-text page for selecting it whole — a copy
  button would need script and this interface has none.
  Three things decide whether such a prompt helps or produces a confident, wrong file.
  It carries the exact schema, so the assistant does not invent key names. It forbids
  guessing in the FIRST rule rather than the last — collect every gap into one list of
  questions, ask them all at once, wait, and leave a key out rather than fill it in,
  which is this project's rule about silence applied to the thing that configures it.
  And it says where the personal half comes from: a reader opening a fresh chat has an
  assistant that knows nothing about them, so it asks for a CV to be attached and
  treats memory as a bonus rather than a premise. A second version of each prompt
  appends the reader's current file for updating rather than starting again, offered
  separately because it carries their own configuration into whatever assistant they
  paste it into.
  **No prompt for the watchlist**, and the page says why where the prompt would have
  been. An assistant asked for a company's hiring-platform identifier produces one that
  looks right, and two independent automated sources each returned a different company
  than the one asked for during this project's design.
  **A Check button beside Save** (C3, in a better shape than it was asked for): it
  validates the box, writes nothing, and answers what the file would do to the postings
  already here. For a profile, every open posting judged twice and then the ones that
  would stop being workable listed individually with the rule that decided each —
  tested live against a deliberately narrow candidate, which reported 2,248 postings
  would be folded away, before anything was written. For rules, how many titles each
  new rule matches, and a rule reading 0 is the most useful line in the report: a
  pattern can be valid and still match nothing on this board. The reasoning lives in
  `vedetta/predict.py`, and `tools/predict-profile.py` now calls it rather than keeping
  its own copy.
  **And a key nothing reads is refused** (C8). `location:` where the code wants
  `locations:` parsed, saved and silently stopped every location rule from applying,
  and nothing would ever have said so. Writing the real keys down found two more faults
  the same afternoon: `trackers` is documented in the settings example and read by
  nothing, so it is now listed as reserved where whoever implements C4 will find it;
  and `extract` had become a list of patterns while the rules validator still compiled
  it as a single string, so **the rules file had not been saveable from the interface
  since that change** — it raised a TypeError instead of reporting anything. No test
  had put a shipped example file through `validate`. Two do now, one from each
  direction. 390 tests.
- 2026-10-09 — **Published**, at `github.com/matteooxx/vedetta`, MIT, 23 commits, CI
  green. ADR-0013 said from the first week that this had to be generic and publishable
  from the first line rather than retrofitted, and this is the pass that found out
  whether that was true. It mostly was: the mechanism was already in code and the case
  already in configuration, so nothing had to be torn apart. What the audit found was
  four smaller things, and the shape of them is worth keeping.
  Two were in the history rather than the working tree, which is the part that is easy
  to forget: a push publishes every commit, so a clean checkout proves nothing. A
  timestamped backup of a real settings file had been swept in before `.gitignore`
  covered that shape — no credential in it, every secret field empty as designed, but
  somebody's working file all the same. And the runner named one absolute path. Both
  were rewritten out of all 23 commits, which costs nothing before the first clone and
  a great deal after it.
  The path turned out to be a bug as well as a disclosure. `run-vedetta.sh` now derives
  its own root, with `VEDETTA_ROOT` to override, so the script a stranger clones works
  where it stands instead of only on the machine it was written for. Every privacy fix
  on this project has been like that: the thing that made it specific to one person was
  also the thing that made it worse.
  The fourth was not on any checklist. The documents quoted the author's own
  job-search statistics — how many applications, how many unanswered — as evidence that
  the problem was real. The evidence survives as a shape rather than a figure. A
  prospective employer reading this repository has no business learning how many times
  its author has been ignored.
  Also added: `LICENSE`, which `pyproject.toml` had claimed since the first commit
  without a file to back it up, and a test workflow against Python 3.11 and 3.12 — the
  oldest version the project claims to support and the one the container actually runs,
  because a claim in `pyproject.toml` that nothing checks is a guess. The 27 design
  documents moved into the repository: the code shows what was built, the records show
  why, including what was tried and rejected.
- 2026-10-09 (later) — **The documents audited against the project, after one line of
  the README turned out to be false.** The operator asked whether the platforms table
  was true. It was not: it said one adapter was implemented when four are — Greenhouse,
  SmartRecruiters, Workday and the sitemap + schema.org path, together reaching 36
  confirmed sources — and listed as unwritten the very adapter the same README spends a
  paragraph praising. Checking it properly turned up three more in the README and five
  in `docs/`, so the honest answer to "is this true?" was "no, and neither is a good
  deal else".
  In the README: the web interface was **not mentioned at all** — zero occurrences of
  "web", "interface" or "triage" — so the front page described a command-line tool and
  a reader would never learn about the filtering, the triage ladder, the insights or
  the configuration editor. Three of seven CLI commands were listed. And
  `profile.yaml`, the file that decides what counts as workable, appeared in neither
  the install steps nor the configuration table: the single most important file for a
  new user was absent from its own documentation.
  In `docs/`: the index still opened with "the app has not been named yet, and its
  purpose has not been disclosed yet" — the first thing a reader sees, in a repository
  published under that name. It pointed at a private directory on a PC that no longer
  holds it, called itself "a candidate for public publication", and left four of the
  eight documents out of its own read order. `data-model.md` described eleven tables
  where sixteen exist, including one (`source_candidate`) that was never built; it is
  now marked as the step-E design it is, with `vedetta/db.py` named as the only
  authority and a note on what diverged. Its sixteen domain events, checked one by one,
  needed no revision at all — which is the part worth noticing.
  `ADR-0002` was still marked **Accepted** while its decision had been reversed in
  full, and is now Superseded. **ADR-0017** records the publication itself: public
  under MIT with the documents included, the private half on the server, pushed from
  the server by a deploy key rather than a token, nothing published automatically, and
  every push audited over the whole history rather than the working tree.
  One finding was a gap in the publication audit rather than in the documents.
  `ADR-0002` carried two absolute Windows paths including the PC's account name, and
  the audit had swept for `/mnt/` paths on the server and never for paths on the
  author's own machine. Corrected forward, not by rewriting an already-pushed branch:
  the exposure is an account name inferable from the public one, which does not justify
  relaxing branch protection to force-push. The pattern list now covers both shapes.
  The lesson is the one the server handbook already states and this pass proves twice
  over: **a document is only as good as its last verification.** Every figure above was
  read off the live system — the adapter registry, the source counts per platform, the
  table list, the event count — and the ones that had been written from memory were the
  ones that were wrong.
