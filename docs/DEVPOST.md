# Devpost submission copy

Everything below is written to be pasted into the Devpost form. Fields are in
the order Devpost asks for them.

---

## Project name

**Compass**

## Tagline (one line)

A background agent that reads your university's rules the way a registrar does,
stays silent until silence would cost you something you cannot get back, and
then does the thing instead of describing it.

## Track

**Good Neighbor Agents**

---

## Inspiration

Universities run on rules that were never written down *for students*.

Prerequisite chains that don't bite until two semesters later. A library fine
that quietly escalates into a registration block with a ten-day clearance
queue. A rule change published to a handbook page instead of sent to an inbox.
A degree plan that has to be approved before a registration window opens, in an
order nobody explains.

None of it is secret. It is published the way a legal code is published —
complete, unindexed, and written for the people administering it.

The students who get caught are not the ones struggling academically. They are
the ones with nobody at home who has already navigated a university.
First-generation students. International students, who are navigating a visa
calendar on top of a term calendar.

And the software that exists is built for the institution, not the student. EAB,
Stellic, Ellucian, Druid — all sold to the registrar's office: analytics,
degree-audit tooling, retention dashboards. The student is the *subject* of
these systems and never the *user*. A 2026 survey of the category noted plainly
that there is still no student-facing agent.

My own situation is why this is the problem I picked. I am a first-generation
international student, and I moved from Engineering into Economics partway
through my degree. I have spent a year learning rules that nobody wrote down
for me, and I found out about more than one of them by being on the wrong side
of it.

## What it does

Compass watches one student's situation against the rules and produces exactly
three kinds of outcome.

**It stays quiet.** Most of what it finds, it deliberately passes over — and it
can tell you why for every single one.

**It handles what needs no judgement.** Where the programme's written rules
determine the outcome completely, it just does it and leaves a receipt.

**It asks.** When a consequence is irreversible *and* the choice is genuinely
the student's, it puts one card on screen: what happened, what it costs if
ignored, why you are seeing it, and two or three buttons. She picks, it
executes, and the receipt is on screen.

The demo dataset has three live scenarios:

| | What is happening | What Compass does |
|---|---|---|
| **The withdrawn waiver** | A rule that let her take *Econometrics I* without *Quantitative Methods* has been withdrawn. The notice went to a handbook page, not to students. The module she needs is now blocked, it runs in Spring only, and it historically fills. | Surfaces a card with two real options: take the missing module and keep the Quantitative specialisation, or switch to General. Either way something is given up, and that trade is hers. |
| **The hold that escalates** | Three overdue Short Loan items. Cheap today; on 5 October they become a €45 charge and a financial hold that takes ten working days to clear — which will not land before registration. | Surfaces a card: return them in person (costs a trip) or authorise €45 (costs money). **Compass never spends her money without asking.** |
| **The duplicate nobody checks** | Her degree plan was never audited and is not on file. It double-counts one module across two requirement groups, and filing is a prerequisite for registration. | Handles it silently. The programme's own written rules fix the outcome, so asking would be theatre. It repairs the plan, files it, and leaves receipts `PLN-2026-12C318` and `ADV-2026-8350F8`. |

## How I built it

**The core design decision: silence is a decision, not an absence of output.**

Ask a model *is this important?* and it will say yes — about almost everything,
because "somewhat important" is always defensible. That is why every
notification system built this way becomes noise, and a student who has learned
to ignore her agent is **worse off than one with no agent at all**: she has also
lost the worry that would have made her check.

So Compass never asks a model whether to speak.

The model establishes **facts** — what changed, what it costs, whether the
consequence is reversible, how many days until the last safe moment, how
confident it is, what the options are. That arrives as a Pydantic `Finding`. The
decision to interrupt is then made by plain Python in `src/compass/gate.py`, in
a fixed order of six rules:

- **R1** confidence below 0.70 → silent
- **R2** the window has already closed → silent
- **R3** the consequence is recoverable → silent
- **R4** irreversible but no judgement required → act, from a whitelist
- **R5** irreversible but more than 45 days out → silent
- **R6** irreversible, inside the horizon, and genuinely her choice → **surface**

R6 is the only path to the student's attention in the entire system.

Three things fall out of that, and each one is a deliverable rather than a
claim:

- **Explainable.** Every verdict cites the rule that produced it, in language
  written for the student, and that string is on the card. "Why am I seeing
  this?" has a real answer.
- **Reproducible.** The same finding on the same date always yields the same
  verdict, so the recorded demo and the test suite are testing the same thing.
- **Auditable.** Silence carries a reason too. "It did nothing" is
  distinguishable from "it crashed."

**The whitelist is where the safety lives.** `AUTO_ACT_PERMITTED` holds two
actions: repairing a degree plan and filing one. Both are bookkeeping whose
outcome the programme's written rules already fix. Everything else — spending
money, changing what she studies, contacting a human — is absent and always
will be.

This prevented a specific failure during development. A model looked at the €45
library charge and reported `needs_human_choice: false`, reasoning that the
charge has to be paid eventually, so there was nothing to decide. A gate that
trusted that field would have paid it. Compass does not trust the field: if the
resolution is not on the whitelist, the finding falls through and the student is
asked. Asking costs three seconds; guessing costs her something she cannot get
back.

**Architecture.** Synthetic dataset → FastMCP server on stdio (school's data
behind a protocol boundary) → three specialist Strands agents composed as tools
(Pathfinder for prerequisite chains, Sentinel for the deadline scan, Explainer
for what a rule means) → orchestrator → the gate → real actions with receipts →
a FastAPI decision card over SSE. Deployed on **Amazon Bedrock AgentCore
Runtime** in `eu-west-1` as a CodeZip bundle, which is packaged from the
repository root so the deployed agent and the local demo are the same code.

