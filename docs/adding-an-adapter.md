# Adding an adapter

**Date:** 2026-11-13. **Question this answers:** what do I do, exactly, to add a
hiring platform?

Every behaviour below carries the `file:line` where it can be read, as of the end of
Phase 2 (533 tests passing, 6 xfailed). If a line number has drifted, the behaviour is
what to check, not the number.

An adapter speaks to one *platform*, not to one employer (`vedetta/adapters/base.py:3-4`).
It returns what the platform said plus a stable key, and never decides whether a posting
is interesting (`base.py:6-7`).

## 1. The file and the class

Create `vedetta/adapters/<platform>.py`. Copy the nearest existing one:
`greenhouse.py` when one request returns everything, `smartrecruiters.py` when each
posting needs a second request for its text.

- Subclass `Adapter` (`base.py:90`) and set `platform` to the exact string the watchlist
  uses (`greenhouse.py:21-22`). The runner looks the adapter up by that string
  (`run.py:100`, `config.py:160`).
- The class is built with **no arguments** (`run.py:127`).
- `fetch` has this signature (`base.py:203-206`), and the runner passes all four
  (`run.py:128-133`):

  ```python
  def fetch(self, source: dict, known_keys: set[str] | None = None,
            detail_budget: int | None = None, progress=None) -> list[RawPosting]:
  ```

  `source` carries `identifier` and `endpoint` (`greenhouse.py:30-31`) plus the declared
  parameters (section 3).
- Return one `RawPosting` per opening (`base.py:60-71`): a stable `platform_key`, `title`,
  `location`, `url`, `published_at`, `text`, `raw`, `resighting`.
- To fail, raise `AdapterError(message, http_status=...)` (`base.py:82-87`,
  `greenhouse.py:42-47`). It is recorded as an `error` poll (`run.py:134-138`); any other
  exception is recorded too (`run.py:139-144`).
- To say something that went oddly without going wrong, `self.note(...)`
  (`base.py:122-131`). `incomplete=True` additionally says the listing may be short, and
  stops anything being closed for that employer (`run.py:160-161`, `run.py:371-380`).

## 2. The registry line: the only place

In `vedetta/adapters/__init__.py` add one import and one entry
(`__init__.py:12-15`, `17-22`):

```python
from .myplatform import MyPlatformAdapter
...
    MyPlatformAdapter.platform: MyPlatformAdapter,
```

Nothing else is edited. The docstring says it (`__init__.py:3-4`) and the readers confirm
it: the runner (`run.py:100`), the watchlist validator (`configstore.py:124-126`,
`configstore.py:424`) and the watchlist sync (`config.py:121`, `config.py:160`) all read
that one dictionary. **Never copy or rebuild it** (`__init__.py:6-10`); a test fails if
`run.ADAPTERS` or `configstore.ADAPTERS` stops being the same object
(`tests/test_adapter_contract.py:44-51`).

## 3. `params`: the extra source keys you read

If `fetch` reads a key from `source` beyond the generic ones (`platform`, `identifier`,
`endpoint`, the verification fields), declare it:
`params = frozenset({"my_key"})` (`base.py:92-96`; example `sitemap.py:54-55`).

If you do not declare it:

- the watchlist refuses the key on save. A key no adapter declares is an unknown key
  (`configstore.py:203-224`); a key some *other* adapter declares is refused on your
  platform by name (`configstore.py:410-437`, test `tests/test_configstore.py:102-111`);
- and it would not reach `fetch` anyway: sync stores only the declared parameters
  (`config.py:162-163`), as JSON in `source.params` (`db.py:46-49`), and `source_dict`
  spreads them back (`db.py:285-303`). `job_url_pattern` and `job_url_exclude` are the two
  declared parameters that have a column of their own (`config.py:124-126`).

Declared parameters are also covered by `tests/test_source_params.py:64-76` and `:209-210`,
which read `ADAPTERS`, so yours is followed through insert, update and removal without
editing that file.

## 4. `resighting`: when to set it

Only for a key that is in `known_keys`, when you are *not* re-reading its page: emit
`RawPosting(platform_key=key, title="", url=url, resighting=True)`
(`base.py:213-218`; `smartrecruiters.py:54-57`, `sitemap.py:106-111`,
`workday.py:66-69`). The runner then keeps the posting open, creates nothing, and carries
the previous content hash forward (`run.py:203-212`, `run.py:265-277`).

If you do not set it:

