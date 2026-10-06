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
    broken = sum(1 for p in report["polls"] if p["outcome"] == "error")
    bits = [f"{count} new" if count else "nothing new"]
    if broken:
        bits.append(f"{broken} source{'s' if broken > 1 else ''} failing")
    return f"{prefix}: " + ", ".join(bits)


def render_text(report: dict, config=None) -> str:
    lines: list[str] = []
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"Vedetta - run {report['run_id']} - {stamp}")
    lines.append("=" * 62)
    lines.append("")

    if report.get("seeding"):
        lines.append("SEEDING RUN - the watchlist was recorded, no mail would normally")
        lines.append("be sent for it. Notifications begin with the next run.")
        lines.append("")

    new = report["new"]
    threshold = 0
    strong = [p for p in new if p["score"] >= threshold]
    rest = [p for p in new if p["score"] < threshold]

    lines.append(f"NEW POSTINGS ({len(new)})")
    lines.append("-" * 62)
    if not new:
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
            if posting.get("url"):
                lines.append(f"    {posting['url']}")
            lines.append("")

    if report.get("closed"):
        lines.append(f"CLOSED SINCE LAST RUN: {report['closed']}")
        lines.append("")

    lines.append("SOURCE HEALTH")
    lines.append("-" * 62)
    ok = [p for p in report["polls"] if p["outcome"] == "ok"]
    empty = [p for p in report["polls"] if p["outcome"] == "empty"]
    bad = [p for p in report["polls"] if p["outcome"] == "error"]
    lines.append(f"{len(ok)} ok, {len(empty)} returned nothing, {len(bad)} failed, "
                 f"{report['sources']} configured")
    for poll in bad:
        lines.append(f"  FAILED  {poll['employer']} ({poll['platform']})")
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
    lines.append("Ranking is a transparent sum over the labels above. Disagree with it")
    lines.append("by editing the rule file; nothing was filtered out of this mail.")
    return "\n".join(lines)
