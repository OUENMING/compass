# Deploying an Agents for Humans entry to AgentCore Runtime: the bug no local test could find

*`sys.path` does not cross a process boundary, and that cost me an afternoon.*

---

My entry for the AWS **Agents for Humans** hackathon, Compass, runs entirely
locally during development. There is no AWS dependency in the data layer, the
tools, the agents or the orchestrator — the Strands Agents SDK is model-agnostic,
so the same code runs against a cheap OpenAI-compatible endpoint on my laptop
and against Amazon Bedrock in the cloud. (That last swap is also what saved the
demo when the account turned out to be blocked on the Bedrock data plane — a
provider is an environment variable here, not an architecture.)

That was deliberate. It meant I could build the whole thing without waiting on
credentials, and it meant that when I finally ran `agentcore deploy`, the only
new variable was the platform.

The platform, it turned out, had one bug waiting for me that **the local suite could not
see**. This post is about that bug, because I think it is
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
def test_the_entrypoint_hands_the_package_to_its_subprocesses(bundle):
    """The one that would have shipped broken: sys.path does not cross processes."""
    result = run_in_bundle(bundle, LOAD + """
    import json, os
    print("PYTHONPATH", json.dumps(os.environ.get("PYTHONPATH", "")))
    """)

    assert result.returncode == 0, result.stderr
    line = next(l for l in result.stdout.splitlines() if l.startswith("PYTHONPATH "))
    entries = json.loads(line.removeprefix("PYTHONPATH ")).split(os.pathsep)
    assert str(bundle / "src") in entries


def test_the_mcp_server_can_be_started_from_the_bundle(bundle):
    """The integration half: the tools really do come up."""
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

**And then I deleted the fix, to check the test was worth having.** The
integration one *still passed*. The spawned child starts with normal `site`
processing, and an editable install of `compass` in my checkout resolves the
import through a `.pth` file whether or not the entrypoint exported anything —
so on a developer machine, the integration test is blind to the very bug it
looks like it is guarding.

Only the assertion on the environment variable itself fails when the export is
removed. That is why the first test above asserts the invariant directly and the
second is labelled a smoke test with no claim attached. A test that passes with
the fix deleted is not a test, and I would not have known without deleting the
fix.

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

## The credential the repository must not contain

A deployed agent needs a model credential, and `agentcore.json` is committed. Its
`envVars` are therefore the wrong place for a key — the file is in git, so
anything in it is public.

The runtime's environment variables have exactly two fields, `name` and `value`,
and no reference syntax. So the name of an SSM parameter goes in the committed
file and the value stays in SSM:

```json
{"name": "COMPASS_SECRET_PARAMETER", "value": "/compass/model-api-key"},
{"name": "COMPASS_SECRET_TARGET",    "value": "DEEPSEEK_API_KEY"}
```

with a policy attached to the runtime's execution role granting `ssm:GetParameter`
on that one ARN and nothing else. The entrypoint reads it at cold start:

```python
def _load_provider_secret() -> None:
    name = os.environ.get("COMPASS_SECRET_PARAMETER", "").strip()
    target = os.environ.get("COMPASS_SECRET_TARGET", "").strip()
    if not (name and target) or os.environ.get(target):
        return
    value = boto3.client("ssm").get_parameter(
        Name=name, WithDecryption=True
    )["Parameter"]["Value"]
    os.environ[target] = value
```

Two details in that function are doing work. It is **idempotent and a no-op when
the variable is already set**, so the local demo, the CLI and the test suite
never reach AWS on account of it — which matters because `invoke` rebuilds the
agent on every call. And the value lands in the process environment, which is
exactly where the model factory already looked, so nothing downstream had to
change.

The first version of this deployment shipped without `openai` in
`pyproject.toml` — the package the OpenAI-compatible backend needs. The invoke
came back `ModuleNotFoundError: No module named 'openai'`, which was the good
news: it meant the SSM read had already worked, and the only thing wrong was a
missing line in the dependency list. **A deployed agent's dependencies are
whatever the bundler resolves from your manifest, not whatever is in your
virtualenv.**

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