- an item with an empty title is **not** taken for a re-sighting. It is dropped, with a
  note on the poll (`run.py:222-226`, `run.py:546-565`);
- a posting you simply do not emit is not seen this run, and `close_missing` closes
  postings whose `last_seen_run` is older, for an employer whose polls were healthy
  (`run.py:384-388`). That is why the flag exists;
- `resighting=True` on a key with no record is dropped too, with a different note that
  calls it an adapter fault (`run.py:216-221`, `run.py:562-564`).

Both notes land on `source_poll.note` and in the report (`run.py:510-521`), and the digest
prints them (`digest/render.py:150-151`, `159-161`).

## 5. `text`: leaving it empty is a choice

`text` is what the body rules and the skill matcher read (`base.py:226-227`). Leave it
empty and **they read the title instead**: `run.py:478-479` substitutes the title and
labels the stored row `title-fallback`; the engine's `body` is then that title
(`labels/engine.py:92-95`). Rules scoped `field: title` are unaffected.

That is acceptable when the platform really has no advert text, and wrong when it has one
you did not fetch. The four existing adapters all fill it with title, location and body
(`greenhouse.py:72`, `workday.py:93`, `smartrecruiters.py:77`, `sitemap.py:268`); do the
same when you can.

What you put in `text` at first sight is **kept whole** in `posting_text`
(`run.py:482-484`) and is what every later `relabel` judges again (`run.py:626-633`).
It is written only for a posting's first sight (`run.py:473-484`), so a title-only text
stays title-only. `raw` is stored JSON-serialised and cut at 200,000 characters
(`run.py:260`); `relabel` no longer reads it, and `backfill-text` rebuilds Greenhouse
only (`backfill.py:3-9`, `78-80`).

## 6. What starts by itself

`tests/test_adapter_contract.py` is parametrized over `ADAPTERS` itself
(`test_adapter_contract.py:6-7`, `19`, `24`, `31`, `37`). **A new adapter is checked the
moment it is in the registry**, with no test edited. It checks four things only: the
registry key equals `platform` (`:20-21`); `fetch` has `source`, `known_keys`,
`detail_budget`, `progress` (`:16`, `:25-28`); the class builds with no arguments
(`:32-34`); `params` is a `frozenset` of non-empty strings (`:38-41`).

I checked this by putting two throwaway classes into the dictionary in-process (nothing
under `vedetta/` touched): the contract file collected 25 tests instead of 17; the
correct class passed all of them, and the one with a misspelt `fetch` and a plain `set`
failed exactly two, with messages naming the missing arguments and the type.

It does **not** check what `fetch` returns, nor that `resighting` is used well. That is
what the next section is for.

## 7. The fixture for `fetch` on stand-in clients

Copy `tests/test_greenhouse_smartrecruiters_fetch.py`, no network:

- `_Response` and `_Base` (`:16-30`) and a client implementing **only the verbs your
  adapter calls** (`:3-4`; Greenhouse's is `:35-42`);
- replace the adapter's client: `monkeypatch.setattr(adapter, "client", lambda: client)`
  (`:55-59`), then assert on the returned `RawPosting` list (`:62-`).

For several requests per posting, copy `tests/test_partial_listings.py:58-90`. To test
through the runner, register a stub with `monkeypatch.setitem(run_mod.ADAPTERS, "stub", ...)`
(`tests/test_partial_listings.py:180`, `tests/test_reconcile.py:292`).

## If the platform is `ashby` or `eightfold`

The production watchlist already holds one `platform: ashby` source and one
`platform: eightfold` source, enabled, with `verified_on` null. **That comes from the
operator's check of the production watchlist; it is not visible in this repository**,
which only says that both are kept "for the future" with no adapter
(`tests/test_configstore.py:121-125`, `configstore.py:417-421`).

What the code adds to that:

- a source with no `verified_on` is stored and **never polled** (`config.py:117-119`,
  `run.py:62`). To activate it, a human confirms real postings and sets `verified_on`;
- once set, and while no adapter is registered, the poll is an `error` saying the build
  has no adapter for that platform (`run.py:101-112`). Registering yours with exactly
  `platform = "ashby"` (or `"eightfold"`) is what ends that;
- while there was no adapter, those sources accepted any declared parameter
  (`configstore.py:417-426`). Once your adapter exists, they are checked against **its**
  `params`, and sync keeps only what it declares (`config.py:160-163`). Read the existing
  entries before registering, or the next save of the watchlist can be refused.
