"""Give postings collected before `posting_text` existed the text first sight read.

Only Greenhouse can be rebuilt: its adapter keeps the whole job, description
included, as `raw`, and builds the text from it with one formula
(adapters/greenhouse.py:72), applied here unchanged. Workday and SmartRecruiters keep
the listing entry, without a description, and the sitemap adapter drops it on
purpose: for them there is no body anywhere, and the posting stays on rule B of
`run.relabel`. A Greenhouse `raw` cut at 200,000 characters is no longer JSON; it is
counted apart and stays on rule B too.

The platform is the one of the posting's first sighting: the item that created the
posting is the one whose `raw` was stored. Reading Workday's `raw` through the
Greenhouse formula would give the title alone, stored as if it were the text - and
the next relabel would recompute on it and drop every label the body gave.

A command, never a start-up step: it rewrites data, so a person decides when.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .adapters.greenhouse import _unescape
from .labels.engine import now_iso

ORIGIN = "backfill-greenhouse"


@dataclass
class Report:
    read: int = 0            # postings with no row in posting_text
    with_text: int = 0       # rebuilt (written only with apply)
    without_text: int = 0    # a platform whose raw has no body
    unreadable: int = 0      # Greenhouse, but raw is not a readable job
    already_stored: int = 0  # had a row; never rewritten
    by_platform: dict = field(default_factory=dict)

    def count(self, platform: str | None, outcome: str) -> None:
        setattr(self, outcome, getattr(self, outcome) + 1)
        per = self.by_platform.setdefault(
            platform or "unknown", {"with_text": 0, "without_text": 0, "unreadable": 0})
        per[outcome] += 1


def greenhouse_text(raw: str | None, title: str) -> str | None:
    """The adapter's text, from the stored job. None when `raw` cannot be read."""
    try:
        job = json.loads(raw) if raw else None
    except ValueError:
        return None
    if not isinstance(job, dict):
        return None
    location = (job.get("location") or {}).get("name")
    content = job.get("content") or ""
    text = " \n".join(filter(None, [job.get("title"), location, _unescape(content)]))
    # The same fallback as first sight (run.execute_in): no text, the title.
    return text or title


def backfill(conn, apply: bool = False) -> Report:
    report = Report()
    report.already_stored = conn.execute("SELECT count(*) FROM posting_text").fetchone()[0]
    rows = conn.execute(
        """WITH first AS (SELECT posting_id, min(id) AS id FROM sighting
                          GROUP BY posting_id)
           SELECT p.id, p.title, p.raw, src.platform
           FROM posting p
           LEFT JOIN posting_text t ON t.posting_id = p.id
           LEFT JOIN first f ON f.posting_id = p.id
           LEFT JOIN sighting s ON s.id = f.id
           LEFT JOIN source src ON src.id = s.source_id
           WHERE t.posting_id IS NULL
           ORDER BY p.id""").fetchall()

    rebuilt = []
    for row in rows:
        report.read += 1
        if row["platform"] != "greenhouse":
            report.count(row["platform"], "without_text")
            continue
        text = greenhouse_text(row["raw"], row["title"])
        if text is None:
            report.count(row["platform"], "unreadable")
            continue
        report.count(row["platform"], "with_text")
        rebuilt.append((row["id"], text))

    if apply and rebuilt:
        stamp = now_iso()
        # OR IGNORE: a text stored by first sight is never overwritten by a rebuild.
        conn.executemany(
            "INSERT OR IGNORE INTO posting_text (posting_id, text, origin, stored_at) "
            "VALUES (?,?,?,?)", [(pid, text, ORIGIN, stamp) for pid, text in rebuilt])
        conn.commit()
    return report
