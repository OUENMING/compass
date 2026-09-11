# Compass

**The missing manual for the students nobody handed a manual to.**

Compass is a background agent that reads a university's degree rules the way a
registrar does. It stays completely silent while everything is fine, speaks up
only when staying quiet would cost a student something they cannot get back —
and then does the thing rather than describing it.

Built for the **AWS Agents for Humans** hackathon, Good Neighbor track.

![Compass architecture](docs/architecture.png)

[Architecture](ARCHITECTURE.md) · [Devpost copy](docs/DEVPOST.md) ·
[Demo video script](docs/VIDEO.md) · [Write-ups](docs/blog/)

---

## 1. The problem

A university runs on rules that were never written down *for students*.

Prerequisite chains that do not bite until two semesters later. A library fine
that quietly escalates into a registration block. A rule change buried on a
handbook page instead of sent to an inbox. A degree plan that has to be approved
before a registration window opens, in an order nobody explains.

None of this is a secret. It is all technically published. But it is published
the way a legal code is published — complete, unindexed, and written for the
people administering it.

The students who get caught are not the ones struggling academically. They are
the ones with nobody at home who has already navigated a university. First-
generation students. International students, who are also navigating a visa
calendar on top of a term calendar. That is the entire audience of this project,
and it is why the demo student is one of them.

**What exists today is built for the institution, not the student.** EAB,
Stellic, Ellucian and Druid all sell to the registrar's office: analytics,
degree-audit tooling, retention dashboards. A 2026 survey of the category
noted plainly that there is still no student-facing agent. The student is the
subject of these systems, never the user of one.

## 2. What Compass does

Compass watches one student's situation against the rules and produces exactly
three kinds of outcome. It runs against a synthetic dataset with three scenarios
already in it.

| Scenario | What is actually happening | What Compass does |
|---|---|---|
| **The withdrawn waiver** | A rule that let her take *Econometrics I* without *Quantitative Methods* has been withdrawn. The announcement went to a handbook page, not to students. The module she wants next year now sits behind one she was told she did not need. | Surfaces a card. There is one route back — take the missing module next term — and a real cost to it, so the choice is hers. |
| **The hold that escalates** | Three overdue Short Loan items. The library block is cheap today and becomes a Fees Office hold on 5 October, which then blocks registration. | Surfaces a card with two real options: return them in person (costs a trip) or authorise the €45 charge (costs money). **Compass never spends her money without asking.** |
| **The duplicate no one checks** | Her degree plan has never been audited and is not on file. It double-counts one module across two requirement groups, and filing is a prerequisite for registration opening. | Handles it silently. The programme's own written rules determine the outcome completely, so asking would be theatre. It repairs the plan, files it, and leaves a receipt. |

And a fourth outcome, which is the point of the whole design: **nothing at
all.** Most of what Compass finds, it deliberately passes over, and it can tell
you why for every single one (§4).

## 3. How it is built

```
data/*.json            synthetic dataset — 26 modules, prerequisite graph,
                       degree requirements, one student, calendar, notices
      │
      ▼
FastMCP school server  stdio; the school's data behind a protocol boundary
      │  (Strands MCPClient)
      ▼
Pathfinder             prerequisite chains, degree gaps, "can this still be closed?"
Sentinel               ★ scans deadlines → structured judgements about consequence
Explainer              what a hold / W-deadline / double-count rule actually means
      │  agents-as-tools, orchestrated by
      ▼
Compass (orchestrator) observe → judge → act
      │
      ▼
gate.py                ★ SIX DETERMINISTIC RULES — the only path to her attention
      │
      ▼
actions.py             real side effects + confirmation numbers + receipts
      │
      ▼
Decision card          FastAPI + SSE · silent → card → click → executed → receipt
      │
      ▼
AgentCore Runtime      eu-west-1, CodeZip
```

The two starred components are the ones that matter, and they are described
below. Everything else is plumbing that any competent agent has.

## 4. Why this is different: silence is a decision, not an absence

Ask a model *is this important?* and it will say yes. It will say yes about
almost everything, because "somewhat important" is always defensible. So every
notification system built this way becomes noise, and a student who has learned
to ignore her agent is **worse off than one with no agent at all** — she has
also lost the worry that would have made her check.

Compass never asks a model whether to speak.

The model establishes **facts** about a situation — what changed, what it costs,
when the last safe moment is, how confident it is. That arrives as a `Finding`.
The decision to interrupt is then made by the plain Python in
[`src/compass/gate.py`](src/compass/gate.py), in a fixed order:

