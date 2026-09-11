# Deploying an Agents for Humans entry to AgentCore Runtime: the bug no local test could find

*`sys.path` does not cross a process boundary, and that cost me an afternoon.*

---

My entry for the AWS **Agents for Humans** hackathon, Compass, runs entirely
locally during development. There is no AWS dependency in the data layer, the
tools, the agents or the orchestrator — the Strands Agents SDK is model-agnostic,
so the same code runs against a cheap OpenAI-compatible endpoint on my laptop
and against Amazon Bedrock in the cloud.

That was deliberate. It meant I could build the whole thing without waiting on
credentials, and it meant that when I finally ran `agentcore deploy`, the only
new variable was the platform.

The platform, it turned out, had one bug waiting for me that **108 passing local
tests could not see**. This post is about that bug, because I think it is
general to any Strands agent that talks to an MCP server on stdio.

## The setup

Compass's school data is exposed through a FastMCP server over stdio, and the
agent consumes it through `MCPClient`:

```python
client = MCPClient(lambda: stdio_client(StdioServerParameters(
    command=sys.executable,
    args=["-m", "compass.tools.school_mcp_server"],
    env=env,
)))
with client:
    yield client.list_tools_sync() + list(ANALYSIS_TOOLS)
```

Note `command=sys.executable` and `args=["-m", "compass.tools.school_mcp_server"]`.
The server is a **child process** running the same package.

There is also a `use_mcp=False` path used by the test suite, which hands the
agent the same functions as in-process `@tool`s — both transports decorate the
same function objects, so the fallback is genuinely the same capabilities rather
than a second implementation that can rot.

## The packaging decision

AgentCore packages a directory (`codeLocation`) and runs an `entrypoint` inside
it. The scaffolded project the CLI generates looks like this:

```
agentcore.json          → codeLocation: "app/Compass/"
app/Compass/main.py     → entrypoint: "main.py"
app/Compass/pyproject.toml
```

That is the right shape for a *self-contained* agent, and it is not the shape I
wanted. I already had `src/compass/` as an installable package with a test
suite, and I was not going to copy it into `app/Compass/` so it could fall out
of date in a directory nobody runs tests in.

So I pointed the runtime at the repository root:

```jsonc
{
  "name": "Compass",
  "build": "CodeZip",
  "entrypoint": "app/Compass/main.py",
  "codeLocation": "./",
  "runtimeVersion": "PYTHON_3_14",
  "networkMode": "PUBLIC",
  "protocol": "HTTP"
}
```

`agentcore package` then builds from the root, and I verified the result rather
than trusting it:

```bash
$ unzip -l agentcore/Compass.zip | grep -E " (app|src|data)/"
   8890  app/Compass/main.py
   ...   src/compass/*.py            (20 files)
   1830  data/announcements.json
   ...   data/*.json                 (6 files)
```

`src/`, `data/` and `app/` arrive as siblings. Good.

## The bug

Inside the bundle, the package is not installed. So the entrypoint puts it on
the path:

```python
_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
if _SRC.is_dir():
    sys.path.insert(0, str(_SRC))

from compass.agents.compass import Compass     # works
```

That import succeeds, and every local test passes. It is also **half a fix**,
because the school-data server is not an import — it is a subprocess:

```python
args=["-m", "compass.tools.school_mcp_server"]
```

A child process inherits the *environment*. It does not inherit the parent's
`sys.path`. So on the first real invocation inside AgentCore, the parent would
import `compass` fine and then spawn a child that dies with
`No module named compass.tools.school_mcp_server`.

Worse, it would die *quietly* in the way that matters. The orchestrator's sweep
already tolerates a failed auto-action — it logs and continues, because the
world can move under an agent — so the visible symptom would have been a sweep
that surfaced fewer cards and a CloudWatch log line nobody reads. A deployed
agent that is subtly less capable than the local one is a worse outcome than one
that fails loudly.

The fix is one line, and it is easy to state once you have found it:

```python
if _SRC.is_dir():
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    # The school-data MCP server runs as a subprocess — `python -m
    # compass.tools.school_mcp_server` — and a child process inherits the
    # environment, not this interpreter's sys.path. Without this line the
    # deployed agent would come up holding tools it cannot start.
    _existing = os.environ.get("PYTHONPATH", "")
    if str(_SRC) not in _existing.split(os.pathsep):
        os.environ["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(_SRC), _existing) if part
        )
