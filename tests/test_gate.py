"""The gate — the one part of Compass that decides whether a person is interrupted.

These are the tests that matter most, because everything the project claims
about "Compass stays silent by default" is a statement about this file. Two
properties are asserted harder than the rest:

* **Determinism.** The same finding and the same date give the same verdict,
  always. That is what separates a policy from a vibe, and it is why the demo
  can be recorded and the tests can be real tests.
* **The asymmetry.** Silence is the cheap default and a missed irreversible
  deadline is the expensive one — but only when the decision is genuinely the
  student's. When there is nothing to decide, Compass acts; when it is not
  authorised to act, it asks rather than assuming.
"""

from __future__ import annotations

from datetime import date

import pytest

from compass.gate import (
    AUTO_ACT_PERMITTED,
    DEFAULT_HORIZON_DAYS,
    DEFAULT_MIN_CONFIDENCE,
    Rule,
    auto_chain,
    decide,
    decide_all,
)
from compass.models import Finding, Option, Severity, Verdict

TODAY = date(2026, 9, 28)


def make_finding(**overrides) -> Finding:
    """A finding that would surface, so each test can change exactly one thing."""
    base = dict(
        id="F-test",
        title="A module you need has closed",
        what_happened="ECON30010 filled on Friday.",
        consequence_if_ignored="You cannot take the module this year.",
        severity=Severity.HIGH,
        irreversible_after_deadline=True,
        deadline=date(2026, 10, 23),
        days_until_last_safe_action=25,
        needs_human_choice=True,
        confidence=0.9,
        options=[
            Option(id="a", label="Take the alternative", consequence="Different module",
                   action="register_modules", recommended=True),
        ],
    )
    base.update(overrides)
    return Finding(**base)


# --------------------------------------------------------------------------
# R1–R6
# --------------------------------------------------------------------------


def test_r6_is_the_only_path_to_the_student():
    """Irreversible + a real choice + inside the horizon is the one card."""
    decision = decide(make_finding(), TODAY)
    assert decision.verdict is Verdict.SURFACE
    assert decision.reason.startswith("R6")


def test_r1_never_acts_on_a_guess():
    decision = decide(make_finding(confidence=DEFAULT_MIN_CONFIDENCE - 0.01), TODAY)
    assert decision.verdict is Verdict.SILENT
    assert decision.reason.startswith("R1")


def test_r2_says_nothing_when_the_window_has_already_closed():
    """A missed deadline has no decision left in it. Distress without a move."""
    decision = decide(make_finding(days_until_last_safe_action=-3), TODAY)
    assert decision.verdict is Verdict.SILENT
    assert decision.reason.startswith("R2")


def test_r3_passes_over_anything_recoverable():
    decision = decide(make_finding(irreversible_after_deadline=False), TODAY)
    assert decision.verdict is Verdict.SILENT
    assert decision.reason.startswith("R3")


def test_r4_acts_when_there_is_nothing_to_decide():
    decision = decide(
        make_finding(
            needs_human_choice=False,
            options=[Option(id="fix", label="Repair the plan", consequence="Fixed",
                            action="repair_degree_plan", recommended=True)],
        ),
        TODAY,
    )
    assert decision.verdict is Verdict.AUTO_ACT
    assert decision.reason.startswith("R4")


def test_r5_stays_quiet_on_a_real_door_that_is_still_far_away():
    decision = decide(make_finding(days_until_last_safe_action=DEFAULT_HORIZON_DAYS + 1),
                      TODAY)
    assert decision.verdict is Verdict.SILENT
    assert decision.reason.startswith("R5")


def test_r5_treats_an_unknown_deadline_as_not_yet_urgent():
    decision = decide(make_finding(deadline=None, days_until_last_safe_action=None),
                      TODAY)
    assert decision.verdict is Verdict.SILENT
    assert decision.reason.startswith("R5")


def test_exactly_on_the_horizon_surfaces():
    """The boundary belongs to the student, not to the silence."""
    decision = decide(make_finding(days_until_last_safe_action=DEFAULT_HORIZON_DAYS),
                      TODAY)
    assert decision.verdict is Verdict.SURFACE


def test_rule_order_is_by_cost_of_being_wrong():
    """A guess that is also closed is reported as a guess, not as closed."""
    decision = decide(
        make_finding(confidence=0.1, days_until_last_safe_action=-30), TODAY
    )
    assert decision.reason.startswith("R1")


# --------------------------------------------------------------------------
# The authorization guard
# --------------------------------------------------------------------------


