"""Composing the digest.

Two rules govern the layout and neither is cosmetic:

* **Nothing is hidden.** Labels decide order and prominence, never visibility. A
  posting the ranking dislikes is still present, further down, with the reason shown
  so it can be disagreed with.
* **Silence is impossible.** The health section reports failed sources and employers
  with no working route. A quiet day still sends mail, so a missing email always
  means a fault rather than a quiet market.
"""
from __future__ import annotations

import textwrap
from datetime import datetime, timezone

SEVERITY_MARK = {
    "blocking": "[blocks]", "warning": "[warn]", "positive": "[fits]", "info": "[note]",
}


def _labels_line(labels: list[dict]) -> str:
    if not labels:
        return "no labels matched - shown unranked rather than dropped"
    parts = []
    for label in labels:
        mark = SEVERITY_MARK.get(label["severity"], "[note]")
        value = f" {label['value']}" if label.get("value") else ""
        parts.append(f"{mark} {label['explain']}{value}")
    return " | ".join(parts)


def subject(report: dict, prefix: str = "Vedetta") -> str:
    count = len(report["new"])
    seeded = len(report.get("seeded") or [])
    excluded = len(report.get("excluded") or [])
    broken = sum(1 for p in report["polls"] if p["outcome"] == "error")
    bits = [f"{count} new" if count else "nothing new"]
    if excluded:
        bits.append(f"{excluded} excluded")
    if seeded:
        bits.append(f"{seeded} seeded")
    if broken:
        bits.append(f"{broken} source{'s' if broken > 1 else ''} failing")
    # Visible in the inbox list, before anything is opened: a rebuilt digest is
    # about a run that already happened, and reading it as today's news wastes an
    # afternoon on postings that have since closed.
    late = " [rebuilt]" if report.get("rebuilt") else ""
    return f"{prefix}{late}: " + ", ".join(bits)


