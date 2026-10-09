"""A prompt the reader can hand to their own AI to write a configuration file.

The configuration is the whole of what this program knows about its reader, and
writing it from a blank page is the part that stops people using a tool like this.
An assistant that has read their CV can do most of it in a minute.

Three things make the difference between a prompt that helps and one that produces a
plausible, wrong file:

**It carries the schema.** The real example file, comments and all, is appended to
every prompt - generated from the file on disk, so it cannot drift from the code the
way a hand-written summary would. A model given the exact keys does not invent keys.

**It forbids guessing, in the first rule rather than the last.** A configuration
file full of confident filler is worse than an empty one: the reader would believe
it. The prompt tells the assistant to collect every gap into one list of questions
and wait, and to leave a key out rather than fill it in. That is this project's own
rule about silence applied to the thing that configures it.

**It says where the personal half comes from.** A reader opening a fresh chat has an
assistant that knows nothing about them, so the prompt asks for a CV to be attached
and treats anything the assistant already remembers as a bonus rather than a
premise.

Not every file is a good candidate. There is no prompt for the watchlist: an
assistant asked for a company's hiring-platform identifier will produce one that
looks right, and during this project's own design two independent automated sources
each returned a different company than the one asked for - one of them a road-paving
contractor returned as an asset manager. Those identifiers are confirmed by a human
looking at real postings, and nothing else.
"""
from __future__ import annotations

HEADER = """\
You are helping me fill in one configuration file for Vedetta, a self-hosted
job-posting monitor. It watches the careers pages of employers I care about and
emails me when something appears that I could actually take on.

{what_this_file_is}

WHAT I AM GIVING YOU
- My CV, attached to this message. (If I forgot to attach it, ask me for it before
  doing anything else.)
- Anything you already know about me from earlier conversations, if you know
  anything. Do not assume you do.
- The exact schema of the file, at the end of this message, with a comment on every
  key explaining what it does.

RULES. The first one matters more than the other four together.

1. NEVER INVENT A VALUE. If my CV and what you know do not tell you something, do
   not guess, and do not write a plausible-looking placeholder. Collect every gap
   into ONE list of questions, ask them all at once, and wait for my answers before
   writing any of the file.
2. If I decline to answer something, LEAVE THE KEY OUT rather than filling it in. An
   absent key means "no opinion" and the program handles that. A wrong value quietly
   changes which jobs I get told about, and I would have no way of noticing.
3. Use ONLY the keys in the schema, spelled exactly as they appear there. A key that
   is not in the schema is refused when I paste the file in. A key with a typo in it
   used to save cleanly and then do nothing at all, which is why it is refused now.
4. Keep the schema's comments where they still apply, and add your own wherever a
   choice needs explaining. This file is read by a person far more often than by the
   program, and in six months that person will be me, wondering why I wrote this.
5. Output the finished file as ONE fenced YAML block, with nothing before or after
   it. I am going to paste it straight into the editor.

{guidance}

THE SCHEMA. Every key the program reads, with what it does.

```yaml
{schema}
```
"""

CURRENT = """

WHAT I HAVE NOW. Start from this and change what needs changing, rather than
beginning again: it holds decisions I have already made.

```yaml
{current}
```
"""

WHAT = {
    "profile": """\
This file, profile.yaml, is the half of the configuration that describes ME: where I
can legally work, how senior a role should be, which technologies I would claim, and
what kinds of work I am aiming at. The program labels every posting it finds against
this file and folds the ones I could not take out of its default view - it never
deletes them, so an over-strict answer costs me attention rather than opportunities,
and a wrong one costs me the opposite.""",
    "rules": """\
This file, rules.yaml, is the half that describes WHAT TO LOOK FOR: a list of
labelling rules, each a few regular expressions with an explanation attached. Every
posting is run through all of them and carries whichever labels matched, which is
what the digest shows me next to it.

I only want your help with ONE kind of rule: the role clusters, `kind: cluster`,
which say what sort of work I am after. Leave every other rule exactly as it is.""",
    "settings": """\
This file, settings.yaml, is mostly about the MACHINE rather than about me: where the
database lives, how the digest is delivered, which discovery techniques are enabled.
Most of it should be left alone.

Three parts are worth your help, and they are the only ones I want you to touch:
`digest.subject_prefix`, `ranking.weights`, and `saved_views`.""",
}

