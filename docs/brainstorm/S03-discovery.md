# S03 — Discovery: working out where an employer's postings actually live

**Date:** 2026-10-07
**Phase:** Brainstorming, prompted by the finding in S02 that the residual problem
is discovery rather than extraction.
**Status:** A procedure, verified in parts. Per-employer results are in the private
half.

> Employer-specific results are not in this file. The method is general; the list of
> who is being watched is personal.

## Why this is the real problem

The evaluation in S02 established something counter-intuitive: almost none of the
failures were "this page is prose a parser cannot read". They were *wrong address*.
A wrong slug, a platform guessed from a company name, a tenant identifier that
belongs to a different company, a board that moved.

Two employers were reported on a platform we already parse perfectly, and returned
nothing, because the identifier was wrong. One was reported on a platform where the
company does not exist at all.

A model that reads pages does not help with this. It reads a page you can already
point at. Discovery is the act of finding which page to point at, and it is a
different problem with different tools.

## The procedure, in five steps

Each step is independently checkable, which is the property that matters.

### 1. Start from the employer's real careers URL, and follow redirects

Not a guessed slug — the URL a person would click. The final host after redirects
is already strong evidence: a careers page that lands on a hiring platform's domain
has identified itself.

This alone identified a quarter of the employers tested.

### 2. Fingerprint the returned HTML for platform markers

Even when the careers page stays on the employer's own domain, it usually embeds
the board — an iframe, a script, an API base URL. Searching the HTML for roughly
forty known platform hostnames finds the embed.

Combined with step 1 this identified **9 of 24** employers that had defeated both a
hand-rolled probe and a published library.

More importantly, it **corrected four answers the library got wrong** and found two
employers the library did not know at all. Fingerprinting the real page beats
looking a name up in a manifest, because the page cannot be wrong about itself.

### 3. Extract the identifier from the page, do not guess it

This is the step that was missing from every earlier attempt, and it is where most
of the failures came from. Each platform embeds its own identifier in a recognisable
shape, and a small set of regular expressions pulls it out of the HTML.

Guessing the identifier from the company name is what produced a road-paving
contractor in place of an asset manager, a Brazilian business school in place of a
technology company, and a garden-pergola retailer in place of an Irish IT
consultancy.

Two verifications of this step, both live: one employer's board was found under an
identifier that includes a dot and a top-level domain — unguessable — and returned
**208 postings** where a guessed name had returned zero. A second was found on an
enterprise platform entirely different from the one claimed, returning **127
postings**.

### 4. Call the platform's API with the extracted identifier

Confirm the identifier against the real endpoint and get a count plus sample
postings. An identifier that resolves but returns nothing is a failed discovery,
not a quiet employer.

### 5. A human reads three sample postings before enrolment

Title and location, not a count. Every false positive in this project — across two
completely independent sources — was caught at exactly this step and would have been
invisible without it.

This is not optional ceremony. A pipeline that checks the status code and counts
rows would have silently enrolled five asphalt-laying jobs in Florida as an asset
manager's careers feed, and then reported "nothing new" forever.

## Techniques evaluated and set aside

**schema.org `JobPosting` structured data.** On paper this is the universal answer:
Google for Jobs requires the markup, so employers have a strong reason to publish
title, description, date and location in machine-readable form on every job page.

Tested on 24 careers landing pages: **zero carried it.** That result is misleading
and worth recording correctly — the markup belongs on an *individual job page*, not
on a search or landing page, so the test looked in the wrong place. It remains a
promising path for extracting a posting once its URL is known, and a poor one for
discovering the board. Re-test it properly against detail pages before relying on it.

**Sitemaps.** Many career sites publish one listing every job URL. Not yet tested;
cheap, and the natural pairing with structured data on detail pages.

**Certificate transparency and DNS.** A `careers.` or `jobs.` subdomain whose CNAME
points at a hiring platform is a clean fingerprint that needs no page fetch at all.
Not tested here, worth adding — it costs one DNS lookup.

**Technology-detection services.** They would answer the question directly, but they
are third parties with their own terms, and the page-fingerprint method already
works for the cases where any method works.

## The residual, honestly

After all of the above, a group of employers remains unidentified. Their careers
pages redirect to a marketing site or return a JavaScript shell with no board
reference in the delivered HTML. The board exists; it is loaded by a script after
the page renders.

For those there are exactly three options:

1. **A person opens the browser's network tab once**, finds the request the page
   makes, and writes the endpoint into the watchlist. Minutes per employer, one
   time, and the most reliable outcome.
2. **A headless browser** renders the page and reports what it requested. Automatable,
   and heavy.
3. **Accept the gap** and record the employer as manual-check-only, so its absence is
   visible rather than silent.

Option 1 is almost certainly right for a list this size. The important thing is that
option 3 exists and is honest: an employer we cannot watch must appear in the digest
as "not watched", never as "nothing new".

## The architectural consequence

Discovery and monitoring have **completely different cost profiles**, and conflating
them is what made this look harder than it is.

| | Discovery | Monitoring |
| --- | --- | --- |
| How often | Once per employer, ever | Every day, every employer |
| Acceptable cost | Minutes, a browser, a person | Milliseconds, one request |
| Failure mode | Noticed immediately | Silent |

So the expensive machinery — a browser, and a model if it ever comes to that —
belongs in a **separate, occasional discovery tool**, not in the daily path. The
daily path stays a handful of HTTP requests against identifiers that are already
known to be correct, which is what makes it cheap enough to run forever and reliable
enough to trust.

That separation also means the daily monitor's resource budget and the discovery
tool's budget are two different numbers, and only one of them has to be small.