| Rule | Condition | Verdict |
|---|---|---|
| **R1** | Confidence below 0.70 | stay silent — never act on a guess |
| **R2** | The last safe moment has already passed | stay silent — there is no move left to offer |
| **R3** | The consequence is recoverable | stay silent — handle it in the background, speak up if that changes |
| **R4** | Irreversible, and the written rules determine the resolution | **act**, from a whitelist, and leave a receipt |
| **R5** | Irreversible, but more than 45 days out | stay silent — this is a watch, not a decision |
| **R6** | Irreversible, inside the horizon, and the choice is genuinely hers | **surface a card** |

R6 is the only path to the student's attention in the entire system.

Three properties fall out of doing it this way, and each of them is a
deliverable rather than a claim:

- **It is explainable.** Every verdict cites the rule that produced it, in
  language written for the student, and that string is shown on the card. She
  can ask "why am I seeing this?" and get a real answer.
- **It is reproducible.** The same finding on the same date always yields the
  same verdict. The recorded demo and the test suite are therefore testing the
  same thing.
- **It is auditable.** Silence carries a reason too. `GateDecision.reason` is
  populated whether or not anything was shown, so "it did nothing" is
  inspectable rather than indistinguishable from a crash.

### The whitelist

`AUTO_ACT_PERMITTED` in `gate.py` holds **two** actions: repairing a degree plan
and filing one. Both are bookkeeping whose outcome the programme's own written
rules already fix. Everything else — spending money, changing what she studies,
contacting a human — is absent from that list and always will be.

There is a specific failure this prevents, and it is the one the project exists
to avoid. A model can look at a €45 library charge and reason, correctly, that
it has to be paid eventually, and report `needs_human_choice: false` — "no
judgement required". A gate that trusted that field would pay it. Compass does
not trust the field: if the resolution is not on the whitelist, the finding
falls through to R5/R6 and the student is asked. *Asking costs three seconds;
guessing costs her something she cannot get back.*

## 5. Real actions, with receipts

"Not just chat about it" is the spine of this hackathon, so the actions are real
and they validate like the registrar's system would.

Seven actions ship: `register_modules`, `drop_module`, `resolve_library_hold`,
`set_specialisation`, `repair_degree_plan`, `file_degree_plan`,
`notify_advisor`.

Each one **refuses** the way the real system refuses. Registering for
*Econometrics II* while its prerequisite is unpassed returns:

```json
{"error": "ECON30010 requires ECON20030, which the student has not passed. Registration refused."}
```

Registration checks unmet prerequisites, the term ECTS cap, seat availability
and duplicate registration, and validates everything *before* mutating anything
— so a refused registration takes no seat. `file_degree_plan` refuses a plan
that would fail its own audit, which is what makes repair-then-file a forced
sequence rather than a suggestion.

Every action that succeeds writes a receipt with a **deterministic**
confirmation number, derived from the action and its arguments rather than a
random value — so re-running the demo produces the same receipt. The receipts
are the evidence: `data/receipts.jsonl` is an append-only record of everything
Compass did, including the things it did without asking.

## 6. Quickstart

Requires Python 3.12+. Nothing else to install; no AWS account needed to run it
locally.

```bash
git clone https://github.com/OUENMING/compass && cd compass
uv venv && uv pip install -e ".[web,dev]"

python -m compass.data.generate      # write the synthetic dataset
python -m compass.agents.compass     # one full sweep on the command line
uvicorn web.app:app                  # or the decision card → localhost:8000
```

A model backend is required for the sweep. Compass is deliberately
model-agnostic and picks one up from its environment:

```bash
export COMPASS_PROVIDER=deepseek DEEPSEEK_API_KEY=...   # or openai, or bedrock
python -m compass.agents.compass
```

Then, on the command line:

```bash
python -m compass.agents.compass                     # sweep, and act on R4
python -m compass.agents.compass --direct-tools      # skip the MCP subprocess
python -m compass.agents.compass --json              # machine-readable verdicts
python -m compass.agents.compass --ask "what happens if I switch specialisation?"
```

Exit code is `10` when something surfaced, so a cron job can tell "nothing to
report" from "she has a decision to make".

## 7. The dataset is fabricated, and that is a design decision

**Every record in `data/` is synthetic.** No real student, no real institution,
no real programme. The university in the demo is *Harbour University Dublin*,
which does not exist.

That is not only a licensing convenience. The scenarios depend on specific rule
readings — a withdrawn waiver, a hold that escalates on a particular date, a
double-count rule — and building them onto a real university's handbook would
mean shipping a document that *asserts things about a real institution's
regulations*. Those assertions would be wrong the moment the institution changed
a rule, and they would be wrong in a way that could mislead a real student.
A fictional institution makes the demo honest: everything in it is true about
the fictional world, and nothing in it is a claim about yours.