def render_text(report: dict, config=None) -> str:
    lines: list[str] = []
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"Vedetta - run {report['run_id']} - {stamp}")
    lines.append("=" * 62)
    lines.append("")

    if report.get("rebuilt"):
        # Said at the top, not in a footnote. A digest rebuilt days later looks
        # exactly like a live one, and acting on it as though it were current means
        # applying to postings that may already have closed.
        lines.append("REBUILT AFTER THE FACT. This run's digest was never delivered,")
        lines.append("so it has been reassembled from the database. The postings were")
        lines.append("first seen on the date of the run above, NOT today: check each")
        lines.append("one is still open before spending time on it.")
        lines.append("")

    seeded = report.get("seeded") or []
    if seeded:
        fresh = sorted({p["employer"] for p in seeded})
        lines.append(f"SEEDED {len(seeded)} existing postings from {len(fresh)} newly")
        lines.append(f"watched source(s): {', '.join(fresh)}.")
        lines.append("They are recorded as history, not reported as news. Anything these")
        lines.append("sources publish from now on appears below like everything else.")
        lines.append("")

    new = report["new"]
    threshold = 0
    strong = [p for p in new if p["score"] >= threshold]
    rest = [p for p in new if p["score"] < threshold]

    lines.append(f"NEW AND WORKABLE ({len(new)})")
    lines.append("-" * 62)
    if not new:
        if report.get("excluded"):
            lines.append("None that your profile says you could take on. The ones that")
            lines.append("were excluded are listed further down with the reason.")
        else:
            # "Every watched source answered" has to be TRUE to be worth printing, and
            # it was printed unconditionally. On 19 November 2026 a lab run produced a
            # digest whose subject said "nothing new, 1 source failing" over a body
            # saying every source had answered: the two halves of the same mail
            # disagreeing.
            #
            # It matters more than a wording slip. When a source fails, "nothing new"
            # may be nothing new *because of the failure* - and a reader who takes the
            # sentence at face value reads the gap as quiet. That is the silent drop
            # this project exists to prevent, arriving as a reassurance.
            silent = [p for p in (report.get("polls") or [])
                      if p.get("outcome") in ("error", "empty", "partial")]
            if silent:
                # Wrapped to the width of the rules above and below it. The prose in
                # this file is hand-wrapped at 62 and nothing here wraps on its own, so
                # a sentence built from a count has to do it itself or it arrives as
                # one 181-character line in a plain-text mail.
                lines.extend(textwrap.wrap(
                    f"None from the sources that answered, and {len(silent)} of "
                    f"{len(report.get('polls') or [])} did not answer in full - so "
                    f"this may be short by whatever those would have carried. The "
                    f"reasons are under SOURCE HEALTH.", width=62))
            else:
                lines.append("None. Every watched source answered and had nothing new.")
    for group, heading in ((strong, None), (rest, "Lower ranked - shown, not hidden")):
        if heading and group:
            lines.append("")
            lines.append(heading)
            lines.append("-" * 62)
        for posting in group:
            flag = " [pipeline, not an opening]" if any(
                l["kind"] == "pipeline" for l in posting["labels"]) else ""
            lines.append(f"* {posting['employer']} - {posting['title']}{flag}")
            where = posting.get("location") or "location not stated"
            when = posting.get("published_at") or "date not supplied"
            lines.append(f"    {where} | published {when} | score {posting['score']:+d}")
            lines.append(f"    {_labels_line(posting['labels'])}")
            if posting.get("skills"):
                lines.append(f"    {posting['skills']}")
            if posting.get("url"):
                lines.append(f"    {posting['url']}")
            lines.append("")

    excluded = report.get("excluded") or []
    if excluded:
        lines.append(f"EXCLUDED BY YOUR PROFILE ({len(excluded)})")
        lines.append("-" * 62)
        for reason, count in (report.get("excluded_reasons") or {}).items():
            lines.append(f"  {count:4d}  {reason}")
        lines.append("")
        lines.append("  Listed in full below, not dropped. If any of these should have")
        lines.append("  reached you, the fix is one line in profile.yaml.")
        lines.append("")
        for posting in excluded[:40]:
            where = posting.get("location") or "location not stated"
            lines.append(f"  - {posting['employer']} - {posting['title']} | {where}")
        if len(excluded) > 40:
            lines.append(f"  ... and {len(excluded) - 40} more, all visible in the interface")
        lines.append("")

    if report.get("closed"):
        lines.append(f"CLOSED SINCE LAST RUN: {report['closed']}")
        lines.append("")

    lines.append("SOURCE HEALTH")
    lines.append("-" * 62)
    ok = [p for p in report["polls"] if p["outcome"] == "ok"]
    empty = [p for p in report["polls"] if p["outcome"] == "empty"]
    bad = [p for p in report["polls"] if p["outcome"] == "error"]
    short = [p for p in report["polls"] if p["outcome"] == "partial"]
    counts = [f"{len(ok)} ok", f"{len(empty)} returned nothing"]
    if short:
        counts.append(f"{len(short)} short")
    counts.append(f"{len(bad)} failed")
    lines.append(", ".join(counts) + f", {report['sources']} configured")
    # The reason goes UNDER the name, exactly as it does for SHORT and NOTE below.
    # It did not, and failure was the only outcome whose explanation was never
    # printed - which is backwards, because it is the one the reader can do nothing
    # about without knowing why. For two days in November 2026 this section said
    # "4 failed" over four names while the record knew each had answered 429 with no
    # Retry-After, which is a refusal and not an outage, and means something entirely
    # different about what to do next.
    for poll in bad:
        lines.append(f"  FAILED  {poll['employer']} ({poll['platform']})")
        reason = poll.get("error")
        if reason:
            lines.append(f"          {reason}")
        if poll.get("note"):
            lines.append(f"          {poll['note']}")
    # Its own word, not FAILED. A listing that came back short answered, and its
    # postings are in this digest; what it cannot do is prove a posting has gone, so
    # nothing was closed for that employer. Reported here and not in the subject
    # line: a large board loses a posting mid-walk often enough that putting it in
    # the subject would teach the reader to ignore the subject.
    for poll in short:
        lines.append(f"  SHORT   {poll['employer']} ({poll['platform']})")
        if poll.get("note"):
            lines.append(f"          {poll['note']}")
    for poll in empty:
        lines.append(f"  EMPTY   {poll['employer']} ({poll['platform']}) - "
                     "a board with no postings, or a wrong identifier")
    # A note on a poll that otherwise went well: something survivable worth saying,
    # such as a posting served without a title that could not be recorded. Printed
    # only here, never in the subject - it is not a failure.
    for poll in ok + empty:
        if poll.get("note"):
            lines.append(f"  NOTE    {poll['employer']} ({poll['platform']})")
            lines.append(f"          {poll['note']}")
    if report.get("unwatched"):
        lines.append("")
        lines.append("NOT WATCHED - no confirmed route exists for these employers:")
        for row in report["unwatched"]:
            url = f" - {row['careers_url']}" if row.get("careers_url") else ""
            lines.append(f"  {row['display_name']}{url}")
        lines.append("  (listed so the gap is visible; absence here would look like silence)")

    lines.append("")
    lines.append("-" * 62)
    lines.append("Ranking is a transparent sum over the labels above. Nothing was")
    lines.append("dropped: anything your profile excluded is listed, with the reason.")
    lines.append("Disagree by editing rules.yaml or profile.yaml.")
    return "\n".join(lines)
