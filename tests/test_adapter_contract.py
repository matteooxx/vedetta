"""The adapter contract, checked for every entry in ``run.ADAPTERS``.

``Adapter.fetch`` is not abstract: it raises NotImplementedError and nothing checks
that a subclass keeps the signature. A badly spelt parameter would only break at
runtime, on a real source. Parametrising over ``ADAPTERS`` itself means a new adapter
joins this test the moment it joins the dictionary.
"""
from __future__ import annotations

import inspect

import pytest

from vedetta.run import ADAPTERS

REQUIRED = ("source", "known_keys", "detail_budget", "progress")


@pytest.mark.parametrize("key,cls", sorted(ADAPTERS.items()))
def test_the_registry_key_is_the_adapters_platform(key, cls):
    assert key == cls.platform


@pytest.mark.parametrize("key,cls", sorted(ADAPTERS.items()))
def test_fetch_accepts_the_four_arguments_the_runner_passes(key, cls):
    params = inspect.signature(cls.fetch).parameters
    missing = [name for name in REQUIRED if name not in params]
    assert not missing, f"{cls.__name__}.fetch lacks {missing}; has {list(params)}"


@pytest.mark.parametrize("key,cls", sorted(ADAPTERS.items()))
def test_an_adapter_is_built_with_no_arguments(key, cls):
    """run.py and web/app.py both call ``adapter_cls()``."""
    assert cls() is not None


@pytest.mark.parametrize("key,cls", sorted(ADAPTERS.items()))
def test_params_is_a_frozenset_of_names(key, cls):
    """configstore validates the watchlist against it, per platform."""
    assert isinstance(cls.params, frozenset)
    assert all(isinstance(name, str) and name for name in cls.params)


def test_run_uses_the_registry_itself_not_a_copy():
    """The registry lives in ``vedetta.adapters``; run.py, web/app.py and the tests
    reach it as ``run.ADAPTERS``. Tests replace entries in that dictionary with
    ``monkeypatch.setitem``. Were ``run.ADAPTERS`` a copy, those tests would keep
    passing while patching a dictionary ``poll`` never reads."""
    from vedetta import adapters, configstore, run
    assert run.ADAPTERS is adapters.ADAPTERS
    assert configstore.ADAPTERS is adapters.ADAPTERS
