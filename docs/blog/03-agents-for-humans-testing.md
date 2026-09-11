# Testing an Agents for Humans entry without ever calling a model

*114 tests, no network, four seconds — and the three bugs they caught.*

---

There is a tempting way to test an agent: ask it a question and have another
model judge the answer. I think that is usually the wrong first move, and for my
entry to the AWS **Agents for Humans** hackathon I did not do it at all.

Compass is a background agent that watches a university's degree rules and
interrupts a student only when staying quiet would cost her something
irreversible. The interesting behaviour is not "did the LLM say something
sensible". It is:

> Given a report, does Compass do **exactly and only** what the policy
> authorised?

That is a property of my code, and it is testable without a model in the loop.

## The seam

The whole suite rests on one method signature:

```python
def sweep(self, findings: list[Finding] | None = None) -> Sweep:
    """Run one full pass: observe, judge, and act on what needs no asking."""
    today = SchoolStore(self.data_dir).today

    if findings is None:
        with agent_tools(use_mcp=self.use_mcp, data_dir=self.data_dir) as tools:
            findings = scan(build_sentinel(self.model, tools))

    sweep = Sweep(today=today, decisions=decide_all(findings, today))
    for decision in sweep.auto_acted:
        receipts = self.execute(decision)
    return sweep
```

`findings=None` means "go ask the model". Passing a list means "here is what the
model said". Every test passes a list.

That single seam is worth more than any amount of model-judging infrastructure,
because it lets me assert on the thing that actually matters:

```python
def test_a_surfaced_finding_changes_nothing_at_all(compass, store, data_dir):
    sweep = compass.sweep(findings=[finding()])

    assert [d.verdict for d in sweep.decisions] == [Verdict.SURFACE]
    assert sweep.receipts == []
    assert receipts_in(data_dir) == []
    assert store.student.active_holds, "the hold must still be there"
```

That is the most important assertion in the repository. If a SURFACE verdict
ever produces a side effect, the project's entire premise is gone — an agent
that acts on things it said it would ask about is worse than one that never acts
at all.

And the counterpart, in the same file:

```python
def test_an_unauthorised_action_surfaces_instead_of_running(compass, store, data_dir):
    """The gate's refusal is the safety property; the orchestrator must honour it."""
    spendy = finding(needs_human_choice=False,
                     options=[Option(action="resolve_library_hold",
                                     action_args={"method": "pay_charge"}, ...)])
    sweep = compass.sweep(findings=[spendy])

    assert [d.verdict for d in sweep.decisions] == [Verdict.SURFACE]
    assert store.student.active_holds, "Compass must not have spent her money"
```

That test exists because the model once reported that €45 charge as requiring no
judgement.

## Bug 1: the model was locally reasonable

The scanning agent looked at "three overdue library items, a €45 replacement
charge, and a block that escalates into a financial hold" and reported
`needs_human_choice: false`. Its reasoning was sound on its own terms — the
charge has to be paid eventually, there is one obvious resolution, so there is
nothing for the student to decide.

It is wrong, and it is wrong in exactly the way this project exists to prevent.
There *is* another way to get the same outcome: return the items in person. That
trades her money against her time, and that trade is hers.

This is not a prompt bug. It is a **design** bug that the prompt bug exposed.
The model should not have been the authority on whether the student needs to
choose. So the gate stopped trusting the field:

```python
if not finding.needs_human_choice:
    chain = auto_chain(finding)
    if chain is not None and set(chain) <= AUTO_ACT_PERMITTED:
        return GateDecision(verdict=Verdict.AUTO_ACT, ...)
    # The report claims no judgement is needed, but the resolution is not one
    # Compass is authorised to carry out alone. When those two disagree, the
    # cautious reading wins: asking costs three seconds, guessing costs the
    # student something she cannot get back.
    declined = "..."
```

The test above is the regression test, and it is written in terms of money
rather than rule codes, because money is the thing the test is protecting.

## Bug 2: the model split one problem into three

One root cause — a withdrawn prerequisite waiver — produced three findings,
because each *symptom* looked like a finding. The student would have got three
cards about one problem, which is the failure mode this project exists to
avoid.

The prompt fix was a worked example rather than another adjective:

> A finding whose only symptom is a date, whose cause you have already reported,
> is the same finding wearing a hat.

There is no unit test for a prompt in the ordinary sense, but there is a
*property* test: the three scenarios each produce exactly one finding. That is
checkable end-to-end and it is in the suite.

## Bug 3: not a prompt bug at all

The sweep reported a library hold as outstanding *after* it had been cleared.
That looked like a reasoning failure and was actually a caching bug in my code.

`SchoolStore` cached the course catalogue at construction. But the agent's tools
run in a **different process** — the MCP server is a subprocess — so a cached
list goes stale the moment either side takes a seat. Removing the cache fixed
it, and broke the write path, because a de-cached `store.course(code)` hands
back a fresh object that nobody persists:

```python
# silently does nothing
course = store.course(code)
course.enrolled += 1
store.save_courses()
```

`save_courses()` wrote the *unchanged* list back to disk. It looks right, it
passes review, and the test that caught it asserted on the value:

```python
def test_a_successful_registration_really_takes_a_seat(store, data_dir):
    before = store.course("ECON10790").enrolled
    actions.register_modules(["ECON10790"])
    assert store.course(code).enrolled == before + 1      # observed 47 == 47
```

Both call sites now go through one atomic read-modify-write:

