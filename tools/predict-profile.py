#!/usr/bin/env python3
"""Predict what a profile change would do, before it touches anything.

    predict-profile.py CANDIDATE.yaml [--root DIR] [--config-dir DIR]

Judges every open posting against both the saved profile and a candidate one, reports
the moves, and **writes nothing**. The table that matters is the last one: the
postings that would go from workable to excluded, each with the rule that decided it.
That is the expensive direction - an exclusion is silent, and a posting the reader
would have taken does not come back.

The interface has the same thing as a Check button beside Save. Both call
`vedetta.predict`, so there is one copy of the reasoning: the command line exists for
a profile that is not in the configuration directory yet, and for a terminal.

This earned its place. The run that introduced region rules found five defects the
test suite had passed, including a two-letter region name matching as a substring
inside "Eusebio, Ceara, Brazil" and making a Brazilian posting acceptable. Tests check
the cases somebody thought of; a prediction checks the data the change will meet.
"""
from __future__ import annotations

import argparse
import sys

import yaml

from vedetta import config as config_mod
from vedetta import db as db_mod
from vedetta import predict
from vedetta.profile import Profile


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

    report = predict.profile_effect(conn, cfg.profile, candidate)
    conn.close()

    print(f"{report['postings']} open postings, judged twice. "
          f"Nothing was written.\n")
    print("location verdict, saved -> candidate:")
    for bucket in predict.BUCKETS:
        was, now = report["before"][bucket], report["after"][bucket]
        arrow = "  " if was == now else "->"
        print(f"  {bucket:<12} {was:>6} {arrow} {now:>6}")

    print("\nwhat moved:")
    for move, count in report["moves"]:
        print(f"  {count:>6}  {move}")

    _report("NO LONGER WORKABLE", report["lost"], report["lost_total"],
            "the expensive direction: read every reason before applying this")
    _report("NEWLY WORKABLE", report["gained"], report["gained_total"],
            "cheap to be wrong about - a posting shown that need not have been")
    return 0


def _report(heading: str, sample: list[dict], total: int, note: str) -> None:
    print(f"\n{heading} ({total}) - {note}")
    if not sample:
        print("  none")
        return
    for move in sample:
        print(f"  {str(move['location'])[:48]:<50} {move['was']} "
              f"({move['was_why']}) -> {move['now']} ({move['now_why']})")
        print(f"      {move['title'][:72]}")
    if total > len(sample):
        print(f"  ... and {total - len(sample)} more; the interface's Check button "
              f"shows the same report")


if __name__ == "__main__":
    sys.exit(main())
