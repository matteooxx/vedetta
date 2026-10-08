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
    for poll in bad:
        lines.append(f"  FAILED  {poll['employer']} ({poll['platform']})")
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