```

## The test that would have caught it

The reason this bug is interesting is not that it is subtle. It is that **no
test that runs in your repository can catch it**, because in your repository
the package is already importable. You have to test the *layout*.

So I wrote one that builds it:

```python
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
```

and then asks the two questions that decide whether the deployed agent works:

```python
def test_the_mcp_subprocess_can_import_compass(bundle):
    """The one that would have shipped broken: sys.path does not cross processes."""
    result = run_in_bundle(bundle, LOAD + """
    import json
    from compass.tools.registry import agent_tools
    with agent_tools(use_mcp=True, data_dir=main.data_dir()) as tools:
        print("TOOLS", json.dumps(sorted(t.tool_name for t in tools)))
    """)

    assert result.returncode == 0, result.stderr
    names = set(json.loads(line.removeprefix("TOOLS ")))
    assert {"list_courses", "get_student_record", "get_degree_requirements"} <= names
    assert {"audit_degree_plan", "term_load", "days_from_today"} <= names
```

The stripped environment is the whole trick. No `PYTHONPATH`, no `PYTHONHOME`,
run from inside the bundle — which is exactly the situation the deployed process
is in, and exactly the situation no ordinary test creates.

## The other thing AgentCore does not give you

The runtime has no writable storage, and Compass is a *writing* agent: it takes
seats, clears holds, files plans. The bundle is treated as read-only.

The first invocation of a session copies the shipped dataset somewhere writable:

```python
def data_dir() -> Path:
    scratch = Path(os.environ.get("COMPASS_SCRATCH_DIR", "/tmp/compass-data"))
    if not (scratch / "meta.json").exists():
        scratch.mkdir(parents=True, exist_ok=True)
        for source in SHIPPED_DATA.glob("*.json"):
            shutil.copy2(source, scratch / source.name)
    os.environ["COMPASS_DATA_DIR"] = str(scratch)
    return scratch
```

Within a session the writes are real: registering for a module takes a seat,
dropping it gives the seat back. They end when the session does, which for
fabricated demo data is the correct lifetime — and I have a test asserting that
nothing lands in the bundle directory itself.

## The contract

`POST /invocations` takes three payloads:

```jsonc
{"action": "sweep"}
{"action": "decide", "finding": {...}, "option_id": "return_in_person"}
{"action": "ask", "question": "when is the W deadline?"}
```

The asymmetry between the first two is the design, not an accident. A sweep is
unattended, so it may only run the two bookkeeping actions the policy module
whitelists. A `decide` carries a human's choice, so it executes what was chosen
and the receipt records which option it was.

And every failure comes back as a *value*, because an entrypoint that raises
gives whoever invoked it a 502 and nothing to act on:

```python
def handle(payload: dict, compass: Compass) -> dict:
    try:
        return _dispatch(payload, compass)
    except CompassError as exc:
        return {"ok": False, "kind": "refused", "error": str(exc)}
    except ValueError as exc:
        return {"ok": False, "kind": "bad_request", "error": str(exc)}
```

A *bad request* and a *refusal by the rules* are different things and deserve
different answers. The refusal is a result worth showing the student — it is the
same refusal the registrar would give her.

## What I'd tell you before you deploy

1. **Package from the root if your package is the product.** A second copy of
   `src/` inside the bundle is a copy that falls out of date. But then you own
   the path setup, and you have to do it in both `sys.path` *and* `PYTHONPATH`.
2. **Test the layout, not just the code.** Build the bundle shape in `tmp_path`
   and run the entrypoint in a stripped environment. It is twenty lines and it
   is the only way to see this class of bug.
3. **Assume the filesystem is read-only,** and copy what you need on first use.
4. **Return failures as values.** The runtime's error surfaces are thin; your
   own `{"ok": false, "kind": ...}` is what makes a deployed agent debuggable.
5. **Verify the zip.** `unzip -l` after `agentcore package` takes four seconds
   and tells you whether your data and your package are actually in there.

The whole deployment is a few hundred lines, and the part that took the longest
was the part with no local reproducer.

---

*Compass is a Python + Strands Agents SDK project deployed on Amazon Bedrock
AgentCore Runtime in eu-west-1. Source, tests and the architecture write-up are
in the repository.*
