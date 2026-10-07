"""Configuration loading.

Code holds mechanism; configuration holds the case (ADR-0013). Nothing here knows
anything about a particular person, employer or job market.

Every path is relative to a configurable root and never absolute, so the same tree
runs unchanged wherever it is deployed (ADR-0015).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_DIR = "config"


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _pick(config_dir: Path, name: str) -> Path:
    """Prefer the real file; fall back to the shipped example.

    The fallback is what makes a fresh clone runnable: the repository contains only
    examples, never real data.
    """
    real = config_dir / f"{name}.yaml"
    return real if real.exists() else config_dir / f"{name}.example.yaml"


@dataclass
class Config:
    root: Path
    settings: dict = field(default_factory=dict)
    watchlist: dict = field(default_factory=dict)
    rules: dict = field(default_factory=dict)
    profile_doc: dict = field(default_factory=dict)
    sources_used: dict = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        value = self.settings.get("database", "runtime/vedetta.db")
        path = Path(value)
        return path if path.is_absolute() else self.root / path

    @property
    def profile(self):
        from .profile import Profile
        return Profile.from_dict(self.profile_doc)

    @property
    def transport(self) -> str:
        """`host` (the default) or `smtp`. See settings.example.yaml."""
        value = str((self.settings.get("digest") or {}).get("transport") or "host")
        return value.strip().lower()

    @property
    def saved_views(self) -> list[dict]:
        views = self.settings.get("saved_views") or []
        return [v for v in views if isinstance(v, dict) and (v.get("name") or "").strip()]

    @property
    def digest(self) -> dict:
        return self.settings.get("digest") or {}

    @property
    def techniques(self) -> dict:
        """Which discovery techniques are enabled. All of them, by default.

        Redundancy is the default rather than an option, because every technique
        tried during design failed in a way that looked like success, and their
        failures are uncorrelated (ADR-0012).
        """
        default = {
            "manifest": True, "redirect": True, "markers": True,
            "identifier_extraction": True, "dns": True, "sitemap": True,
            "structured_data": True, "headless_browser": False,
        }
        default.update(self.settings.get("discovery") or {})
        return default

    @property
    def ai_worker(self) -> str | None:
        """Optional external worker (ADR-0014). Absent by default.

        Its absence must never break a run - it degrades the result and is reported.
        """
        return (self.settings.get("ai_worker") or {}).get("url") or os.environ.get("VEDETTA_AI_WORKER")


def load(root: str | Path = ".", config_dir: str | None = None) -> Config:
    root = Path(root).resolve()
    cdir = Path(config_dir) if config_dir else root / DEFAULT_CONFIG_DIR
    picks = {name: _pick(cdir, name)
             for name in ("settings", "watchlist", "rules", "profile")}
    return Config(
        root=root,
        settings=_load(picks["settings"]),
        watchlist=_load(picks["watchlist"]),
        rules=_load(picks["rules"]),
        profile_doc=_load(picks["profile"]),
        sources_used={k: v.name for k, v in picks.items()},
    )


def sync_watchlist(conn, watchlist: dict) -> dict:
    """Push the configured employers and sources into the database.

    A source is written with its ``verified_on`` exactly as configured. A source
    without one is stored but will never be polled -- enrolment stays a human act,
    enforced by the query in run.py rather than by discipline.
    """
    counts = {"employers": 0, "sources": 0, "unverified": 0}
    for entry in watchlist.get("employers") or []:
        key = entry.get("key")
        if not key:
            continue
        conn.execute(
            """INSERT INTO employer (key, display_name, channel, homepage, careers_url, enabled, notes)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(key) DO UPDATE SET
                 display_name=excluded.display_name, channel=excluded.channel,
                 homepage=excluded.homepage, careers_url=excluded.careers_url,
                 enabled=excluded.enabled, notes=excluded.notes""",
            (
                key,
                entry.get("display_name") or key,
                entry.get("channel") or "default",
                entry.get("homepage"),
                entry.get("careers_url"),
                int(entry.get("enabled", True)),
                entry.get("notes"),
            ),
        )
        employer_id = conn.execute("SELECT id FROM employer WHERE key=?", (key,)).fetchone()[0]
        counts["employers"] += 1

        for source in entry.get("sources") or []:
            platform = source.get("platform")
            identifier = source.get("identifier")
            if not platform or not identifier:
                continue
            verified = source.get("verified_on")
            if not verified:
                counts["unverified"] += 1
            conn.execute(
                """INSERT INTO source (employer_id, platform, identifier, endpoint,
                        job_url_pattern, job_url_exclude, discovered_by, verified_on,
                        verified_note, enabled)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(employer_id, platform, identifier) DO UPDATE SET
                     endpoint=excluded.endpoint,
                     job_url_pattern=excluded.job_url_pattern,
                     job_url_exclude=excluded.job_url_exclude,
                     verified_on=excluded.verified_on,
                     verified_note=excluded.verified_note,
                     enabled=excluded.enabled""",
                (
                    employer_id, platform, str(identifier), source.get("endpoint"),
                    source.get("job_url_pattern"), source.get("job_url_exclude"),
                    source.get("discovered_by") or "config",
                    str(verified) if verified else None,
                    source.get("verified_note"), int(source.get("enabled", True)),
                ),
            )
            counts["sources"] += 1
    conn.commit()
    return counts
