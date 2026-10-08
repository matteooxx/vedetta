"""Command line entry point.

    vedetta init          create the database and load the watchlist
    vedetta run           poll, reconcile, label, and send the digest
    vedetta run --stdout  the same, printing instead of sending
    vedetta check         read-only integrity report
    vedetta digest --run N  rebuild and queue a run's digest that never went out
"""
from __future__ import annotations

import argparse
import sys

from . import config as config_mod
from . import db as db_mod
from . import run as run_mod
from .digest import dispatch as dispatch_mod
from .digest import outbox, rebuild
from .runlock import RunInProgress, acquire


def _load(args):
    cfg = config_mod.load(args.root, args.config_dir)
    return cfg


def cmd_init(args) -> int:
    cfg = _load(args)
    conn = db_mod.connect(cfg.db_path)
    counts = config_mod.sync_watchlist(conn, cfg.watchlist)
    print(f"database : {cfg.db_path}")
    print(f"config   : {', '.join(f'{k}={v}' for k, v in cfg.sources_used.items())}")
    print(f"employers: {counts['employers']}")
    print(f"sources  : {counts['sources']} "
          f"({counts['unverified']} without verified_on, which will NOT be polled)")
    if counts["unverified"]:
        print("           a source is only polled once a human has confirmed it by")
        print("           looking at real postings - see docs/brainstorm/S03-discovery.md")
    conn.close()
    return 0


def cmd_run(args) -> int:
    cfg = _load(args)
    conn = db_mod.connect(cfg.db_path)
    config_mod.sync_watchlist(conn, cfg.watchlist)

    lock_path = cfg.db_path.parent / "run.lock"
    try:
        with acquire(lock_path, owner=f"cli:{args.trigger}"):
            report = run_mod.execute(conn, cfg, trigger=args.trigger,
                                     force_seed=args.seed)
    except RunInProgress as exc:
        print(f"skipped: {exc}", file=sys.stderr)
        conn.close()
        return 3
    # One shared decision for every caller. The interface used to make this call
    # itself and made it wrong - it queued nothing - so there is now only one copy.
    if args.stdout:
        subject_line, body = dispatch_mod.compose(report, cfg)
        print(subject_line)
        print()
        print(body)
        conn.close()
        return 0

    outcome = dispatch_mod.dispatch(conn, cfg, report)
    if outcome.action == "skipped":
        print(outcome.subject)
        print()
        print(outcome.body)
        print()
        print(f"({outcome.detail})")
        conn.close()
        return 0
    if outcome.action == "unsendable":
        print(outcome.detail, file=sys.stderr)
        print(outcome.body)
        conn.close()
        return 2
    print(outcome.detail)
    conn.close()
    return 0


def cmd_digest(args) -> int:
    """Rebuild a past run's digest and queue it.

    The recovery path for a digest that never went out. It happened: runs started
    from the interface queued nothing for a while, so their postings were recorded -
    and therefore stopped being new - without anybody being told. `--list` shows
    which runs are in that state.
    """
    cfg = _load(args)
    conn = db_mod.connect(cfg.db_path)
    if args.list:
        rows = conn.execute(
            "SELECT r.id, r.started_at, r.trigger, r.digest_sent, r.seeding, "
            "       (SELECT COUNT(*) FROM posting p WHERE p.first_seen_run = r.id) "
            "         AS first_seen, "
            "       (SELECT COUNT(*) FROM posting p WHERE p.first_seen_run = r.id "
            "          AND p.workable = 1) AS workable "
            "FROM run r WHERE r.state = 'finished' ORDER BY r.id").fetchall()
        queued = {p.run_id for p in outbox.pending(cfg.db_path)}
        print(f"{'run':>4}  {'started':<20} {'trigger':<9} {'first seen':>10} "
              f"{'workable':>9}  digest")
        lost = []
        for row in rows:
            if row["digest_sent"]:
                state = "sent"
            elif row["id"] in queued:
                state = "queued"
            elif row["seeding"]:
                # A seeding run reports nothing by design: it is somebody's back
                # catalogue. Calling that a loss would bury the real ones.
                state = "seeded, by design"
            elif row["first_seen"]:
                state = "NEVER REPORTED"
                lost.append(row)
            else:
                state = "nothing to report"
            print(f"{row['id']:>4}  {row['started_at'][:19]:<20} "
                  f"{row['trigger']:<9} {row['first_seen']:>10} "
                  f"{row['workable']:>9}  {state}")
        if lost:
            total = sum(r["workable"] for r in lost)
            print()
            print(f"{len(lost)} run(s) found postings and reported none of them: "
                  f"{total} workable in total.")
            print("Rebuild one with:  vedetta digest --run N")
        conn.close()
        return 0

    if not args.run:
        print("give --run N, or --list to see which runs need one", file=sys.stderr)
        conn.close()
        return 1

    try:
        report = rebuild.report_for(conn, cfg, args.run)
    except LookupError as exc:
        print(str(exc), file=sys.stderr)
        conn.close()
        return 1

    if args.stdout:
        subject_line, body = dispatch_mod.compose(report, cfg)
        print(subject_line)
        print()
        print(body)
        conn.close()
        return 0

    outcome = dispatch_mod.dispatch(conn, cfg, report)
    print(outcome.detail)
    conn.close()
    return 0