```python
def take_seat(self, code: str, delta: int) -> Course | None:
    courses = self.courses
    target = next((c for c in courses if c.code == code.strip().upper()), None)
    if target is None:
        return None
    target.enrolled = max(target.enrolled + delta, 0)
    self._write_atomic("courses", [c.model_dump(mode="json") for c in courses])
    return target
```

The lesson generalises: **if the thing you are mutating is returned by a getter
that constructs a new object, you are not mutating the thing.** Make the store
own one method per mutation and there is only one place for it to be wrong.

## The test that no local test can be

The deployment bundle introduced a class of bug that is invisible in your own
repository, because there the package is already importable. The MCP server runs
as a subprocess, and **a child process inherits the environment, not the
parent's `sys.path`**:

```python
args=["-m", "compass.tools.school_mcp_server"]
```

So patching `sys.path` alone passes 113 local tests and fails on the first real
invocation. The fix is to export `PYTHONPATH` too. So I built the bundle layout
in `tmp_path` and ran the child in a stripped environment:

```python
@pytest.fixture
def bundle(tmp_path) -> Path:
    """A copy of the repository in the shape AgentCore ships it."""
    root = tmp_path / "bundle"
    root.mkdir()
    for name in ("app", "src", "data"):
        shutil.copytree(REPO / name, root / name)
    return root
```

And then I did the thing I should do to every test that claims to catch
something: **I deleted the fix and checked that the test failed.**

It didn't.

```
TOOLS OK 13   <-- with the PYTHONPATH export removed
```

The child process starts with normal `site` processing, and an editable install
of `compass` in my checkout lives in a `.pth` file inside `site-packages` — so
the import resolves through the editable install whether or not the environment
variable was ever set. My stripped environment wasn't stripped; it was just
differently furnished. The test passed for a reason that had nothing to do with
the thing I was testing.

The failure mode is worth naming precisely. An integration test can only
distinguish "fixed" from "broken" if the broken version is genuinely reachable
in the test's environment. On a developer machine, an editable install makes
"the package is importable" true by default, so the test is measuring the
developer machine. It would have gone on passing forever, and it would have been
cited in the README as proof.

The fix was to stop testing the integration and assert the invariant where it
lives:

```python
entries = json.loads(line).split(os.pathsep)
assert str(bundle / "src") in entries, (
    "the entrypoint did not put the bundle's src on PYTHONPATH, so the MCP "
    "server it spawns as a subprocess will not be able to import compass"
)
```

That assertion fails when the fix is removed. The integration check is still
there, but it is labelled a smoke test and no longer claims to guard anything.

That is the general shape I would recommend, and it has two halves. **Whenever
production differs from development by more than configuration, build the
production arrangement in `tmp_path` and run it.** And then: **delete the fix
and watch the test fail.** If it doesn't, you have written a test that describes
your laptop.

## The fixtures that keep the suite honest

Two, and both came from being annoyed at flaky results.

**A fresh dataset per test.** Never the checked-in `data/`. A test that reads
whatever is on disk is testing the last time someone ran the demo. Generating
the dataset is deterministic, so this costs nothing:

```python
@pytest.fixture
def data_dir(tmp_path, monkeypatch) -> Path:
    target = tmp_path / "data"
    target.mkdir()
    write_all(target)
    monkeypatch.setenv("COMPASS_DATA_DIR", str(target))
    reset_store()
    yield target
    reset_store()
```

**Credentials stripped from the environment.** An autouse fixture removes
`AWS_PROFILE`, `COMPASS_PROVIDER` and friends and points `HOME` at a temp
directory:

```python
@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch, tmp_path_factory):
    """Keep the model factory from reaching for whatever is on this laptop."""
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_PROFILE",
                 "AWS_DEFAULT_PROFILE", "COMPASS_PROVIDER", "COMPASS_MODEL_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path_factory.mktemp("home")))
```

A suite whose behaviour depends on whose machine it runs on is not a suite. My
model factory falls back to Bedrock when it sees AWS credentials — which is
correct in production and catastrophic in a test run on my laptop, where I
happen to be logged in.

## Where a model *is* in the loop

It is, obviously — Compass is an agent. The point is that the model lives behind
one testable seam and everything downstream of it is deterministic:

```python
today = SchoolStore(self.data_dir).today
findings = scan(build_sentinel(self.model, tools))     # ← the only model call
sweep = Sweep(today=today, decisions=decide_all(findings, today))
```

`decide_all` is a pure function. Same findings, same date, same verdicts. That
is what makes the recorded demo and the test suite the same artefact instead of
two things that happen to look alike — and it is why I can say "it stays quiet
by default" as a property rather than a hope.

## What I'd take to the next agent

**Find the seam where the model stops and your code starts, and put your test
suite entirely on the far side of it.** For Compass that is `Finding`.

**Assert on consequences, not on decisions.** "No receipt was written" and "her
money was not spent" are properties. "The verdict was SURFACE" is an
implementation detail that will change.

**Write the regression test in the user's units.** The test that guards the €45
bug asserts `store.student.active_holds`, not a rule code, because money is what
is actually being protected.

**Build the production layout in `tmp_path`.** The bug with no local reproducer
is the one that ships.

**And strip the environment.** The most reliable way to make a test suite lie to
you is to let it inherit whatever the developer's laptop happens to have.

---

*Compass is a Python + Strands Agents SDK project with 114 tests, no network, and
a four-second suite. Source, tests and the architecture write-up are in the
repository.*
