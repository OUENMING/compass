"""The deployed contract — ``app/Compass/main.py``.

The runtime module is loaded from its file rather than imported, because it is
an AgentCore entrypoint sitting outside the package. What is worth testing here
is not the plumbing; it is the two promises the deployed agent makes:

* a sweep reports **every** bucket, including the silences, so "it did nothing"
  is inspectable rather than indistinguishable from a crash, and
* a bad payload produces an answer that says so, because an invocation that
  raises is an invocation nobody can debug from the outside.

The model is never called. ``handle`` is a pure function of a payload and an
agent, so these tests hand it a stand-in and assert on what comes back.
"""

from __future__ import annotations

import importlib.util
from datetime import date

import pytest

from compass.agents.compass import Compass, Sweep
from compass.gate import decide_all
from compass.models import Finding, Option, Severity

pytest.importorskip("bedrock_agentcore", reason="deployment extra not installed")

RUNTIME = (
    __import__("pathlib").Path(__file__).resolve().parents[1]
    / "app" / "Compass" / "main.py"
)


def _load_runtime():
    spec = importlib.util.spec_from_file_location("compass_runtime_main", RUNTIME)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runtime():
    return _load_runtime()


def finding(**overrides) -> Finding:
    base = dict(
        id="F-test",
        title="The library block escalates on Friday",
        what_happened="Three Short Loan items are overdue.",
        consequence_if_ignored="Registration stays locked.",
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
        ],
    )
    base.update(overrides)
    return Finding(**base)


class StubAgent:
    """A real orchestrator for execution, with the model call taken out."""

    def __init__(self, data_dir, findings):
        self.data_dir = data_dir
        self._real = Compass(data_dir=data_dir, model=object(), use_mcp=False)
        self._findings = findings

    def sweep(self):
        today = self._real.sweep(findings=[]).today
        return Sweep(today=today, decisions=decide_all(self._findings, today))

    def execute(self, decision, option_id=None):
        return self._real.execute(decision, option_id)

    def ask(self, question):
        return f"answered: {question}"


@pytest.fixture
def agent(data_dir):
    return StubAgent(data_dir, [finding()])


# --------------------------------------------------------------------------
# sweep
# --------------------------------------------------------------------------


def test_a_sweep_reports_the_silences_too(runtime, agent):
    """Otherwise "it stayed quiet" and "it fell over" look the same from outside."""
    agent._findings = [
        finding(),
        finding(id="F-quiet", irreversible_after_deadline=False),
    ]
    out = runtime.handle({"action": "sweep"}, agent)

    assert out["ok"] is True
    assert out["summary"]
    assert [c["finding"]["id"] for c in out["surfaced"]] == ["F-test"]
    assert [c["finding_id"] for c in out["silent"]] == ["F-quiet"]
    assert out["silent"][0]["reason"].startswith("R3")


def test_a_surfaced_finding_carries_the_options_and_nothing_was_run(runtime, agent, store):
    out = runtime.handle({"action": "sweep"}, agent)

    options = out["surfaced"][0]["finding"]["options"]
    assert [o["id"] for o in options] == ["return"]
    assert out["receipts"] == []
    assert store.student.active_holds, "a sweep must not act on what it surfaced"


def test_the_default_action_is_a_sweep(runtime, agent):
    assert runtime.handle({}, agent)["ok"] is True


# --------------------------------------------------------------------------
# decide
# --------------------------------------------------------------------------


def test_deciding_executes_the_option_that_was_chosen(runtime, agent, store, data_dir):
    sweep = runtime.handle({"action": "sweep"}, agent)
    chosen = sweep["surfaced"][0]["finding"]

    out = runtime.handle(
        {"action": "decide", "finding": chosen, "option_id": "return"}, agent
    )

    assert out["ok"] is True
    # The receipt names the method actually used, not the card's option id —
    # the audit trail is about what happened, not what was clicked.
    assert out["receipts"][0]["option_id"] == "return_in_person"
    assert out["receipts"][0]["detail"]["charge_eur"] == 0.00
    assert [h.kind for h in store.student.active_holds] == ["Advising"]


def test_deciding_without_a_finding_is_a_bad_request_not_a_crash(runtime, agent):
    out = runtime.handle({"action": "decide", "option_id": "return"}, agent)

    assert out["ok"] is False
    assert out["kind"] == "bad_request"
    assert "finding" in out["error"]


def test_a_refusal_by_the_rules_is_reported_as_a_refusal(runtime, agent):
    """ECON30010 sits behind an unmet prerequisite. The registrar says no."""
    agent._findings = [
        finding(
            id="F-prereq",
            options=[Option(id="reg", label="Register", consequence="Takes it",
                            action="register_modules",
                            action_args={"codes": ["ECON30010"]}, recommended=True)],
        )
    ]
    sweep = runtime.handle({"action": "sweep"}, agent)
    out = runtime.handle(
        {"action": "decide", "finding": sweep["surfaced"][0]["finding"]}, agent
    )

    assert out["ok"] is False
    assert out["kind"] == "refused"
    assert "ECON20030" in out["error"]


# --------------------------------------------------------------------------
# ask, and the edges
# --------------------------------------------------------------------------


def test_ask_needs_a_question(runtime, agent):
    assert runtime.handle({"action": "ask", "question": "When is the W deadline?"},
                          agent)["answer"].startswith("answered:")
    out = runtime.handle({"action": "ask", "question": "   "}, agent)
    assert out["ok"] is False and out["kind"] == "bad_request"


def test_an_unknown_action_is_refused_with_the_list_of_real_ones(runtime, agent):
    out = runtime.handle({"action": "delete_everything"}, agent)

    assert out["ok"] is False
    assert "'sweep'" in out["error"] and "'decide'" in out["error"]


def test_the_entrypoint_returns_an_answer_even_when_it_fails(runtime, monkeypatch, data_dir):
    """The runtime must stay answerable. An exception is an unhelpful answer."""
    def explode(*_args, **_kwargs):
        raise RuntimeError("the dataset is on fire")

    monkeypatch.setattr(runtime, "Compass", explode)
    out = runtime.invoke({"action": "sweep"})

    assert out["ok"] is False
    assert out["kind"] == "error"
    assert "on fire" in out["error"]