def cmd_relabel(args) -> int:
    """Re-apply the current rules and profile to postings already stored.

    The labels are a cached judgement. Without this, editing rules.yaml or
    profile.yaml appears not to work: the postings you were looking at keep their old
    verdicts, and anything you just un-excluded stays hidden.
    """
    cfg = _load(args)
    conn = db_mod.connect(cfg.db_path)
    stats = run_mod.relabel(conn, cfg)
    conn.close()
    print(f"re-evaluated {stats['postings']} postings against the current configuration")
    print(f"  workable : {stats['workable']}")
    print(f"  excluded : {stats['excluded']} (folded out of the default view, not deleted)")
    return 0


def cmd_outbox(args) -> int:
    """List, print or retire queued digests.

    Exists so the queue is inspectable by a person and not only by the runner: a
    digest sitting undelivered is a fault, and a fault nobody can see is the kind
    this project is organised against.
    """
    cfg = _load(args)
    waiting = outbox.pending(cfg.db_path)
    if args.sent is not None:
        conn = db_mod.connect(cfg.db_path)
        run_mod.mark_digest_sent(conn, args.sent)
        conn.close()
        for item in waiting:
            if item.run_id == args.sent:
                outbox.clear(item.path)
        print(f"run {args.sent} recorded as delivered")
        return 0
    if args.show is not None:
        for item in waiting:
            if item.run_id == args.show:
                print(item.subject)
                print()
                print(item.body)
                return 0
        print(f"no queued digest for run {args.show}", file=sys.stderr)
        return 1
    if not waiting:
        print("outbox empty")
        return 0
    print(f"{len(waiting)} digest(s) waiting for delivery:")
    for item in waiting:
        print(f"  run {item.run_id}: {item.subject}")
    return 0


def cmd_check(args) -> int:
    cfg = _load(args)
    status = db_mod.check(cfg.db_path)
    print(status)
    return 0 if status.get("ok") else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="vedetta")
    parser.add_argument("--root", default=".", help="project root (default: .)")
    parser.add_argument("--config-dir", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init").set_defaults(func=cmd_init)

    run_parser = sub.add_parser("run")
    run_parser.add_argument("--stdout", action="store_true", help="print, do not send")
    run_parser.add_argument("--seed", action="store_true", help="force a silent seeding run")
    run_parser.add_argument("--trigger", default="manual")
    run_parser.set_defaults(func=cmd_run)

    sub.add_parser("relabel", help="re-apply rules and profile to stored postings"
                   ).set_defaults(func=cmd_relabel)

    outbox_parser = sub.add_parser("outbox", help="queued digests awaiting delivery")
    outbox_parser.add_argument("--show", type=int, metavar="RUN",
                               help="print the queued digest for a run")
    outbox_parser.add_argument("--sent", type=int, metavar="RUN",
                               help="record a run as delivered and remove it")
    outbox_parser.set_defaults(func=cmd_outbox)

    digest_parser = sub.add_parser(
        "digest", help="rebuild and queue the digest for a run that never sent one")
    digest_parser.add_argument("--run", type=int, metavar="N",
                               help="the run to rebuild")
    digest_parser.add_argument("--list", action="store_true",
                               help="which runs have postings but never reported")
    digest_parser.add_argument("--stdout", action="store_true",
                               help="print it instead of queueing it")
    digest_parser.set_defaults(func=cmd_digest)
    sub.add_parser("check").set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
