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
from . import mailbox as mailbox_mod
from .digest import mail, render
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
    body = render.render_text(report, cfg)
    subject_line = render.subject(report, cfg.digest.get("subject_prefix", "Vedetta"))

    # A run where every source was being seeded has no news in it, so there is
    # nothing worth sending; any other run sends, including a quiet one, because a
    # missing email has to keep meaning "something is wrong".
    if args.stdout or (report["seeding"] and not report["new"]):
        print(subject_line)
        print()
        print(body)
        if report["seeding"] and not args.stdout:
            print()
            print("(every source was seeded on this run: nothing sent by design)")
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


def cmd_mail(args) -> int:
    """Read the job mailbox and record what looks like an application outcome.

    Read-only throughout, and nothing it finds changes a triage stage: the
    observations wait for a human in the interface.
    """
    cfg = _load(args)
    config = mailbox_mod.MailboxConfig.from_env(cfg.settings.get("mailbox"))
    if not config.configured:
        print("mailbox not configured: set VEDETTA_SMTP_USER and "
              "VEDETTA_SMTP_PASSWORD (one Gmail app password serves both sending "
              "and reading)", file=sys.stderr)
        return 2
    conn = db_mod.connect(cfg.db_path)
    try:
        observations = mailbox_mod.fetch(config)
    except mailbox_mod.MailboxNotConfigured as exc:
        print(f"mailbox not configured ({exc})", file=sys.stderr)
        conn.close()
        return 2
    except Exception as exc:
        print(f"mailbox read failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        conn.close()
        return 1
    stats = mailbox_mod.attach(conn, observations)
    conn.close()
    print(f"read {len(observations)} message(s) that look like an outcome")
    print(f"  new          : {stats['stored']}")
    print(f"  matched      : {stats['matched']}")
    print(f"  unmatched    : {stats['unmatched']} (shown as unmatched, not guessed)")
    print(f"  already known: {stats['already']}")
    print("Nothing was marked read, and no triage stage was changed.")
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
    sub.add_parser("mail", help="read the job mailbox for application outcomes"
                   ).set_defaults(func=cmd_mail)
    sub.add_parser("check").set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
