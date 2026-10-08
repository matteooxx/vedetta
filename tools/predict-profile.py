#!/usr/bin/env python3
"""Predict what a profile change would do, before it touches anything.

    vedetta-predict CANDIDATE.yaml [--root DIR] [--config-dir DIR]

Judges every open posting against both the current profile and a candidate one,
reports the moves, and **writes nothing**. The table that matters is the last one:
the postings that would go from workable to excluded, each with the rule that decided
it. That is the expensive direction — an exclusion is silent, and a posting the reader
would have taken does not come back.

This exists because it earned its place. The run that introduced region rules found
five defects the test suite had passed, including `EU` matching as a substring inside
"Eusébio, Ceara, Brazil" and making a Brazilian posting acceptable. Tests check the
cases somebody thought of; a prediction run checks the data the change will actually
meet.

Any change to how postings are judged — the profile, the rules, the place tables —
is worth running through this first.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter

import yaml

from vedetta import config as config_mod
from vedetta import db as db_mod
from vedetta.profile import Profile

BUCKETS = ("preferred", "acceptable", "conditional", "excluded", "unknown")
WORKABLE = ("preferred", "acceptable", "conditional")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("candidate", help="the profile file to try")
    parser.add_argument("--root", default=".")
    parser.add_argument("--config-dir", default=None)
    parser.add_argument("--limit", type=int, default=25,
                        help="how many examples to list per direction")
    args = parser.parse_args()

    cfg = config_mod.load(args.root, args.config_dir)
    conn = db_mod.connect(cfg.db_path)
    with open(args.candidate, encoding="utf-8") as handle:
        candidate = Profile.from_dict(yaml.safe_load(handle))

    rows = conn.execute(
        "SELECT id, title, location FROM posting WHERE closed_run IS NULL").fetchall()

    before, after, moves = Counter(), Counter(), Counter()
    lost, gained = [], []

    for row in rows:
        old, old_hit = cfg.profile.location_verdict(row["location"])
        new, new_hit = candidate.location_verdict(row["location"])
        before[old] += 1
        after[new] += 1
        if old == new:
            continue
        moves[f"{old} -> {new}"] += 1
        if old in WORKABLE and new not in WORKABLE:
            lost.append((row, old, old_hit, new, new_hit))
        elif old not in WORKABLE and new in WORKABLE:
            gained.append((row, old, old_hit, new, new_hit))

    print(f"{len(rows)} open postings, judged twice. Nothing was written.\n")
    print("location verdict, current -> candidate:")
    for bucket in BUCKETS:
        arrow = "  " if before[bucket] == after[bucket] else "->"
        print(f"  {bucket:<12} {before[bucket]:>6} {arrow} {after[bucket]:>6}")

    print("\nwhat moved:")
    for move, count in moves.most_common():
        print(f"  {count:>6}  {move}")

    _report("NO LONGER WORKABLE", lost, args.limit,
            "the expensive direction: read every reason below before applying this")
    _report("NEWLY WORKABLE", gained, args.limit,
            "cheap to be wrong about - a posting shown that need not have been")

    conn.close()
    return 0


def _report(heading: str, items: list, limit: int, note: str) -> None:
    print(f"\n{heading} ({len(items)}) - {note}")
    if not items:
        print("  none")
        return
    seen: set = set()
    for row, old, old_hit, new, new_hit in items:
        key = (str(row["location"])[:48], new_hit)
        if key in seen:
            continue
        seen.add(key)
        print(f"  {str(row['location'])[:48]:<50} {old} ({old_hit}) -> "
              f"{new} ({new_hit})")
        print(f"      {row['title'][:72]}")
        if len(seen) >= limit:
            remaining = len(items) - len(seen)
            if remaining > 0:
                print(f"  ... and {remaining} more; --limit N to see them")
            return


if __name__ == "__main__":
    sys.exit(main())