GUIDANCE = {
    "profile": """\
HOW TO THINK ABOUT THE PARTS THAT ARE EASY TO GET WRONG

- `locations` is not where I would like to live. It is where I can legally take a
  job, which is a different question with a definite answer. Regions and blocs can
  be written wherever a country can - `EU`, `EEA`, `Schengen`, `Europe`, `Asia`,
  `North America` - and they are better than a hand-written list of countries,
  because they cover the ones neither of us would have thought of. Anywhere I would
  need a visa goes under `conditional`, NOT `acceptable`, even when it sits inside a
  region I accept: a specific rule beats a region, which is exactly what that is
  for. If my CV does not make my citizenship and work authorisation unambiguous,
  ASK - this is the single field most worth getting right.
- `experience.years` is my own total. `experience.max_years_requested` is the
  ceiling I am willing to see asked for, which is a different number and usually a
  little higher: it is what decides whether "8+ years required" counts against a
  posting.
- `experience.reject_level` and `accept_level` are matched against the TITLE. Think
  about the words that appear in the titles I should and should not be shown -
  "principal", "head of", "director" against "junior", "graduate", "associate".
  Reject is tested first and wins, so a word in both lists is a rejection.
- `tracks.require_match` is the strongest filter in the file: with it on, a posting
  that matches none of my target role clusters is folded out of the default view. It
  is also the rule most likely to be wrong, because it fails whenever my clusters are
  too narrow. If you turn it on, say so in a comment.
- `skills.have` is what I would defend in a technical interview TODAY. `skills.watch`
  is what I want to be told about without claiming it. Do not pad either list to look
  impressive: `have` is shown to me as "yours", and padding it means being shown
  postings I would fail.
- `exclude_if` lists the rule ids that make a posting unworkable for me. Everything
  else is shown with a label attached and left to my judgement.""",
    "rules": """\
HOW TO WRITE A ROLE CLUSTER, AND WHAT NOT TO TOUCH

- A cluster rule looks like this, and the `when` patterns are matched against the
  posting's TITLE when `field: title` is set, which is almost always what a cluster
  wants:

      - id: cluster-platform
        kind: cluster
        severity: positive
        weight: 5
        field: title
        explain: "platform engineering"
        when:
          - '(?i)\\b(platform|infrastructure|devops|sre)\\b.{0,24}\\b(engineer|developer)\\b'

- Work from REAL POSTINGS, not from job-title theory. Ask me for three or four
  adverts I was genuinely interested in and three I was not, and build the patterns
  from the words those titles actually use. A cluster invented from a taxonomy
  matches nothing.
- Every pattern needs `\\b` word boundaries. Without them "SRE" matches "pressure"
  and "ops" matches "shops", and the label will be wrong in a way I will not notice
  because it looks plausible.
- `explain` is shown to me beside the posting, so write it as a phrase a human reads:
  "platform engineering", not "CLUSTER_PLATFORM_ENG".
- Keep every `kind: gate` rule EXACTLY as it is. Those encode visa and language
  facts, and I have tuned them against real adverts. Do not reword them, do not
  "improve" their regular expressions, do not reorder them.
- Do not add a rule that makes a judgement about whether I would be good at a job.
  This program labels and orders; the deciding is mine.""",
    "settings": """\
WHAT TO DO WITH THE THREE PARTS, AND WHAT TO LEAVE

- `digest.subject_prefix` is the first thing I see in my inbox. One short word.
- `ranking.weights` sets how much each severity moves a posting up or down the
  digest. The defaults are deliberate: positive +3, warning -2, blocking -6, info 0.
  Change them only if I tell you I want a different balance, and explain the change
  in a comment.
- `saved_views` are named filter URLs, shown as shortcuts above the postings list.
  These are worth generating: propose three or four that follow from my profile, each
  a `name` and a `query` of filter parameters. For example
  `{"name": "Ireland, this week", "query": "place=Ireland&age=7d"}`. The parameters
  available are `place`, `employer`, `skill`, `label`, `triage`, `mode`, `age`,
  `scope` and `q`.
- LEAVE ALONE: `database`, `digest.transport`, `digest.host`, `digest.port`,
  `digest.user`, `digest.sender`, `digest.starttls`, every key under `discovery`, and
  `ai_worker`. Those describe the machine this runs on and the techniques it is
  allowed to use. Getting them wrong stops the program working, and none of them can
  be worked out from my CV.
- Never write a password, token or app password into this file. The program is built
  to hold no credential of any kind, and this file is edited in a browser.""",
}

# The files an assistant can usefully write. The watchlist is deliberately absent -
# see the module docstring.
GENERATED = ("profile", "rules", "settings")


def build(name: str, schema: str, current: str | None = None) -> str:
    """The prompt for one file. `schema` is the example file, `current` the real one."""
    if name not in GENERATED:
        raise KeyError(name)
    prompt = HEADER.format(what_this_file_is=WHAT[name], guidance=GUIDANCE[name],
                           schema=schema.rstrip())
    if current:
        prompt += CURRENT.format(current=current.rstrip())
    return prompt
