"""Shared fixtures.

The important one is `offline_config`. The example watchlist ships two *verified*
sources, so any test that started a run was quietly reaching out to GitLab and
Grafana Labs over the network: slow, flaky on a train, and rude to two companies who
never asked to host a test suite. It also made the run report itself as seeding,
which hid the very behaviour one of those tests was there to check.
"""
from __future__ import annotations

import os
import shutil

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, "config")

# One employer, one source, deliberately without verified_on: stored, never polled.
# A run against this configuration does everything a real run does except talk to
# anybody.
UNVERIFIED_WATCHLIST = """employers:
  - key: example-corp
    display_name: Example Corp
    channel: private
    careers_url: https://example.invalid/careers
    sources:
      - platform: greenhouse
        identifier: examplecorp
        discovered_by: manifest
"""


@pytest.fixture()
def offline_config(tmp_path):
    """A configuration directory whose sources are all unverified."""
    directory = tmp_path / "config"
    directory.mkdir()
    for name in ("profile", "rules", "settings"):
        shutil.copy(os.path.join(EXAMPLES, f"{name}.example.yaml"),
                    directory / f"{name}.example.yaml")
    (directory / "watchlist.yaml").write_text(UNVERIFIED_WATCHLIST, encoding="utf-8")
    return str(directory)
