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
* will the **MCP subprocess** be able to import it — a child process inherits
  the environment, not the parent's ``sys.path``.

The second question is asked of the *environment the entrypoint builds*, not of
the integration. That is not a stylistic choice: the integration check passes
even with the fix deleted, because the child starts with normal ``site``
processing and an editable install resolves the import regardless. See
``test_the_entrypoint_hands_the_package_to_its_subprocesses``.
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

# The dependencies, and nothing else. Running the child with `-S` stops Python
# from processing the `site-packages` directory, which is what makes this a
# clean room: an editable install of `compass` in this checkout lives in a `.pth`
# file *inside* site-packages, and `.pth` files are only executed for site
# directories — never for a `PYTHONPATH` entry. So the child can import strands,
# mcp and pydantic, and still has no route to `compass` except the one the
# entrypoint sets up, which is exactly the situation in the deployed container.
SITE_PACKAGES = Path(
    __import__("sysconfig").get_paths()["purelib"]
)

# mcp's Windows stdio path imports pywintypes, and pywin32 exposes it through
# a .pth file — which `-S` exists to skip. Adding the same directories the
# .pth names restores parity with a real (site-processing) container without
# putting `compass` on the child's path, which is the property the clean room
# exists to protect.
PYWIN32_PATH_ENTRIES = (
    [str(SITE_PACKAGES / d) for d in ("win32", "win32/lib", "pywin32_system32")]
    if sys.platform == "win32"
    else []
)


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
    # The DLLs behind pywintypes load via PATH on Windows (see
    # PYWIN32_PATH_ENTRIES above).
    path = os.environ.get("PATH", "")
    if sys.platform == "win32":
        path += os.pathsep + str(SITE_PACKAGES / "pywin32_system32")

    env = {
        "PATH": path,
        "HOME": os.environ.get("HOME", ""),
        "COMPASS_SCRATCH_DIR": str(bundle / "scratch"),
        # The dependencies, but no route to `compass`. See SITE_PACKAGES above.
        "PYTHONPATH": os.pathsep.join(
            [str(SITE_PACKAGES)] + PYWIN32_PATH_ENTRIES
        ),
        # Windows cannot initialise sockets — and therefore any subprocess
        # transport — without SystemRoot, and tempfile wants its tmp pair.
        # On a non-POSIX dev machine the clean room fails on their absence
        # for reasons that have nothing to do with the bundle layout.
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "TEMP": os.environ.get("TEMP", ""),
        "TMP": os.environ.get("TMP", ""),
    }
    return subprocess.run(
        [sys.executable, "-S", "-c", textwrap.dedent(source)],
        cwd=bundle, env=env, capture_output=True, text=True, timeout=120,
    )


def test_the_clean_room_is_actually_clean(bundle):
    """Guard the guard.

    If `compass` were importable in this environment without the entrypoint's
    path setup — which is what an editable install would do — then the
    subprocess test below would pass whether or not the bug was fixed, and would
    be worth nothing. This asserts the premise the other tests rest on.
    """
    result = run_in_bundle(bundle, "import compass")

    assert result.returncode != 0, (
        "compass is importable inside the bundle with no path setup, so the "
        "tests in this file cannot tell a fixed deployment from a broken one"
    )
    assert "ModuleNotFoundError" in result.stderr


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


def test_the_entrypoint_hands_the_package_to_its_subprocesses(bundle):
    """The regression guard, asserted directly.

    This is the load-bearing test in the file. The fix it protects is one
    environment variable, and no amount of integration testing can see it on a
    developer machine: the MCP server is spawned as `python -m ...`, and because
    *it* starts with the normal `site` machinery, an editable install of
    `compass` in the developer's checkout resolves the import whether or not the
    variable was ever set. The clean room in `run_in_bundle` covers the process
    the entrypoint runs in, not the one it spawns.

    So the invariant is checked where it lives: after importing the entrypoint,
    `PYTHONPATH` must name the bundle's own `src`, because that is the only
    thing the subprocess will inherit.
    """
    result = run_in_bundle(bundle, LOAD + """
    import json, os
    print("PYTHONPATH", json.dumps(os.environ.get("PYTHONPATH", "")))
    """)

    assert result.returncode == 0, result.stderr
    line = next(l for l in result.stdout.splitlines() if l.startswith("PYTHONPATH "))
    entries = json.loads(line.removeprefix("PYTHONPATH ")).split(os.pathsep)

    assert str(bundle / "src") in entries, (
        "the entrypoint did not put the bundle's src on PYTHONPATH, so the MCP "
        "server it spawns as a subprocess will not be able to import compass"
    )
    # And it must not have thrown away whatever was already there.
    assert str(SITE_PACKAGES) in entries


def test_the_mcp_server_can_be_started_from_the_bundle(bundle):
    """The integration half: the tools really do come up."""
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
