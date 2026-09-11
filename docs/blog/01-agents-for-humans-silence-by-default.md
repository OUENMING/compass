# My Agents for Humans entry never asks the model whether to interrupt

*How a 150-line rule engine became the most important file in the repository.*

---

Every notification system eventually becomes noise, and the reason is
structural rather than a failure of care.

Ask a language model *"is this important?"* and it says yes. It says yes about
almost everything, because "somewhat important" is always defensible, and a
model trained to be helpful is not trained to be blunt about your Tuesday.
Stack that up over a semester and you get an agent that pings you eleven times a
day, and a student who has learned to swipe them away without reading.

That student is **worse off than one with no agent at all**. She has lost the
low-grade worry that would have made her check the handbook herself, and gained
nothing in its place.

This is the design problem I built my entry for the AWS **Agents for Humans**
hackathon around. Compass is a background agent for first-generation and
international university students: it watches a degree's rules the way a
registrar does, and speaks up only when staying quiet would cost the student
something she cannot get back.

The interesting part is not the agents. It is the thing that decides whether
they are allowed to bother her.

## The split

Compass does not ask a model whether to interrupt. It asks a model for **facts**,
and then decides in code.

The facts arrive as a Pydantic model:

```python
class Finding(BaseModel):
    title: str
    what_happened: str
    consequence_if_ignored: str
    severity: Severity
    irreversible_after_deadline: bool     # the question that matters
    deadline: date | None
    days_until_last_safe_action: int | None
    needs_human_choice: bool
    confidence: float                     # 0..1
    options: list[Option]
```

And the decision is a pure function:

```python
def decide(finding: Finding, today: date,
           horizon_days: int = 45,
           min_confidence: float = 0.7) -> GateDecision:
```

No I/O, no clock, no randomness — `today` is passed in rather than read from the
system. That matters more than it looks. It means the same finding on the same
date always produces the same verdict, so the recorded demo and the test suite
are exercising the same artefact instead of two things that happen to look
alike.

The rules, in evaluation order:

| | Condition | Verdict |
|---|---|---|
| **R1** | Confidence below 0.70 | silent — never act on a guess |
| **R2** | The last safe moment has passed | silent — there is no move left to offer |
| **R3** | The consequence is recoverable | silent — handle it in the background |
| **R4** | Irreversible, no judgement required | **act**, from a whitelist |
| **R5** | Irreversible, more than 45 days out | silent — this is a watch, not a decision |
| **R6** | Irreversible, inside the horizon, genuinely hers to decide | **surface a card** |

R6 is the only path to the student's attention in the entire system.

## Why the order matters

Three of those rules are about *not* interrupting, and the ordering is what
makes the quiet ones do real work.

**R2 before R3** means a missed deadline is not a crisis to report — it is a
thing with no remaining move, and reporting it produces distress without
offering an action. That goes in the next plan review instead.

**R3 before R4 and R6** is the one that keeps the whole thing livable. A
recoverable problem never earns an interruption, regardless of how big it is,
because the agent can fix it in the background and speak up only if it stops
being fixable. The asymmetry Compass is built on is that a missed irreversible
deadline costs a semester, while an unnecessary notification costs three seconds
— and the usual failure mode is to over-correct toward the cheap side.

**R5 before R6** is the one that keeps the *card* meaningful. A real one-way
door eight months out is not a decision today; it is a thing to watch. The
horizon is a constant, not a heuristic:

```python
DEFAULT_HORIZON_DAYS = 45
```

## The whitelist is where safety lives

The part I would point at first is not the rule ordering. It is this:

```python
# The complete list of actions Compass may take on its own initiative.
#
# This is deliberately a whitelist held by the *policy* module, not by the
# module that owns the capability. ``compass.tools.actions`` can do many things;
# which of them may run without asking is a decision about the student, and that
# decision lives here.
AUTO_ACT_PERMITTED = frozenset({"repair_degree_plan", "file_degree_plan"})
```