def test_r4_refuses_an_action_the_gate_is_not_authorised_to_run():
    """The interesting failure: the report says "no choice", the fix is spendy.

    Registering a student for a module takes a real seat. If Sentinel claims no
    judgement is needed, the gate must not take that as permission — it must
    read the action and ask.
    """
    decision = decide(
        make_finding(
            needs_human_choice=False,
            options=[Option(id="reg", label="Register", consequence="A seat",
                            action="register_modules", recommended=True)],
        ),
        TODAY,
    )
    assert decision.verdict is Verdict.SURFACE
    assert "not one it is allowed to make on your behalf" in decision.reason


def test_r4_refuses_an_action_that_does_not_exist():
    """An invented action name must never be executable."""
    decision = decide(
        make_finding(
            needs_human_choice=False,
            options=[Option(id="x", label="Do the thing", consequence="?",
                            action="delete_student_record", recommended=True)],
        ),
        TODAY,
    )
    assert decision.verdict is Verdict.SURFACE


def test_a_refused_r4_still_respects_the_horizon():
    """If the fix isn't ours to make, the finding is a normal one-way door."""
    decision = decide(
        make_finding(
            needs_human_choice=False,
            days_until_last_safe_action=200,
            options=[Option(id="reg", label="Register", consequence="A seat",
                            action="register_modules", recommended=True)],
        ),
        TODAY,
    )
    assert decision.verdict is Verdict.SILENT
    assert decision.reason.startswith("R5")


def test_every_permitted_action_is_actually_offered_by_a_real_option():
    """The whitelist is meaningless if it names actions nothing can request."""
    from compass.tools.actions import ACTION_BY_NAME

    assert AUTO_ACT_PERMITTED <= set(ACTION_BY_NAME), (
        "AUTO_ACT_PERMITTED names an action the tool layer does not have."
    )


def test_auto_chain_prefers_the_recommendation():
    finding = make_finding(
        needs_human_choice=False,
        options=[
            Option(id="other", label="B", consequence="c", action="drop_module"),
            Option(id="fix", label="A", consequence="c",
                   action="file_degree_plan", after="repair_degree_plan",
                   recommended=True),
        ],
    )
    assert auto_chain(finding) == ["repair_degree_plan", "file_degree_plan"]


def test_auto_chain_is_none_when_there_is_no_option():
    assert auto_chain(make_finding(options=[])) is None


# --------------------------------------------------------------------------
# Determinism and ordering
# --------------------------------------------------------------------------


def test_the_same_finding_always_gets_the_same_verdict():
    finding = make_finding()
    verdicts = {decide(finding, TODAY).reason for _ in range(50)}
    assert len(verdicts) == 1


def test_ordering_is_by_urgency_not_by_severity_label():
    """A 'critical' thing with six months of runway is not the urgent one."""
    loud_but_distant = make_finding(
        id="loud", severity=Severity.CRITICAL, days_until_last_safe_action=40
    )
    quiet_but_friday = make_finding(
        id="soon", severity=Severity.LOW, days_until_last_safe_action=2
    )
    order = [d.finding.id for d in decide_all([loud_but_distant, quiet_but_friday], TODAY)]
    assert order == ["soon", "loud"]


def test_auto_acted_sort_between_surfaced_and_silent():
    surfaced = make_finding(id="s")
    handled = make_finding(
        id="a", needs_human_choice=False,
        options=[Option(id="f", label="Fix", consequence="c",
                        action="repair_degree_plan", recommended=True)],
    )
    passed_over = make_finding(id="q", irreversible_after_deadline=False)
    order = [d.finding.id for d in decide_all([passed_over, handled, surfaced], TODAY)]
    assert order == ["s", "a", "q"]


def test_silence_always_carries_a_reason():
    """Absence of output is not an explanation. Every silent verdict cites a rule."""
    findings = [
        make_finding(confidence=0.1),
        make_finding(days_until_last_safe_action=-1),
        make_finding(irreversible_after_deadline=False),
        make_finding(days_until_last_safe_action=300),
    ]
    for decision in decide_all(findings, TODAY):
        assert decision.verdict is Verdict.SILENT
        assert decision.reason.startswith("R")
        assert len(decision.reason) > 40


@pytest.mark.parametrize("rule", list(Rule))
def test_every_rule_has_student_facing_text(rule):
    from compass.gate import RULE_TEXT

    assert RULE_TEXT[rule].strip().endswith(".")
