"""Shared fixtures.

Every test runs against a **freshly generated dataset in a temporary
directory**, never the checked-in ``data/``. Two reasons, and the second one
matters more than the first:

1. Tests that mutate the student record must not leave the demo data dirty.
2. The dataset is the *fixture* for every claim Compass makes. A test that
   reads whatever happens to be on disk is testing the last time someone ran the
   demo, not the system.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from compass.data.generate import DEMO_TODAY, INSTITUTION, write_all  # noqa: E402
from compass.store import SchoolStore  # noqa: E402
from compass.tools.school_tools import reset_store  # noqa: E402


@pytest.fixture
def data_dir(tmp_path, monkeypatch) -> Path:
    """A freshly generated synthetic dataset, isolated from the repo's."""
    target = tmp_path / "data"
    target.mkdir()
    write_all(target)
    monkeypatch.setenv("COMPASS_DATA_DIR", str(target))
    reset_store()
    yield target
    reset_store()


@pytest.fixture
def store(data_dir) -> SchoolStore:
    return SchoolStore(data_dir)


@pytest.fixture
def today():
    return DEMO_TODAY


@pytest.fixture
def institution():
    return INSTITUTION


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch, tmp_path_factory):
    """Keep the model factory from reaching for whatever is on this laptop.

    Nothing in the unit tests builds a model, but ``resolve_provider`` reads
    ``AWS_PROFILE``, ``COMPASS_PROVIDER`` and ``~/.aws/credentials`` — and a
    test suite whose behaviour depends on whose machine it runs on is not a test
    suite. An empty HOME makes the credential-file check fail the same way it
    would on a clean runner.
    """
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_PROFILE",
                 "AWS_DEFAULT_PROFILE", "COMPASS_PROVIDER", "COMPASS_MODEL_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path_factory.mktemp("home")))