Seven actions ship — register, drop, resolve a hold, switch specialisation,
repair a plan, file a plan, notify an advisor. Two of them may run unattended.
Both are bookkeeping whose outcome the programme's *written rules* already fix
completely: rule 1 says a module counts once, rule 2 says a group needs a certain
number of credits, so repairing a plan applies arithmetic rather than judgement.
Filing submits a document whose contents those rules have already determined.

Everything that spends money, changes what she studies, or contacts a human is
absent from that set, and the module that owns those capabilities has no say in
it. That separation is deliberate. `actions.py` is *capability*; `gate.py` is
*policy about a person*. They are different concerns and they belong in
different files.

### The bug this caught

Here is the failure it prevented, and it is the reason I would argue for this
split rather than trusting a model's self-report.

The demo has a library scenario: three overdue items, a €45 replacement charge,
and a library block that escalates into a financial hold. During development,
the scanning agent looked at that charge and reported:

```json
{"needs_human_choice": false, ...}
```

Its reasoning was sound on its own terms. The charge has to be paid eventually,
there is one obvious resolution, so there is nothing for the student to decide.

That reasoning is wrong, and it is wrong in exactly the way this project exists
to prevent. There *is* another way to get the same outcome — return the items in
person — and it trades her money against her time. That trade is hers to make.

A gate that trusted the field would have paid it. My gate does not trust the
field:

```python
declined = ""
if not finding.needs_human_choice:
    chain = auto_chain(finding)
    if chain is not None and set(chain) <= AUTO_ACT_PERMITTED:
        return GateDecision(verdict=Verdict.AUTO_ACT, ...)
    # The report claims no judgement is needed, but the resolution is not one
    # Compass is authorised to carry out alone. When those two disagree, the
    # cautious reading wins: asking costs three seconds, guessing costs the
    # student something she cannot get back.
    declined = ("Compass judged this to have one obvious resolution, but that "
                "resolution is not one it is allowed to make on your behalf — "
                "so it is asking you rather than doing it.")
```

When the model's self-assessment and the policy's authorization disagree, the
cautious reading wins and the student is asked. The reason string the student
sees is written in her language, not in rule codes.

## Making silence inspectable

One more thing, and it is the reason I think this pattern generalises beyond my
project.

A system that stays quiet most of the time is indistinguishable from a broken
system, unless you make the silence visible. `GateDecision.reason` is populated
for *every* verdict, including the SILENT ones, and the web UI lists them:

> **Watching.** Nothing has needed you yet.
>
> *Passed over:* this is fixable later, so staying quiet costs you nothing today.
> *Passed over:* real, but not yet a decision — you still have plenty of room.
> *Passed over:* the window has already closed; there is no decision left to
> make.

That list is what turns "it stays quiet by default" from a slogan into
something a judge — or a student — can check. It is also the fastest way to
debug the agent: when Compass is quiet and you expected a card, the reason tells
you which rule fired and therefore which fact was wrong.

## What I'd take to the next agent

If you are building anything that decides when to bother a human:

**Split facts from policy.** Let the model establish what is true; decide in
code what to do about it. The model is good at reading a handbook and bad at
knowing when to interrupt.

**Make the interrupt path singular.** One rule, one verdict, one place. If there
are three ways for a notification to reach a person, you have three things to
audit and eventually one of them will be wrong.

**Put the authorization list in the policy module, not the capability module.**
Which actions may run unattended is a claim about the user, and it should live
where every other claim about the user lives.

**Record the silences.** An agent that cannot show you what it decided *not* to
do has told you half of what you need.

And, if you are entering for a track called **Agents for Humans**: the thing that
made this project work was refusing to let the model make the one decision the
whole product is about.

---

*Compass is a Python + Strands Agents SDK project deployed on Amazon Bedrock
AgentCore Runtime. Source, tests and the architecture write-up are in the
repository.*
