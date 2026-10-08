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
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import (Flask, abort, flash, redirect, render_template, request,
                   url_for)

from .. import config as config_mod
from .. import configstore
from .. import facets
from .. import insights as insights_mod
from .. import progress as progress_mod
from ..digest import outbox
from .. import triage as triage_mod
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

    @app.context_processor
    def running_banner():
        """A run in progress, surfaced on every page.

        Somebody who starts a run and navigates away should not have to remember
        where they left it.
        """
        try:
            cfg = config_mod.load(ROOT, str(CONFIG_DIR))
            conn = db_mod.connect(cfg.db_path)
            active = progress_mod.latest_running(conn)
            conn.close()
        except Exception:
            active = None
        return {"active_run": active}

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
        # Which platforms this build can actually speak to, and which configured
        # sources it cannot. A stale container is otherwise invisible: its Run Now
        # writes errors that read like failures at the employer's end.
        configured = [r[0] for r in conn.execute(
            """SELECT DISTINCT platform FROM source
               WHERE enabled=1 AND verified_on IS NOT NULL""")]
        build = {
            "adapters": sorted(run_mod.ADAPTERS),
            "missing": sorted(p for p in configured if p not in run_mod.ADAPTERS),
            "version": __import__("vedetta").__version__,
        }
        conn.close()
        return render_template("dashboard.html", last=last, polls=polls,
                               counts=counts, unwatched=unwatched, cfg=cfg,
                               build=build)

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
                               view=view, profile_on=cfg.profile.configured,
                               saved_views=cfg.saved_views,
                               stages=triage_mod.STAGES, quick=triage_mod.QUICK,
                               current_query=request.query_string.decode("utf-8"))

    @app.post("/postings/<int:posting_id>/triage")
    def triage(posting_id: int):
        cfg = load_config()
        conn = open_db(cfg)
        state = request.form.get("state")
        note = (request.form.get("note") or "").strip() or None
        if state == "clear":
            triage_mod.clear(conn, posting_id)
        elif triage_mod.is_valid(state):
            triage_mod.set_stage(conn, posting_id, state, note)
        else:
            conn.close()
            abort(400)
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
        """Start a run in the background and send the reader to watch it.

        A run takes anything from a second to an hour, so blocking the request on it
        was never going to work: the browser sat on a white page with no way to tell a
        slow run from a dead one. It now returns immediately and the progress page
        answers "how is it going" from the database.
        """
        cfg = load_config()
        conn = open_db(cfg)
        config_mod.sync_watchlist(conn, cfg.watchlist)
        conn.close()

        lock_path = Path(cfg.db_path).parent / "run.lock"
        started: dict = {}
        ready = threading.Event()

        def work():
            # Its own connection: SQLite objects do not cross threads, and the
            # progress reader needs to get in while this is working.
            inner = db_mod.connect(cfg.db_path)
            try:
                with acquire(lock_path, owner="web-ui"):
                    run_id = run_mod.start_run(inner, "manual", False)
                    started["run_id"] = run_id
                    ready.set()
                    reporter = progress_mod.Reporter(cfg.db_path, run_id)
                    try:
                        run_mod.execute_in(inner, cfg, run_id, reporter=reporter)
                    except Exception as exc:
                        # Recorded on the run, not only in a log: a run that died has
                        # to say so on the page the reader is already watching.
                        reporter.error(f"{type(exc).__name__}: {exc}")
                        run_mod.finish_run(inner, run_id, "failed",
                                           f"{type(exc).__name__}: {exc}")
            except RunInProgress as exc:
                started["busy"] = str(exc)
                ready.set()
            finally:
                inner.close()
                ready.set()

        threading.Thread(target=work, daemon=True, name="vedetta-run").start()
        # Waited on briefly so the redirect can name the run. If the lock is held the
        # thread says so and this returns just as fast.
        ready.wait(timeout=10)

        if started.get("busy"):
            flash(started["busy"], "warn")
            return redirect(url_for("dashboard"))
        run_id = started.get("run_id")
        if run_id is None:
            flash("The run was started but has not reported in yet. The progress page "
                  "will show it once it does.", "warn")
            return redirect(url_for("dashboard"))
        return redirect(url_for("run_progress", run_id=run_id))

    @app.route("/runs/<int:run_id>")
    def run_progress(run_id: int):
        cfg = load_config()
        conn = open_db(cfg)
        snap = progress_mod.snapshot(conn, run_id)
        conn.close()
        if snap is None:
            abort(404)
        # Whether this run's digest is still waiting to go out. A run started from
        # here queues the digest; the scheduled run delivers it, because the mail
        # transport belongs to the host and not to this container. Worth saying on
        # the page rather than leaving the reader to wonder where the email went.
        queued = any(item.run_id == run_id
                     for item in outbox.pending(cfg.db_path))
        return render_template("run.html", snap=snap, queued=queued)

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

    @app.post("/views")
    def save_view():
        """Append a named view to settings.yaml.

        Written into the same file a person edits, through the same validate-and-back-up
        path as the editor: saved views are configuration, not a second store
        (ADR-0016). A structured write keeps the file's comments, which is the only
        reason editing it by hand stays pleasant.
        """
        name = (request.form.get("name") or "").strip()
        query = (request.form.get("query") or "").strip()
        if not name:
            flash("A view needs a name.", "error")
            return redirect(request.referrer or url_for("postings"))

        def mutate(doc):
            views = doc.setdefault("saved_views", [])
            for existing in views:
                if str(existing.get("name", "")).strip().lower() == name.lower():
                    existing["query"] = query
                    return
            views.append({"name": name, "query": query})

        try:
            configstore.patch(CONFIG_DIR, "settings", mutate, None)
        except (configstore.ConfigError, configstore.ConflictError) as exc:
            flash(f"Not saved: {exc}", "error")
            return redirect(request.referrer or url_for("postings"))
        flash(f"Saved the view “{name}”. It is in settings.yaml, so you can edit or "
              f"reorder it there too.", "ok")
        return redirect(url_for("postings", **request.args.to_dict(flat=False)))

    @app.post("/views/delete")
    def delete_view():
        name = (request.form.get("name") or "").strip()

        def mutate(doc):
            views = doc.get("saved_views") or []
            doc["saved_views"] = [
                v for v in views
                if str(v.get("name", "")).strip().lower() != name.lower()]

        try:
            configstore.patch(CONFIG_DIR, "settings", mutate, None)
        except (configstore.ConfigError, configstore.ConflictError) as exc:
            flash(f"Not removed: {exc}", "error")
            return redirect(request.referrer or url_for("postings"))
        flash(f"Removed the view “{name}”.", "ok")
        return redirect(url_for("postings"))

    @app.route("/insights")
    def insights():
        """Signals the posting list cannot show.

        Everything here is a query over data already collected - no source is
        contacted - and nothing here hides or re-scores a posting. It is context for
        a human, which is the posture of the whole project.
        """
        cfg = load_config()
        conn = open_db(cfg)
        weeks = max(1, min(int(request.args.get("weeks", 8) or 8), 52))
        data = insights_mod.summary(conn, weeks=weeks)
        data["pipeline"] = triage_mod.pipeline(conn)
        data["in_flight"] = triage_mod.in_flight(conn)
        conn.close()
        return render_template("insights.html", data=data, weeks=weeks)

    @app.route("/health")
    def health():
        cfg = load_config()
        status = db_mod.check(cfg.db_path)
        return (json.dumps(status), 200 if status.get("ok") else 503,
                {"Content-Type": "application/json"})

    return app


app = create_app()
