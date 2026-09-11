"""The orchestrator — observe, judge, act, and do nothing else.

These tests never call a model. ``Compass.sweep`` takes findings directly, so the
whole observe→judge→act pipeline can be exercised with findings written by hand.
That is deliberate: the interesting behaviour is not "did the LLM say something
sensible", it is "given a report, does Compass do exactly and only what the gate
authorised".

The single most important assertion in this file is that **a SURFACE verdict has
no side effects at all**. If that ever stops holding, the project's premise is
gone: an agent that acts on things it said it would ask about is worse than one
that never acts.
"""

from __future__ import annotations

from datetime import date

import pytest

from compass.agents.compass import Compass, CompassError
from compass.models import Finding, Option, Receipt, Severity, Verdict

TODAY = date(2026, 9, 28)


def finding(**overrides) -> Finding:
    base = dict(
        id="F-test",
        title="The library block escalates on Friday",
        what_happened="Three Short Loan items are overdue and the block reaches registration.",
        consequence_if_ignored="Registration stays locked until the Fees Office clears it.",
        severity=Severity.CRITICAL,
        irreversible_after_deadline=True,
        deadline=date(2026, 10, 5),
        days_until_last_safe_action=7,
        needs_human_choice=True,
        confidence=0.9,
        options=[
            Option(id="return", label="Return the items in person",
                   consequence="No charge, costs you a trip",
                   action="resolve_library_hold",
                   action_args={"method": "return_in_person"}, recommended=True),
            Option(id="pay", label="Authorise the EUR 45 charge",
                   consequence="Costs 45 euro", action="resolve_library_hold",
                   action_args={"method": "pay_charge"}),
        ],
    )
    base.update(overrides)
    return Finding(**base)


@pytest.fixture
def compass(data_dir) -> Compass:
    # `model=object()` is not a stub to be proud of, but it is honest: no code
    # path under test touches the model, and building a real one would make the
    # test suite depend on a network. Findings are injected instead.
    return Compass(data_dir=data_dir, model=object(), use_mcp=False)


def receipts_in(data_dir) -> list[dict]:
    path = data_dir / "receipts.jsonl"
    if not path.exists():
        return []
    import json
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# --------------------------------------------------------------------------
# The promise: nothing happens until she says so
# --------------------------------------------------------------------------


def test_a_surfaced_finding_changes_nothing_at_all(compass, store, data_dir):
    sweep = compass.sweep(findings=[finding()])

    assert [d.verdict for d in sweep.decisions] == [Verdict.SURFACE]
    assert sweep.receipts == []
    assert receipts_in(data_dir) == []
    assert store.student.active_holds, "the hold must still be there"


def test_a_silent_finding_changes_nothing_either(compass, data_dir):
    quiet = finding(irreversible_after_deadline=False)
    sweep = compass.sweep(findings=[quiet])

    assert [d.verdict for d in sweep.decisions] == [Verdict.SILENT]
    assert receipts_in(data_dir) == []


def test_the_sweep_always_reports_the_silences(compass):
    """Silence has to be inspectable. Otherwise it is indistinguishable from a bug."""
    sweep = compass.sweep(findings=[finding(), finding(id="quiet",
                                                      irreversible_after_deadline=False)])
    assert len(sweep.decisions) == 2
    assert len(sweep.silent) == 1
    assert sweep.silent[0].reason.startswith("R3")


# --------------------------------------------------------------------------
# The other half: what needs no judgement gets done
# --------------------------------------------------------------------------


def test_an_authorised_action_is_really_executed(compass, store, data_dir):
    clean = finding(
        id="F-plan",
        needs_human_choice=False,
        options=[Option(id="fix", label="Repair the plan",
                        consequence="Bookkeeping only",
                        action="repair_degree_plan", recommended=True)],
    )
    sweep = compass.sweep(findings=[clean])

    assert [d.verdict for d in sweep.decisions] == [Verdict.AUTO_ACT]
    assert [r.action for r in sweep.receipts] == ["repair_degree_plan"]
    assert [r["action"] for r in receipts_in(data_dir)] == ["repair_degree_plan"]
    from compass import audit as audit_mod
    assert audit_mod.find_duplicates(store.student.draft_plan) == {}


def test_a_forced_sequence_runs_in_order(compass, store, data_dir):
    sequenced = finding(
        id="F-file",
        needs_human_choice=False,
        options=[Option(id="file", label="Repair the plan and file it",
                        consequence="Two steps the rules fix",
                        action="file_degree_plan", after="repair_degree_plan",
                        recommended=True)],
    )
    sweep = compass.sweep(findings=[sequenced])

    assert [r.action for r in sweep.receipts] == [
        "repair_degree_plan", "file_degree_plan"
    ]
    assert store.student.degree_plan_filed is True


