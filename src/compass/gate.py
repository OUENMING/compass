"""The deterministic gate — Compass's single most important design decision.

The problem this solves
-----------------------
Every notification system eventually becomes noise. The reason is structural:
when an LLM (or a rules engine) is asked "is this important?", the answer is
almost always *yes, somewhat* — so everything gets surfaced, and the student
learns to ignore all of it. A student who ignores everything is worse off than
a student with no agent at all, because now they also feel covered.

So Compass never asks a model whether to speak. The model's job is to establish
**facts** about a situation (`Finding`) — what changed, what it costs, when the
last safe moment is, how sure it is. The decision to interrupt is then made by
the plain Python below, which is:

* **explainable** — every verdict cites one of six numbered rules, and the
  reason string is shown to the student on the card ("why am I seeing this?")
* **reproducible** — same finding + same date always yields the same verdict,
  so the demo is honest and the tests are real tests
* **auditable** — silence is a *decision with a reason*, not an absence of
  output. ``GateDecision.reason`` is recorded even when nothing is shown.

The asymmetry that drives the whole policy
------------------------------------------
A missed irreversible deadline costs a student a semester or a year. A
notification they didn't need costs them three seconds and a little trust.
Those are not equal, but they pull in opposite directions, and the usual failure
is to over-correct toward the cheap side. Compass resolves it by refusing to
spend attention on anything it can recover from: if ignoring something is
*fixable later*, Compass stays quiet and handles it in the next plan review.
Only genuine one-way doors get to interrupt.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from .models import Finding, GateDecision, Verdict


class Rule(str, Enum):
    """The six rules, in evaluation order. Cited in every verdict."""

    R1_LOW_CONFIDENCE = "R1"
    R2_WINDOW_CLOSED = "R2"
    R3_RECOVERABLE = "R3"
    R4_NO_CHOICE = "R4"
    R5_TOO_EARLY = "R5"
    R6_ONE_WAY_DOOR = "R6"


RULE_TEXT: dict[Rule, str] = {
    Rule.R1_LOW_CONFIDENCE: (
        "Compass is not confident enough in its reading of the rules to act on it."
    ),
    Rule.R2_WINDOW_CLOSED: (
        "The window has already closed. There is no decision left to make, so "
        "interrupting now would only cause distress without giving you a move. "
        "This goes into your next plan review instead."
    ),
    Rule.R3_RECOVERABLE: (
        "This is fixable later, so staying quiet costs you nothing today. "
        "Compass will handle it in the background and speak up only if it stops "
        "being fixable."
    ),
    Rule.R4_NO_CHOICE: (
        "There is only one correct resolution and it needs no judgement from "
        "you, so Compass did it and left a receipt rather than asking."
    ),
    Rule.R5_TOO_EARLY: (
        "Real, but not yet a decision — you still have plenty of room. "
        "Compass is watching it and will speak before it becomes urgent."
    ),
    Rule.R6_ONE_WAY_DOOR: (
        "Both conditions hold: ignoring this cannot be undone later, and the "
        "choice is yours to make, not something Compass can decide for you."
    ),
}

# How far ahead a one-way door has to be before it counts as "now".
# A deadline 8 months out is not a decision today; a deadline in 45 days is.
DEFAULT_HORIZON_DAYS = 45

# Below this, a finding is a guess and guesses do not get to interrupt people.
DEFAULT_MIN_CONFIDENCE = 0.7

# The complete list of actions Compass may take on its own initiative.
#
# This is deliberately a whitelist held by the *policy* module, not by the
# module that owns the capability. ``compass.tools.actions`` can do many things;
# which of them may run without asking is a decision about the student, and that
# decision lives here. Every entry is rule-determined: repairing a plan applies
# written programme rules 1 and 2, and filing one submits a document whose
# contents those rules have already fixed. Anything that spends money, changes
# what she studies, or contacts a human is not on the list and never will be.
AUTO_ACT_PERMITTED = frozenset({"repair_degree_plan", "file_degree_plan"})


def auto_chain(finding: Finding) -> list[str] | None:
    """The actions Compass would have to run to resolve a finding by itself.

    Reads the option the agent recommended (falling back to the first option)
    and returns its actions in the order they must run. Returns ``None`` when
    there is nothing to execute — no options, or an option that names no action.
    """
    if not finding.options:
        return None
    option = next((o for o in finding.options if o.recommended), finding.options[0])
    chain = [a for a in (option.after, option.action) if a]
    return chain or None


def decide(
    finding: Finding,
    today: date,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> GateDecision:
    """Apply the six rules to one finding and return a verdict with its reason."""

    # R1 — never act on a guess.
    if finding.confidence < min_confidence:
        return GateDecision(
            verdict=Verdict.SILENT,
            reason=f"R1: confidence {finding.confidence:.2f} < {min_confidence:.2f}. "
            + RULE_TEXT[Rule.R1_LOW_CONFIDENCE],
            finding=finding,
        )

    days = finding.days_until_last_safe_action

    # R2 — the window has closed; there is no choice left to offer.
    if days is not None and days < 0:
        return GateDecision(
            verdict=Verdict.SILENT,
            reason=f"R2: last safe action was {abs(days)} day(s) ago. "
            + RULE_TEXT[Rule.R2_WINDOW_CLOSED],
            finding=finding,
        )

    # R3 — recoverable things never earn an interruption.
    if not finding.irreversible_after_deadline:
        return GateDecision(
            verdict=Verdict.SILENT,
            reason=f"R3: consequence is reversible. {RULE_TEXT[Rule.R3_RECOVERABLE]}",
            finding=finding,
        )

    # R4 — irreversible, but there is nothing for the student to decide.
    declined = ""
    if not finding.needs_human_choice:
        chain = auto_chain(finding)
        if chain is not None and set(chain) <= AUTO_ACT_PERMITTED:
            return GateDecision(
                verdict=Verdict.AUTO_ACT,
                reason=f"R4: irreversible, no judgement required; Compass ran "
                f"{' then '.join(chain)}. " + RULE_TEXT[Rule.R4_NO_CHOICE],
                finding=finding,
            )
        # The report claims no judgement is needed, but the resolution is not
        # one Compass is authorised to carry out alone. When those two disagree,
        # the cautious reading wins: asking costs three seconds, guessing costs
        # the student something she cannot get back. Fall through to R5/R6 so an
        # undecided-but-not-yet-urgent situation still stays quiet.
        declined = (
            "Compass judged this to have one obvious resolution, but that "
            "resolution is not one it is allowed to make on your behalf — so it "
            "is asking you rather than doing it."
        )

    # R5 — real one-way door, but still far enough out to be a "watch".
    if days is None or days > horizon_days:
        shown = "unknown" if days is None else f"{days} day(s)"
        return GateDecision(
            verdict=Verdict.SILENT,
            reason=f"R5: {shown} until the last safe action "
            f"(horizon {horizon_days}). " + RULE_TEXT[Rule.R5_TOO_EARLY],
            finding=finding,
        )

    # R6 — irreversible + a real choice + inside the horizon. This is the only
    # path to the student's attention in the entire system.
    prefix = f"R6: irreversible in {days} day(s) and the choice is yours. "
    return GateDecision(
        verdict=Verdict.SURFACE,
        reason=(f"{declined} Asking is the safe reading of that conflict. {prefix}"
                if declined else prefix) + RULE_TEXT[Rule.R6_ONE_WAY_DOOR],
        finding=finding,
    )


def decide_all(
    findings: list[Finding],
    today: date,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> list[GateDecision]:
    """Run the gate over a batch, most urgent first.

    Sorting is by *urgency of the one-way door*, not by severity label — a
    "critical" thing with six months of runway should not outrank a "medium"
    thing whose window shuts on Friday.
    """

    decisions = [decide(f, today, horizon_days, min_confidence) for f in findings]

    def sort_key(d: GateDecision):
        # Surfaced things first, then auto-actions (recorded, not shown), then silence.
        rank = {
            Verdict.SURFACE: 0,
            Verdict.AUTO_ACT: 1,
            Verdict.SILENT: 2,
        }[d.verdict]
        days = (
            d.finding.days_until_last_safe_action
            if d.finding and d.finding.days_until_last_safe_action is not None
            else 10**6
        )
        return (rank, days)

    return sorted(decisions, key=sort_key)
