"""The deployment bundle's layout — the failure mode no unit test would catch.

AgentCore packages `codeLocation` and runs `entrypoint` inside it. Compass is
packaged from the repository root so that `src/`, `data/` and `app/` all arrive
as siblings; the entrypoint then puts `src/` on the path and copies the shipped
dataset somewhere writable.

Every one of those steps is invisible locally, because locally the package is
already importable and the dataset already exists. So this test builds the
bundle layout in a temporary directory, strips the environment down to what a
fresh container would have, and asks the two questions that decide whether the
deployed agent works at all:

* can the entrypoint find the package and the data when it is not installed, and
* can the **MCP subprocess** import it too — a child process inherits the
  environment, not the parent's ``sys.path``, so a fix that only patches
  ``sys.path`` passes every local test and fails on the first invocation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def bundle(tmp_path) -> Path:
    """A copy of the repository in the shape AgentCore ships it."""
    root = tmp_path / "bundle"
    root.mkdir()
    for name in ("app", "src", "data"):
        shutil.copytree(REPO / name, root / name,
                        ignore=shutil.ignore_patterns("__pycache__"))
    return root


def run_in_bundle(bundle: Path, source: str) -> subprocess.CompletedProcess:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "COMPASS_SCRATCH_DIR": str(bundle / "scratch"),
        # No PYTHONPATH and no PYTHONHOME: the bundle has to fend for itself.
    }
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(source)],
        cwd=bundle, env=env, capture_output=True, text=True, timeout=120,
    )


LOAD = """
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location(
        "bundle_main", "app/Compass/main.py")
    main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main)
"""


def test_the_entrypoint_finds_the_package_and_the_dataset(bundle):
    result = run_in_bundle(bundle, LOAD + """
    print("DATA", main.data_dir())
    from compass.store import SchoolStore
    print("TODAY", SchoolStore(main.data_dir()).today)
    """)

    assert result.returncode == 0, result.stderr
    assert "DATA" in result.stdout
    # The dataset is copied out of the read-only bundle into writable scratch.
    assert "TODAY 2026-09-28" in result.stdout


def test_the_mcp_subprocess_can_import_compass(bundle):
    """The one that would have shipped broken: sys.path does not cross processes."""
    result = run_in_bundle(bundle, LOAD + """
    import json
    from compass.tools.registry import agent_tools
    with agent_tools(use_mcp=True, data_dir=main.data_dir()) as tools:
        print("TOOLS", json.dumps(sorted(t.tool_name for t in tools)))
    """)

    assert result.returncode == 0, result.stderr
    line = next(l for l in result.stdout.splitlines() if l.startswith("TOOLS "))
    names = set(json.loads(line.removeprefix("TOOLS ")))

    # The school's data must arrive over the protocol...
    assert {"list_courses", "get_student_record", "get_degree_requirements"} <= names
    # ...and the deterministic analysis must be present regardless, because the
    # gate depends on its exactness and it does not live behind the protocol.
    assert {"audit_degree_plan", "term_load", "days_from_today"} <= names


def test_the_entrypoint_writes_only_inside_scratch(bundle):
    """The bundle directory is treated as read-only, so nothing may land in it."""
    before = sorted(p.name for p in (bundle / "data").iterdir())
    result = run_in_bundle(bundle, LOAD + """
    main.data_dir()   # points COMPASS_DATA_DIR at the writable copy
    from compass.tools.actions import register_modules
    print("REG", register_modules(["ECON10790"]).get("detail", {}).get("modules"))
    """)

    assert result.returncode == 0, result.stderr
    assert "REG ['ECON10790']" in result.stdout
    assert sorted(p.name for p in (bundle / "data").iterdir()) == before

    written = bundle / "scratch" / "student.json"
    assert "ECON10790" in written.read_text(), (
        "the registration has to land in the writable copy, or the deployed "
        "agent forgets every action it takes"
    )
