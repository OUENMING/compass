# Compass

> **The missing manual for the students nobody handed a manual to.**

[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12%2B-blue?style=flat-square)](https://www.python.org/)
[![Strands Agents](https://img.shields.io/badge/Strands-Agents%20SDK-orange?style=flat-square)](https://strandsagents.com/)
[![AgentCore](https://img.shields.io/badge/Deployed-AgentCore%20Runtime-yellow?style=flat-square)](https://aws.amazon.com/bedrock/agentcore/)
[![Tests](https://img.shields.io/badge/tests-132%20passing-brightgreen?style=flat-square)](tests/)
[![Data](https://img.shields.io/badge/data-100%25%20synthetic-lightgrey?style=flat-square)](#-license-and-data)

**English** · [简体中文](README.zh-CN.md)

A background agent that reads a university's degree rules the way a registrar
does. Silent while everything is fine. It speaks up only when silence would cost
a student something she cannot get back — and then **does the thing** rather
than describing it.

Built for the **AWS Agents for Humans** hackathon · **Good Neighbor Agents** track.

![Compass architecture](docs/architecture.png)

<p align="center">
  <a href="#-the-problem">The problem</a> ·
  <a href="#-features">Features</a> ·
  <a href="#-install">Install</a> ·
  <a href="#-usage">Usage</a> ·
  <a href="#-project-structure">Structure</a> ·
  <a href="#-tech-stack">Tech stack</a> ·
  <a href="#-how-it-works-silence-is-a-decision">How it works</a> ·
  <a href="#-faq">FAQ</a> ·
  <a href="ARCHITECTURE.md">Architecture</a> ·
  <a href="docs/DEVPOST.md">Devpost</a> ·
  <a href="docs/blog/">Write-ups</a>
</p>

---

## 🧭 The problem

A university runs on rules that were never written down *for students*.

Prerequisite chains that do not bite until two semesters later. A library fine
that quietly escalates into a registration block. A rule change buried on a
handbook page instead of sent to an inbox. A degree plan that must be approved
before a registration window opens, in an order nobody explains.

None of it is a secret. All of it is published — the way a legal code is:
complete, unindexed, and written for the people administering it.

The students who get caught are not the ones struggling academically. They are
the ones with **nobody at home who has already navigated a university**:
first-generation students, and international students also navigating a visa
calendar on top of a term calendar. That is this project's whole audience, and
why the demo student is one of them.

**What exists today is built for the institution, not the student.** EAB,
Stellic, Ellucian and Druid all sell to the registrar's office: analytics,
degree-audit tooling, retention dashboards. A 2026 survey of the category noted
that there is still no student-facing agent. The student is the *subject* of
these systems, never the *user* of one.

### Why an agent, and not another app

The hackathon brief says it directly: *"instead of another app people open and
manage, the agent runs autonomously and only surfaces when there's a real
decision to make."*

A course-picker is exactly what that brief rules out. Compass is not a tool a
student opens — it is a watcher that reads the rules continuously and interrupts
**at most six times a term**, and only when the alternative is a loss she cannot
undo.

---

## ✨ Features

| Feature | What it does | Built with | Status |
|---|---|---|---|
| **Deterministic silence gate** | Six plain-Python rules decide whether to speak. The model never votes on whether to interrupt. | `src/compass/gate.py` | ✅ |
| **Consequence reasoning** | Reads a deadline and reports `{irreversible_after_deadline, days_until_last_safe_action, confidence, options}` as a structured `Finding`. | Strands + Pydantic v2 | ✅ |
| **Real side effects** | Seven actions that refuse the way the registrar's system refuses — unmet prerequisite, ECTS cap, full module, failed audit. | `src/compass/tools/actions.py` | ✅ |
| **Receipts you can re-derive** | Every action writes an append-only receipt with a *deterministic* confirmation number. Re-run the demo, get the same number. | `data/receipts.jsonl` (written at runtime) | ✅ |
| **Agent whitelist** | Two auto-actions permitted. Spending money, changing what she studies, and contacting a human are all absent — and always will be. | `AUTO_ACT_PERMITTED` | ✅ |
| **Decision card UI** | Silent → card slides in → she picks → it executes → receipt on screen. | FastAPI + SSE | ✅ |
| **School data behind a protocol** | The catalogue, the degree rules and her record are served by a FastMCP server over stdio, not imported. Two transports, one tool list. | FastMCP · `MCPClient` | ✅ |
| **Three specialist agents** | Pathfinder (prerequisite chains) · Sentinel (deadline scan) · Explainer (what a rule means), composed agents-as-tools. | Strands Agents SDK | ✅ |
| **Deployed and remote-drivable** | Live on AgentCore Runtime in `eu-west-1`; `compass.remote` speaks the full four-verb contract over `InvokeAgentRuntime`. | AgentCore · boto3 | ✅ |
| **Pluggable model backend** | `bedrock` · `openai` · `deepseek`, chosen by one environment variable. | `src/compass/llm.py` | ✅ |

See [`docs/DEVPOST.md`](docs/DEVPOST.md) for the three demo scenarios in full.

---

## 📦 Install

### Requirements

| | |
|---|---|
| Python | **3.12+** (deployed on 3.14) |
| [uv](https://docs.astral.sh/uv/) | any recent version |
| AWS account | **not needed** to run locally |
| Docker | **not needed** (CodeZip deployment) |

### Setup

```bash
git clone https://github.com/OUENMING/compass
cd compass
uv venv && uv pip install -e ".[web,dev]"
```

That is the whole install — no database, no cloud dependency. You do need a model
backend: set `COMPASS_PROVIDER` plus its key, or `DEEPSEEK_API_KEY`, or
`OPENAI_API_KEY`. Without one, `resolve_provider()` raises rather than guessing.
See [Optional extras](#optional-extras).

### Optional extras

```bash
uv pip install -e ".[remote]"   # only if your AWS credentials come from `aws login`
uv pip install -e ".[docs]"     # only to regenerate docs/architecture.png
```

`aws login` issues browser-based temporary credentials through the AWS Common
Runtime, and `botocore` refuses that provider without the `crt` extra. If your
credentials are a plain access key, you do not need this.

The architecture figure is checked in, so `docs` is not needed to run or read the
project — only to redraw it.

---

## 🚀 Usage

### 1 · Generate the synthetic dataset

```bash
python -m compass.data.generate
```

Deterministic: generate twice, get byte-identical files. The tests assert
exactly that.

### 2 · Pick a model backend

Compass is deliberately model-agnostic and reads its backend from the
environment:

```bash
export COMPASS_PROVIDER=deepseek DEEPSEEK_API_KEY=...   # or openai, or bedrock
```

### 3 · Run a sweep

```bash
python -m compass.agents.compass                     # sweep, and act on R4
python -m compass.agents.compass --direct-tools      # skip the MCP subprocess
python -m compass.agents.compass --json              # machine-readable verdicts
python -m compass.agents.compass --ask "what happens if I switch specialisation?"
```

Exit code is **`10` when something surfaced**, so a cron job can tell "nothing to
report" from "she has a decision to make".

### 4 · Open the decision card

```bash
uvicorn web.app:app        # → http://localhost:8000
```

Silent → a card slides in → click an option → the action executes → a receipt
appears.

### 5 · Drive the deployed agent

`agentcore invoke` wraps whatever you give it in `{"prompt": ...}`, reaching the
conversational half of the contract and only that. The other two verbs need their
payload intact — which is what `compass.remote` is for:

```bash
python -m compass.remote --json > sweep.json      # sweep the deployed agent
python -m compass.remote                          # read the report
python -m compass.remote --decide 2 --option 1 --from sweep.json
python -m compass.remote --ask "when is the W deadline?"
```

A real run against the deployed endpoint:

```text
2026-09-28 — 2 finding(s): 2 surfaced, 0 handled, 0 deliberately passed over.

  [1] surfaced: Overdue library items are blocking your registration and escalate on 5 October
          by 2026-10-05 (7 day(s) left)  ·  severity critical  ·  confidence 0.95
          -> 1. return-in-person: Return the three items in person
          -> 2. pay-charge: Authorise the EUR 45.00 replacement charge
          choose with: --decide 1 --option 1
```

After `--decide 1 --option 1`:

```text
[LIB-2026-B6E2B7] Recorded the items as returned and cleared the library hold.
```

Re-sweeping in the same session returns **one** finding instead of two. The
deployed agent really did the work, and the state it changed is still changed.

> **Findings are addressed by position, not by id.** Ids are written by the model
> on every sweep and differ between runs; the position cannot move, because the
> report and the client walk the same list in the same order.

> **A session is the unit of state**, so a `decide` has to name the session its
> `sweep` ran in. Every call prints the one it used and `--session` takes it
> back. Without one you get a fresh session, which starts from the shipped
> dataset.

---

## 📁 Project structure

```
compass/
├── README.md                  this file
├── README.zh-CN.md            简体中文
├── CLAUDE.md                  orientation for an AI agent working in the repo
├── ARCHITECTURE.md            how it is put together, and why
├── ARCHITECTURE.review-20260918.md   the review that produced the above
├── LICENSE                    MIT
├── pyproject.toml             extras: web · dev · remote
│
├── data/                      synthetic dataset — 26 modules, prerequisite
│   ├── courses.json           graph, degree requirements, one student,
│   ├── degree_requirements.json   calendar, notices
│   ├── student.json
│   ├── calendar.json
│   ├── announcements.json
│   ├── meta.json              provenance + "all of this is fabricated"
│   └── receipts.jsonl         append-only record of everything it did (runtime)
│
├── src/compass/
│   ├── gate.py                ★ six deterministic rules — the only path
│   │                            to the student's attention
│   ├── models.py              the `Finding` contract (Pydantic v2)
│   ├── store.py               re-reads on read; atomic writes
│   ├── prereq.py              prerequisite graph traversal
│   ├── audit.py               degree-plan audit
│   ├── llm.py                 backend selection (bedrock · openai · deepseek)
│   ├── remote.py              client for the deployed runtime
│   ├── agents/
│   │   ├── compass.py         orchestrator: observe → judge → act → record
│   │   ├── pathfinder.py      prerequisite chains, degree gaps
│   │   ├── sentinel.py        ★ deadline scan → structured judgements
│   │   └── explainer.py       what a hold / W-deadline / double-count means
│   ├── tools/
│   │   ├── school_mcp_server.py   FastMCP over stdio (the deployment path)
│   │   ├── school_tools.py        the same functions as in-process @tools
│   │   ├── analysis_tools.py
│   │   ├── registry.py            picks the transport, one tool list
│   │   └── actions.py             real side effects + receipts
│   └── data/generate.py       deterministic dataset generator
│
├── web/
│   ├── app.py                 FastAPI: /, /api/events (SSE), POST /api/decide
│   └── static/                the decision card
│
├── app/Compass/main.py        AgentCore entrypoint (reuses src/compass)
├── agentcore/                 deployment config + the SSM read policy
│
├── tests/                     132 tests, no network, ~4s
├── docs/
│   ├── architecture.png       generated by make_architecture.py — the
│   │                            figure is code, so it cannot go stale
│   ├── DEVPOST.md             submission copy
│   ├── VIDEO.md               demo video shot list
│   └── blog/                  three write-ups
└── agentcore/policies/        the one-ARN SSM policy
```

---

## 🛠 Tech stack

| Technology | Version | Used for | Link |
|---|---|---|---|
| [Strands Agents SDK](https://strandsagents.com/) | 1.55.1 | The three specialist agents, `@tool`, agents-as-tools, `MCPClient` | strandsagents.com |
| [FastMCP](https://github.com/jlowin/fastmcp) | — | School data behind a stdio protocol boundary | github.com/jlowin/fastmcp |
| [Amazon Bedrock AgentCore Runtime](https://aws.amazon.com/bedrock/agentcore/) | — | Deployment (CodeZip, `eu-west-1`) | aws.amazon.com |
| Amazon Bedrock | — | First-class model backend (Claude) | aws.amazon.com/bedrock |
| AWS Systems Manager Parameter Store | — | The deployed credential, as a `SecureString` | aws.amazon.com/systems-manager |
| [Pydantic](https://docs.pydantic.dev/) | v2 | The `Finding` contract between model and gate | docs.pydantic.dev |
| [FastAPI](https://fastapi.tiangolo.com/) + SSE | — | The decision card | fastapi.tiangolo.com |
| [uv](https://docs.astral.sh/uv/) | — | Environment and packaging | docs.astral.sh/uv |
| [pytest](https://pytest.org/) | — | 132 tests, no network | pytest.org |
| Python | 3.12+ | Runtime (deployed on 3.14) | python.org |

Development tooling: **Claude Code**.

---

## 🧠 How it works: silence is a decision

> This is the part worth reading. Everything else is plumbing that any competent
> agent has.

Ask a model *is this important?* and it says yes — about almost everything,
because "somewhat important" is always defensible. So every notification system
built this way becomes noise, and a student who has learned to ignore her agent
is **worse off than one with no agent at all**: she has also lost the worry that
would have made her check.

**Compass never asks a model whether to speak.**

The model establishes **facts** — what changed, what it costs, when the last safe
moment is, how confident it is, what the options are. That arrives as a
`Finding`. Whether to interrupt is then decided by plain Python in
[`src/compass/gate.py`](src/compass/gate.py), in a fixed order:

| Rule | Condition | Verdict |
|---|---|---|
| **R1** | Confidence below 0.70 | stay silent — never act on a guess |
| **R2** | The last safe moment has already passed | stay silent — there is no move left to offer |
| **R3** | The consequence is recoverable | stay silent — handle it in the background, speak up if that changes |
| **R4** | Irreversible, and the written rules determine the resolution | **act**, from a whitelist, and leave a receipt |
| **R5** | Irreversible, but more than 45 days out | stay silent — this is a watch, not a decision |
| **R6** | Irreversible, inside the horizon, and the choice is genuinely hers | **surface a card** |

```text
Finding — facts only; the model never decides whether to speak
   │
   ▼
gate.py · R1 → R2 → R3 → R4 → R5 → R6 · first match wins
   │
   ├── stay silent    R1 · R2 · R3 · R5
   ├── act + receipt  R4   (whitelist only)
   └── surface        R6 ──▶ the student
```

**R6 is the only path to the student's attention in the entire system.**

Three properties fall out of doing it this way, and each is a deliverable rather
than a claim:

| Property | Evidence |
|---|---|
| **Explainable** | Every verdict cites the rule that produced it, in language written for the student, and that string is shown on the card. She can ask *"why am I seeing this?"* and get a real answer. |
| **Reproducible** | The same finding on the same date always yields the same verdict, so the recorded demo and the test suite test the same thing. |
| **Auditable** | Silence carries a reason too: `GateDecision.reason` is populated whether or not anything was shown, so *"it did nothing"* is inspectable rather than indistinguishable from a crash. |

### The whitelist is where the safety lives

`AUTO_ACT_PERMITTED` in `gate.py` holds **two** actions: repairing a degree plan
and filing one. Both are bookkeeping whose outcome the programme's own written
rules already fix. Everything else — spending money, changing what she studies,
contacting a human — is absent from that list and always will be.

There is a specific failure this prevents, and it is the one the project exists
to avoid. A model can look at a €45 library charge and reason, correctly, that
it has to be paid eventually, and report `needs_human_choice: false` — *"no
judgement required"*. A gate that trusted that field would pay it.

**Compass does not trust the field.** If the resolution is not on the whitelist,
the finding falls through to R5/R6 and the student is asked.

> *Asking costs three seconds; guessing costs her something she cannot get back.*

### Real actions, with receipts

"Not just chat about it" is the spine of this hackathon, so the actions are real
and they validate like the registrar's system would.

Seven actions ship: `register_modules`, `drop_module`, `resolve_library_hold`,
`set_specialisation`, `repair_degree_plan`, `file_degree_plan`,
`notify_advisor`.

Each one **refuses** the way the real system refuses. Registering for
*Econometrics II* with its prerequisite unpassed returns:

```json
{"error": "ECON30010 requires ECON20030, which the student has not passed. Registration refused."}
```

Registration checks unmet prerequisites, the term ECTS cap, seat availability and
duplicate registration — and validates everything *before* mutating anything, so
a refused registration takes no seat. `file_degree_plan` refuses a plan that
would fail its own audit, which makes repair-then-file a forced sequence rather
than a suggestion.

Every successful action writes a receipt with a **deterministic** confirmation
number, derived from the action and its arguments rather than a random value — so
re-running the demo produces the same receipt. The receipts are the evidence:
`data/receipts.jsonl` (created on first run, not checked in) is an append-only
record of everything Compass did, **including the things it did without asking**.

### What Compass will not do

Stated as limits, because a system like this is defined by its refusals:

| It will not… | Because |
|---|---|
| **Spend the student's money** | Any action with a cost is a card, never an automatic action. |
| **Change what she studies on its own initiative** | Switching specialisation is offered, never taken. |
| **Contact a human for her** | Unless she chooses to. Sending a message to an advisor is irreversible in a way a plan repair is not, and the receipt says so. |
| **Act on a low-confidence reading** | Below 0.70 the verdict is silence, however bad the consequence would be if true. |
| **Interrupt about something it can fix later** | Recoverable problems are handled in the background until they stop being recoverable. |

---

## ☁️ Deployment

The deployed agent **is** the same agent. `app/Compass/main.py` validates a
payload, calls into `compass.agents.compass`, and serialises the answer; nothing
about Compass's behaviour lives in the entrypoint, so the local demo and the
deployed runtime cannot drift apart.

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

### The contract

`POST /invocations` accepts one of four payloads. The decision card calls the
first two directly:

```jsonc
{"action": "sweep"}                                    // the whole picture
{"action": "decide", "finding": {...}, "option_id": "return_in_person"}
{"action": "ask", "question": "when is the W deadline?"}
{"action": "reset"}                                    // regenerate the dataset
```

A payload with no `action` is read by what it contains: a bare `prompt` is a
question, nothing at all means a sweep.

`reset` exists because a live demo endpoint is consumed by its first visitor —
once someone clears the library hold, the next person to look finds nothing. The
generator is deterministic and the data is fabricated, so putting it back is
honest. It is a **demo affordance, not part of the agent**.

Note the asymmetry between the first two, which is the design. A sweep is
unattended, so it may only run the two whitelisted bookkeeping actions. A
`decide` carries a human's choice, so it executes what was chosen and the
receipt records which option it was.

Every failure comes back as a **value**, because an entrypoint that raises gives
whoever invoked it a 502 and nothing to act on:

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

### The credential the repository must not contain

A deployed agent needs a model credential, and `agentcore.json` is committed.
Its `envVars` are therefore the wrong place for a key. The runtime's environment
variables have exactly two fields, `name` and `value`, and no reference syntax —
so the **name** of an SSM parameter goes in the committed file and the value
stays in SSM:

```json
{"name": "COMPASS_SECRET_PARAMETER", "value": "/compass/model-api-key"},
{"name": "COMPASS_SECRET_TARGET",    "value": "DEEPSEEK_API_KEY"}
```

with a policy attached to the runtime's execution role granting
`ssm:GetParameter` on **that one ARN and nothing else**
([`agentcore/policies/model-key.json`](agentcore/policies/model-key.json)). The
entrypoint reads it at cold start, idempotently, and is a no-op when the variable
is already set — so the local demo, the CLI and the test suite never reach AWS on
account of it.

### Which model answers

Compass supports three backends and picks one from `COMPASS_PROVIDER`:
`bedrock`, `openai`, or `deepseek`. The deployed runtime here runs **`deepseek`**.

`bedrock` is the first-class path and what this was built against. The AWS
account used for this deployment is under a new-account restriction on the
Bedrock **data plane** — `ValidationException: Access to Bedrock models is not
allowed for this account`, reported as `Error 002`. Isolating it showed the
restriction is account-wide, not model-specific: **Amazon Nova and Titan
fail identically**, in every region, under the account root's own credentials,
while the Bedrock *control plane* answers 200 and the console Playground renders
normally. That asymmetry is why the console can look healthy while every API call
fails.

Rather than let that decide whether the demo works, the runtime was pointed at a
different provider — which is what the abstraction was for. **Switching back is
one environment variable and a redeploy; the code path is the same one.**

---

## ✅ Tests

```bash
python -m pytest tests -q      # 132 passed, no network, ~4s
```

The suite never calls a model and never touches the checked-in `data/`: each test
generates a fresh dataset in a temporary directory, and an autouse fixture strips
the AWS and provider-selection variables from the environment and redirects
`HOME` to an empty directory — so the suite cannot behave differently on a
machine that happens to be logged in.

Three files are worth pointing at:

- **[`test_gate.py`](tests/test_gate.py)** — tests the policy directly. The
  property that matters is that R6 is the *only* path to a surface verdict, and
  that an unauthorised resolution reported as needing no judgement **still gets
  asked about**.
- **[`test_bundle.py`](tests/test_bundle.py)** — builds the deployment bundle's
  layout in a temp directory and runs the entrypoint inside it with a stripped
  environment. It exists because the MCP server runs as a **subprocess**, and a
  child process inherits the environment, not the parent's `sys.path` — so a fix
  that only patched `sys.path` would pass every local test and fail on the first
  real invocation: a deployment bug no amount of ordinary local testing finds.

  The assertion is on the **environment the entrypoint builds**, not on the
  integration: removing the `PYTHONPATH` export and re-running the integration
  check *still succeeds*, because the child process starts with normal `site`
  processing and an editable install resolves the import anyway. **A test that
  passes with the fix removed is not a test**, so the invariant is asserted where
  it is actually load-bearing, and the integration half is labelled the smoke
  test it is.

- **[`test_remote.py`](tests/test_remote.py)** — pins the wire contract between
  the deployed agent and `compass.remote`. One side builds that JSON as a dict
  and the other reads it as a dict, so nothing type-checks the seam; the tests
  assert the exact payload each verb puts on the wire, which is what a rename on
  either side would break.

---

## ❓ FAQ

<details>
<summary><b>Do I need an AWS account to run this?</b></summary>

No. Nothing in the data layer, the tools, the agents, the gate or the web UI
touches AWS. The only things that need credentials are `agentcore deploy` and
`compass.remote`.

You do need *a model backend*, and that can be any OpenAI-compatible endpoint:

```bash
export COMPASS_PROVIDER=openai OPENAI_API_KEY=...
```

</details>

<details>
<summary><b>Why doesn't it just ask the model whether to notify me?</b></summary>

Because the model will say yes, about almost everything. That is the failure mode
the whole design is built around — see
[silence is a decision](#-how-it-works-silence-is-a-decision). The model supplies
facts; a fixed order of six Python rules decides whether you get interrupted.

It also makes the demo *reproducible*: the same finding on the same date always
produces the same verdict, so what you see in the video is what the tests assert.

</details>

<details>
<summary><b>Can it spend my money?</b></summary>

No. There is a `resolve_library_hold` action that can authorise a €45
replacement charge, and it is **not** on the auto-action whitelist. Any action
with a cost is always a card you choose from.

This is not theoretical — during development the model reported the charge as
`needs_human_choice: false`, reasoning that it has to be paid eventually. A gate
that trusted that field would have paid it. There is now a test for exactly that.

</details>

<details>
<summary><b>Why is the university fictional?</b></summary>

Every record in `data/` is synthetic and the institution — *Harbour University
Dublin* — does not exist. This is a design decision, not just a licensing
convenience.

The scenarios depend on specific rule readings: a withdrawn waiver, a hold that
escalates on a particular date, a double-count rule. Building them onto a real
university's handbook would mean shipping a document that **asserts things about
a real institution's regulations** — assertions that go wrong the moment the
institution changes a rule, and wrong in a way that could mislead a real student.

A fictional institution makes the demo honest: everything in it is true about the
fictional world, and nothing in it is a claim about yours.

</details>

<details>
<summary><b>The demo endpoint shows nothing to see. What happened?</b></summary>

Someone got there first. A live demo is consumed by its first visitor — once
anyone clears the library hold, the next person to look finds a clean record.

Send `{"action": "reset"}` to `/invocations` (or click **Reset** in the decision
card) to regenerate the dataset. The generator is deterministic and the data is
fabricated, so putting it back is honest.

</details>

<details>
<summary><b>Why doesn't <code>agentcore invoke</code> work for a sweep?</b></summary>

Because `agentcore invoke` wraps whatever you pass it in `{"prompt": ...}`. That
reaches the `ask` verb and only that — `sweep` and `decide` never see their real
payload.

Use `python -m compass.remote`, a small client over `InvokeAgentRuntime` that
speaks the full contract. It has its own tests
([`tests/test_remote.py`](tests/test_remote.py)) because the payload shape is a
contract that nothing type-checks.

</details>

<details>
<summary><b>Can I point it at my own programme?</b></summary>

Yes, and the dataset generator is already parameterised by requirement group —
nothing in the gate knows what economics is. Replace `data/*.json` with your own
catalogue, prerequisite graph and requirement groups; the agents read them
through the same tools.

The interesting open question is whether the *rule shapes* generalise — a
prerequisite chain, a deadline that escalates, a double-count. See the
[roadmap](#-roadmap).

</details>

---

## 🗺 Roadmap

| Direction | The argument |
|---|---|
| **Rule shapes, not one programme** | The vocabulary of rules is currently a single Economics programme. The question worth answering is whether the *shapes* generalise — and I think they do, because the generator is already parameterised by requirement group and the gate is domain-blind. |
| **Rules that are not written down** | Sentinel currently reasons over rules that appear in the handbook. The harder and more valuable version reasons over the ones that don't — the pattern that says *"the School may, at its discretion"*. |
| **More than one student** | The current demo follows a single record. The gate, the whitelist and the receipt log are all per-student already, and the receipt log is the piece an access office would actually want: an audit trail of what the agent did on its own, and why. |
| **Event-driven instead of swept** | The sweep is currently on demand; a term-long deployment would run it on a calendar trigger and on handbook-change detection. |

---

## 📚 Documentation

| Document | What is in it |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | How it is put together, and *why* — including alternatives considered and rejected |
| [`ARCHITECTURE.review-20260918.md`](ARCHITECTURE.review-20260918.md) | The audit that produced the architecture doc: what was deep, what was shallow, what is still wrong |
| [`CLAUDE.md`](CLAUDE.md) | Orientation for an AI agent working in this repo — where things live and which traps to avoid |
| [`docs/DEVPOST.md`](docs/DEVPOST.md) | The submission copy: problem, audience, three demo scenarios |
| [`docs/VIDEO.md`](docs/VIDEO.md) | Demo video shot list |
| [`docs/blog/01`](docs/blog/01-agents-for-humans-silence-by-default.md) | Silence by default: refusing to let the model decide when to speak |
| [`docs/blog/02`](docs/blog/02-agents-for-humans-agentcore-deployment.md) | Deploying to AgentCore: the bug no local test could find |
| [`docs/blog/03`](docs/blog/03-agents-for-humans-testing.md) | Testing an agent that is defined by what it refuses to do |
| [`docs/make_architecture.py`](docs/make_architecture.py) | The architecture figure is code, so it cannot go stale |

---

## 📄 License and data

MIT — see [LICENSE](LICENSE). SPDX-License-Identifier: `MIT`.

This is original work written for this hackathon; **no pre-existing project code
was reused.**

### On the data, once more

All records are fabricated, the institution is fictional, and **no real
student's information is anywhere in this repository**. See
[`data/meta.json`](data/meta.json).
