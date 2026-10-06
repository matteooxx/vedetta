"""Command line entry point.

    vedetta init          create the database and load the watchlist
    vedetta run           poll, reconcile, label, and send the digest
    vedetta run --stdout  the same, printing instead of sending
    vedetta check         read-only integrity report
"""
from __future__ import annotations

import argparse
import sys

from . import config as config_mod
from . import db as db_mod
from . import run as run_mod
from .digest import mail, render


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

    report = run_mod.execute(conn, cfg, trigger=args.trigger, force_seed=args.seed)
    body = render.render_text(report, cfg)
    subject_line = render.subject(report, cfg.digest.get("subject_prefix", "Vedetta"))

    if args.stdout or report["seeding"]:
        print(subject_line)
        print()
        print(body)
        if report["seeding"] and not args.stdout:
            print()
            print("(seeding run: nothing sent by design)")
        conn.close()
        return 0

    try:
        result = mail.send(subject_line, body, cfg.digest)
        run_mod.mark_digest_sent(conn, report["run_id"])
        print(result)
    except mail.MailNotConfigured as exc:
        print(f"mail not configured ({exc}); printing instead", file=sys.stderr)
        print(body)
        conn.close()
        return 2
    conn.close()
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

    sub.add_parser("check").set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