`python -m compass.data.generate` is deterministic — generate twice, get
byte-identical files, and the tests assert exactly that. The demo date is fixed
at `2026-09-28` so that every deadline calculation agrees with the calendar on
screen and the recording is repeatable.

## 8. Deploying to AgentCore

The deployed agent is the same agent. `app/Compass/main.py` validates a payload,
calls into `compass.agents.compass`, and serialises the answer; nothing about
Compass's behaviour lives in the entrypoint, so the local demo and the deployed
runtime cannot drift apart.

```bash
agentcore validate
agentcore package                 # → agentcore/Compass.zip
agentcore deploy --yes
agentcore invoke "when is the W deadline?"
```

The runtime has **no writable storage**, so the first invocation of a session
copies the shipped dataset into scratch and points `COMPASS_DATA_DIR` at it.
Within a session the writes are real — registering for a module takes a seat,
dropping it gives the seat back — and they end with the session, which is the
right lifetime for fabricated data.

`POST /invocations` accepts one of three payloads. The decision card calls the
first two directly:

```jsonc
{"action": "sweep"}                                    // the whole picture
{"action": "decide", "finding": {...}, "option_id": "return_in_person"}
{"action": "ask", "question": "when is the W deadline?"}
{"action": "reset"}                                    // see below
```

A payload with no `action` is read by what it contains: a bare `prompt` is a
question, and nothing at all means a sweep.

`reset` regenerates the dataset. A live demo endpoint is consumed by its first
visitor — once someone clears the library hold, the next person to look finds
nothing to see — and the generator is deterministic and the data is fabricated,
so putting it back is honest. It is a demo affordance, not part of the agent.

Note the asymmetry between the first two, which is the design. A sweep may only
run the two whitelisted bookkeeping actions. A `decide` carries a human's
choice, so it executes what was chosen — and `handle()` returns every failure as
a value rather than an exception, distinguishing a *bad request* from a
*refusal by the rules*. A refusal is a result worth showing the student, not a
500.

## 9. Tests

```bash
python -m pytest tests -q      # 114 passed, no network, ~4s
```

The suite never calls a model and never touches the checked-in `data/`: each
test generates a fresh dataset in a temporary directory, and an autouse fixture
strips AWS and provider credentials from the environment so the suite cannot
behave differently on a machine that happens to be logged in.

Two of the files are worth pointing at:

- **`test_gate.py`** tests the policy directly. The property that matters is
  that R6 is the *only* path to a surface verdict, and that an unauthorised
  resolution reported as needing no judgement still gets asked about.
- **`test_bundle.py`** builds the deployment bundle's layout in a temp directory
  and runs the entrypoint inside it with a stripped environment. It exists
  because the MCP server runs as a **subprocess**, and a child process inherits
  the environment rather than the parent's `sys.path` — so a fix that only
  patched `sys.path` would pass every local test and fail on the first real
  invocation. That is a deployment bug no amount of local testing finds.

  The assertion is on the **environment the entrypoint builds**, not on the
  integration: removing the `PYTHONPATH` export and re-running the integration
  check here *still succeeds*, because the child process starts with normal
  `site` processing and an editable install resolves the import anyway. A test
  that passes with the fix removed is not a test, so the invariant is asserted
  where it is actually load-bearing and the integration half is labelled as the
  smoke test it is.

## 10. What Compass will not do

Stated as limits, because a system like this is defined by its refusals:

- **It will not spend the student's money.** Any action with a cost is a card,
  never an automatic action.
- **It will not change what she studies on its own initiative.** Switching
  specialisation is offered, never taken.
- **It will not contact a human for her** without her choosing to. Sending a
  message to an advisor is irreversible in a way a plan repair is not, and the
  receipt says so.
- **It will not act on a low-confidence reading.** Below 0.70 the verdict is
  silence, regardless of how bad the consequence would be if true.
- **It will not interrupt about something it can fix later.** Recoverable
  problems are handled in the background until they stop being recoverable.

## 11. Built with

**Strands Agents SDK** for the agents and tools · **FastMCP** for the school-data
server · **Amazon Bedrock AgentCore Runtime** for deployment · **Amazon
Bedrock** for the deployed model · **FastAPI + SSE** for the decision card ·
**Pydantic v2** for the structured contract between the model and the gate.

Built with **Claude Code**.

### Licence

MIT — see [LICENSE](LICENSE). This is original work written for this hackathon;
no pre-existing project code was reused.

### On the data, once more

All records are fabricated, the institution is fictional, and no real student's
information is anywhere in this repository. See `data/meta.json`.