def test_an_unauthorised_action_surfaces_instead_of_running(compass, store, data_dir):
    """The gate's refusal is the safety property; the orchestrator must honour it."""
    spendy = finding(
        id="F-spend",
        needs_human_choice=False,
        options=[Option(id="pay", label="Pay the charge", consequence="45 euro",
                        action="resolve_library_hold",
                        action_args={"method": "pay_charge"}, recommended=True)],
    )
    sweep = compass.sweep(findings=[spendy])

    assert [d.verdict for d in sweep.decisions] == [Verdict.SURFACE]
    assert receipts_in(data_dir) == []
    assert store.student.active_holds, "Compass must not have spent her money"


# --------------------------------------------------------------------------
# Executing on her say-so
# --------------------------------------------------------------------------


def test_execute_runs_the_option_the_student_clicked(compass, store, data_dir):
    sweep = compass.sweep(findings=[finding()])
    decision = sweep.surfaced[0]

    result = compass.execute(decision, "pay")
    assert isinstance(result[0], Receipt)
    assert result[0].detail["charge_eur"] == 45.00, "she chose to pay, not to travel"
    assert [h.kind for h in store.student.active_holds] == ["Advising"]
    assert result[0].reversible is False


def test_execute_without_an_option_id_takes_the_recommendation(compass, store):
    sweep = compass.sweep(findings=[finding()])
    receipt = compass.execute(sweep.surfaced[0])[0]
    assert receipt.option_id == "return_in_person"


def test_execute_refuses_an_option_that_does_not_exist(compass):
    sweep = compass.sweep(findings=[finding()])
    with pytest.raises(CompassError, match="no option"):
        compass.execute(sweep.surfaced[0], "fly_to_the_moon")


def test_execute_refuses_an_action_compass_does_not_have(compass):
    rogue = finding(
        id="F-rogue",
        options=[Option(id="x", label="Expel yourself", consequence="?",
                        action="delete_student_record", recommended=True)],
    )
    sweep = compass.sweep(findings=[rogue])
    with pytest.raises(CompassError, match="not available to Compass"):
        compass.execute(sweep.surfaced[0])


def test_execute_refuses_mis_named_arguments(compass):
    """A model that gets a parameter name wrong gets a refusal, not a traceback."""
    typo = finding(
        id="F-typo",
        options=[Option(id="x", label="Switch", consequence="?",
                        action="set_specialisation",
                        action_args={"name": "general"}, recommended=True)],
    )
    sweep = compass.sweep(findings=[typo])
    with pytest.raises(CompassError, match="wrong arguments"):
        compass.execute(sweep.surfaced[0])


def test_a_refused_action_reaches_the_student_as_a_reason(compass):
    """The registrar's refusal is the point, so it must be shown, not swallowed."""
    prereq = finding(
        id="F-prereq",
        options=[Option(id="reg", label="Register for Econometrics II",
                        consequence="Takes the module",
                        action="register_modules",
                        action_args={"codes": ["ECON30010"]}, recommended=True)],
    )
    sweep = compass.sweep(findings=[prereq])
    with pytest.raises(CompassError) as excinfo:
        compass.execute(sweep.surfaced[0])
    assert "ECON20030" in str(excinfo.value)


def test_a_failed_auto_action_does_not_take_the_sweep_down(compass, data_dir):
    """If the world moved under us, the sweep reports and carries on."""
    stale = finding(
        id="F-stale",
        needs_human_choice=False,
        options=[Option(id="fix", label="Repair the plan",
                        consequence="Bookkeeping",
                        action="repair_degree_plan", recommended=True)],
    )
    compass.sweep(findings=[stale])          # first sweep fixes it
    second = compass.sweep(findings=[stale])  # second sweep finds nothing to fix

    assert second.receipts == []
    assert len(receipts_in(data_dir)) == 1


# --------------------------------------------------------------------------
# Shape
# --------------------------------------------------------------------------


def test_summary_counts_every_bucket(compass):
    sweep = compass.sweep(findings=[
        finding(),
        finding(id="quiet", irreversible_after_deadline=False),
        finding(id="fix", needs_human_choice=False,
                options=[Option(id="r", label="Repair", consequence="c",
                                action="repair_degree_plan", recommended=True)]),
    ])
    assert "3 finding(s)" in sweep.summary()
    assert "1 surfaced" in sweep.summary()
    assert "1 handled" in sweep.summary()
    assert "1 deliberately passed over" in sweep.summary()


def test_progress_events_describe_the_whole_sweep(data_dir):
    seen: list[str] = []
    c = Compass(data_dir=data_dir, model=object(), use_mcp=False,
                on_event=lambda e: seen.append(e["stage"]))
    c.sweep(findings=[finding()])

    assert seen[0] == "sweep_start"
    assert "gate_done" in seen
    assert seen[-1] == "sweep_done"