**The actions are real.** Seven of them: register, drop, resolve a hold, switch
specialisation, repair a plan, file a plan, notify an advisor. Each refuses the
way the registrar's system refuses — an unmet prerequisite, the term ECTS cap, a
full module, a plan that would fail its own audit. Every check runs *before* any
mutation, so a refused registration takes no seat. Successes append to
`data/receipts.jsonl` with deterministic confirmation numbers: re-running the
demo produces the same receipt.

The deployed endpoint also accepts `{"action": "reset"}`, which regenerates the
dataset. A live demo is consumed by its first visitor — once someone clears the
library hold, the next person to look finds nothing to see — and since the
generator is deterministic and the data is fabricated, putting it back is
honest. It is a demo affordance, not part of the agent.

## Challenges

**The model kept being locally reasonable in ways that broke a global
property.** Three examples, all found by testing rather than by reasoning:

1. It split one root cause into three findings, so the student got three cards
   about one problem. Fixed with a worked example in the prompt: a finding whose
   only symptom is a date, whose cause has already been reported, is the same
   finding wearing a hat.
2. It misread "no choice" on the €45 charge, as described above.
3. It reported a situation that had already been resolved, because it was
   working from a stale read. That one turned out to be a real bug in my code,
   not the prompt: the store cached the course catalogue at construction, and
   the agent's tools run in a *different process* from the orchestrator, so a
   cached list goes stale the moment either side takes a seat. Removing the
   cache fixed it — and then broke the write path, because a de-cached
   `store.course(code)` hands back a fresh object that nobody persists.
   `course.enrolled += 1` looked right and silently did nothing. Both call sites
   now go through a single `take_seat(code, delta)` that does an atomic
   read-modify-write.

**Deployment had a bug that no local test could find.** The MCP server runs as a
subprocess, and a child process inherits the environment rather than the
parent's `sys.path`. A fix that patched only `sys.path` passed every local test
tests and would have failed on the first real invocation. It now exports
`PYTHONPATH`.

Testing that claim turned out to be more interesting than making it. I deleted
the export and re-ran the deployment-layout test — and it **still passed**,
because the spawned child starts with normal `site` processing and the editable
install in my checkout resolved the import anyway. My test was blind to the bug
it was guarding. The fix is now asserted where it actually lives, on the
environment the entrypoint builds for its subprocesses, with a comment
explaining why the integration test can't see it.

**The AgentCore runtime has no writable storage.** The first invocation of a
session copies the shipped dataset into scratch and points `COMPASS_DATA_DIR`
at it, so the writes are real within a session and disappear with it — which is
the right lifetime for fabricated data.

## What I learned

The most useful thing I did was refuse to let the model make the decision that
the whole product is about. Every time I was tempted to ask the model "should I
show this to her?", the honest answer was that it would say yes, and the product
would become another thing she ignores.

The second most useful thing was writing the failures down as tests. Every one
of the three prompt problems above is now a test that fails if it comes back.

## What's next

- The vocabulary of rules is currently one programme. The interesting question
  is whether the *rule shapes* — a prerequisite chain, a deadline that
  escalates, a double-count — generalise, and I think they do: the dataset
  generator is already parameterised by requirement group, and nothing in the
  gate knows what economics is.
- Sentinel currently reasons over rules that are written down. The harder and
  more valuable version reasons over rules that are *not* — the pattern in the
  handbook that says "the School may, at its discretion".

## Built with

`strands-agents` · `fastmcp` · `bedrock-agentcore` · `boto3` · `openai` ·
Amazon Bedrock (Claude on Bedrock — the first-class model backend) ·
Amazon Bedrock AgentCore Runtime · AWS Systems Manager Parameter Store ·
Amazon CloudWatch · `fastapi` · `uvicorn` · `pydantic` · `pytest` · Python 3.12+

Built with **Claude Code**.

**On the model, for anyone reading the code.** Compass is deliberately
model-agnostic — `compass.llm` selects a backend from `COMPASS_PROVIDER` — and
the deployment behind the demo runs the `deepseek` provider, with its key read at
cold start from an SSM `SecureString` that only the runtime's execution role may
read. `bedrock` is the primary path and the one this was developed against; the
AWS account used for this deployment is under a new-account restriction on the
Bedrock data plane (`ValidationException: Access to Bedrock models is not allowed
for this account`, surfaced as `Error 002`). Isolating it showed the restriction
is account-wide rather than model-specific — Amazon Nova and Titan fail
identically, in every region, under the account root's own credentials — so it
was not something to fix by choosing a different model. Rather than let it decide
whether the demo works, the runtime was pointed at another provider, which is
what the abstraction was for. Switching back is one environment variable and a
redeploy.

---

## The "try it out" links

| | |
|---|---|
| Repository | `https://github.com/OUENMING/compass` |
| Video (5 min) | see the YouTube/Vimeo link on the project page |
| Architecture | `ARCHITECTURE.md` + `docs/architecture.png` |

## Note on the data

**Every record in the repository is fabricated.** No real student, no real
institution, no real programme. The university in the demo is *Harbour
University Dublin*, which does not exist.

That is a deliberate design decision and not only a licensing convenience. The
scenarios depend on specific rule readings — a withdrawn waiver, a hold that
escalates on a particular date, a double-count rule — and building them onto a
real university's handbook would mean shipping a document that *asserts things
about a real institution's regulations*. Those assertions would be wrong the
moment the institution changed a rule, and wrong in a way that could mislead a
real student. A fictional institution makes the demo honest: everything in it is
true about the fictional world, and nothing in it is a claim about yours.

This is original work written for this hackathon. No pre-existing project code
was reused.
