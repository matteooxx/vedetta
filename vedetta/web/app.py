"""The web interface.

A long-running service, which is why it is a Custom App and the daily run is not
(ADR-0016). It is an editor for the configuration files and a reader of the
database; it is not a second source of truth for anything.

Deliberately server-rendered with no build step and no client framework: the whole
point of this page is to be readable and editable years from now.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from flask import (Flask, abort, flash, redirect, render_template, request,
                   url_for)

from .. import config as config_mod
from .. import configstore
from .. import facets
from .. import db as db_mod
from .. import run as run_mod
from ..runlock import RunInProgress, acquire

ROOT = Path(os.environ.get("VEDETTA_ROOT", "."))
CONFIG_DIR = Path(os.environ.get("VEDETTA_CONFIG_DIR", ROOT / "config"))


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def humanise(value) -> str:
    """Turn a platform timestamp into something a person reads at a glance.

    The platforms return half a dozen shapes - "2026-09-23T11:37:50-04:00",
    "2026-10-6", a bare date. Showing those raw was the single most unfriendly thing
    in the first interface: a column of ISO strings is data, not information.
    """
    if not value:
        return "Date not supplied"
    text = str(value).strip()
    try:
        head = text.replace("Z", "+00:00")
        stamp = datetime.fromisoformat(head)
    except ValueError:
        try:
            parts = [int(x) for x in text.split("T")[0].split("-")]
            stamp = datetime(parts[0], parts[1], parts[2])
        except Exception:
            return text[:24]
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    days = (now - stamp).days
    pretty = f"{stamp.day} {MONTHS[stamp.month - 1]} {stamp.year}"
    if days < 0:
        return pretty
    if days == 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        return f"{pretty} · {days // 7} weeks ago"
    return pretty


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("VEDETTA_SECRET_KEY") or os.urandom(32)
    app.jinja_env.filters["when"] = humanise

    def load_config():
        return config_mod.load(ROOT, str(CONFIG_DIR))

    def open_db(cfg):
        return db_mod.connect(cfg.db_path)

    # ------------------------------------------------------------------ dashboard
    @app.route("/")
    def dashboard():
        cfg = load_config()
        conn = open_db(cfg)
        last = conn.execute(
            "SELECT * FROM run ORDER BY id DESC LIMIT 1").fetchone()
        polls = []
        if last:
            polls = conn.execute(
                """SELECT p.outcome, p.item_count, p.error, s.platform,
                          e.display_name AS employer
                   FROM source_poll p
                   JOIN source s ON s.id = p.source_id
                   JOIN employer e ON e.id = s.employer_id
                   WHERE p.run_id = ?
                   ORDER BY (p.outcome='error') DESC, e.display_name""",
                (last["id"],),
            ).fetchall()
        counts = {
            "postings": conn.execute(
                "SELECT count(*) FROM posting WHERE closed_run IS NULL").fetchone()[0],
            "employers": conn.execute(
                "SELECT count(*) FROM employer WHERE enabled=1").fetchone()[0],
            "polled": conn.execute(
                """SELECT count(*) FROM source
                   WHERE enabled=1 AND verified_on IS NOT NULL""").fetchone()[0],
            "awaiting": conn.execute(
                """SELECT count(*) FROM source
                   WHERE enabled=1 AND verified_on IS NULL""").fetchone()[0],
        }
        unwatched = run_mod.unwatched(conn)
        conn.close()
        return render_template("dashboard.html", last=last, polls=polls,
                               counts=counts, unwatched=unwatched, cfg=cfg)

    # ------------------------------------------------------------------- postings
    @app.route("/postings")
    def postings():
        cfg = load_config()
        conn = open_db(cfg)
        selection = facets.Selection.from_request(request.args)
        rows = facets.page(conn, selection)
        view = {
            "scopes": facets.scope_counts(conn, selection),
            "options": facets.options(conn, selection),
            "total": facets.total(conn, selection),
        }
        conn.close()
        return render_template("postings.html", postings=rows, sel=selection,
                               view=view, profile_on=cfg.profile.configured)

    @app.post("/postings/<int:posting_id>/triage")
    def triage(posting_id: int):
        cfg = load_config()
        conn = open_db(cfg)
        state = request.form.get("state")
        if state not in ("interested", "dismissed", "applied", "clear"):
            abort(400)
        if state == "clear":
            conn.execute("DELETE FROM triage WHERE posting_id=?", (posting_id,))
        else:
            from ..labels.engine import now_iso
            conn.execute(
                """INSERT INTO triage (posting_id, state, decided_at) VALUES (?,?,?)
                   ON CONFLICT(posting_id) DO UPDATE SET
                     state=excluded.state, decided_at=excluded.decided_at""",
                (posting_id, state, now_iso()))
        conn.commit()
        conn.close()
        return redirect(request.referrer or url_for("postings"))

    # -------------------------------------------------------------------- sources
    @app.route("/sources")
    def sources():
        cfg = load_config()
        conn = open_db(cfg)
        rows = [dict(r) for r in conn.execute(
            """SELECT s.*, e.display_name AS employer, e.careers_url
               FROM source s JOIN employer e ON e.id = s.employer_id
               ORDER BY (s.verified_on IS NULL) DESC, e.display_name""").fetchall()]
        conn.close()
        return render_template("sources.html", sources=rows)

    @app.post("/sources/<int:source_id>/sample")
    def sample(source_id: int):
        """Fetch a few live postings so a human can confirm before enrolling.

        This is the enrolment rule given a home. Two independent automated methods
        each returned a different company than the one asked for during design - one
        of them a road-paving contractor - and both were caught only by someone
        reading actual titles. So the UI shows titles, never a row count.
        """
        cfg = load_config()
        conn = open_db(cfg)
        row = conn.execute(
            """SELECT s.*, e.display_name AS employer FROM source s
               JOIN employer e ON e.id = s.employer_id WHERE s.id=?""",
            (source_id,)).fetchone()
        conn.close()
        if row is None:
            abort(404)
        source = dict(row)
        adapter_cls = run_mod.ADAPTERS.get(source["platform"])
        if adapter_cls is None:
            flash(f"No adapter for '{source['platform']}' yet, so this source cannot "
                  f"be sampled or polled. It is listed as unwatched on purpose.", "warn")
            return redirect(url_for("sources"))
        try:
            items = adapter_cls().fetch(source)
        except Exception as exc:
            flash(f"{source['employer']}: fetch failed - {exc}", "error")
            return redirect(url_for("sources"))
        preview = [{"title": i.title, "location": i.location, "url": i.url,
                    "published_at": i.published_at} for i in items[:8]]
        return render_template("sample.html", source=source, preview=preview,
                               total=len(items))

    # --------------------------------------------------------------------- config
    @app.route("/config/<name>", methods=["GET", "POST"])
    def config_edit(name: str):
        if name not in configstore.EDITABLE:
            abort(404)
        if request.method == "POST":
            text = request.form.get("text", "")
            expected = request.form.get("digest") or None
            try:
                saved = configstore.save(CONFIG_DIR, name, text, expected)
            except configstore.ConflictError as exc:
                flash("Not saved: the file changed on disk since you opened it. "
                      "Your version is below; the version now on disk is shown "
                      "beside it. Nothing was overwritten.", "error")
                return render_template("config.html", name=name, text=text,
                                       digest=exc.current_hash,
                                       conflict=exc.current_text, path=None,
                                       is_example=False)
            except configstore.ConfigError as exc:
                flash(f"Not saved: {exc}", "error")
                return render_template("config.html", name=name, text=text,
                                       digest=expected, conflict=None, path=None,
                                       is_example=False)
            flash(f"Saved {saved.path.name}. A timestamped backup was kept beside it.",
                  "ok")
            return redirect(url_for("config_edit", name=name))

        current = configstore.read(CONFIG_DIR, name)
        return render_template("config.html", name=name, text=current.text,
                               digest=current.digest, conflict=None,
                               path=current.path, is_example=current.is_example)

    # ------------------------------------------------------------------- run now
    @app.post("/run")
    def run_now():
        cfg = load_config()
        conn = open_db(cfg)
        config_mod.sync_watchlist(conn, cfg.watchlist)
        lock_path = Path(cfg.db_path).parent / "run.lock"
        try:
            with acquire(lock_path, owner="web-ui"):
                report = run_mod.execute(conn, cfg, trigger="manual")
        except RunInProgress as exc:
            conn.close()
            flash(str(exc), "warn")
            return redirect(url_for("dashboard"))
        conn.close()
        new = len(report["new"])
        seeded = len(report.get("seeded") or [])
        failed = sum(1 for p in report["polls"] if p["outcome"] == "error")
        parts = [f"{new} new"] if new else ["nothing new"]
        if seeded:
            parts.append(f"{seeded} seeded")
        if failed:
            parts.append(f"{failed} source(s) failed")
        flash("Run finished: " + ", ".join(parts)
              + ". No mail was sent from here - the scheduled run does that.", "ok")
        return redirect(url_for("dashboard"))

    @app.post("/relabel")
    def relabel_now():
        """Re-apply the current rules and profile to every stored posting.

        Without this the interface lies after a configuration edit: the postings on
        screen keep their old verdicts, so a filter you just widened appears to have
        done nothing.
        """
        cfg = load_config()
        conn = open_db(cfg)
        lock_path = Path(cfg.db_path).parent / "run.lock"
        try:
            with acquire(lock_path, owner="web-ui:relabel"):
                stats = run_mod.relabel(conn, cfg)
        except RunInProgress as exc:
            conn.close()
            flash(str(exc), "warn")
            return redirect(request.referrer or url_for("dashboard"))
        conn.close()
        flash(f"Re-evaluated {stats['postings']} postings: {stats['workable']} workable, "
              f"{stats['excluded']} excluded and still listed.", "ok")
        return redirect(request.referrer or url_for("postings"))

    @app.route("/health")
    def health():
        cfg = load_config()
        status = db_mod.check(cfg.db_path)
        return (json.dumps(status), 200 if status.get("ok") else 503,
                {"Content-Type": "application/json"})

    return app


app = create_app()
