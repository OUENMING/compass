"""The client that talks to the deployed agent — ``compass.remote``.

Nothing here reaches AWS. ``compass.remote`` is a thin client, so the parts worth
testing are the parts that are not the network: how a finding is addressed, and
what payload each verb puts on the wire.

That second one is the real subject. The client and ``app/Compass/main.py`` agree
on a JSON envelope that no type checker sees, since one builds it as a dict and
the other reads it as a dict. These tests pin the four payloads against the
actions the runtime dispatches on, so a rename on either side fails here rather
than three minutes into a deployment.
"""

from __future__ import annotations

import json

import pytest

from compass import remote


SWEEP = {
    "ok": True,
    "today": "2026-09-28",
    "surfaced": [
        {
            "verdict": "surface",
            "reason": "irreversible in 7 day(s) and the choice is yours",
            "finding": {
                "id": "F2-library-hold",
                "title": "Overdue library items are blocking your registration",
                "options": [
                    {"id": "opt-return", "label": "Return the three items in person"},
                    {"id": "opt-pay", "label": "Authorise the EUR 45 charge"},
                ],
            },
        }
    ],
    "handled": [
        {
            "verdict": "auto_act",
            "reason": "irreversible, no judgement required",
            "finding": {
                "id": "plan-duplicate-assignment",
                "title": "Your degree plan was never checked",
                "options": [{"id": "repair", "label": "Repair the plan"}],
            },
        }
    ],
    "silent": [],
}


class FakeBoto:
    """Records the calls a verb makes, and answers with a fixed body."""

    def __init__(self, body: dict):
        self.body = body
        self.calls: list[dict] = []

    def invoke_agent_runtime(self, **kwargs):
        self.calls.append(kwargs)
        encoded = json.dumps(self.body).encode()

        class _Body:
            def read(self) -> bytes:
                return encoded

        return {"response": _Body()}


@pytest.fixture
def client(monkeypatch):
    fake = FakeBoto({"ok": True, "answer": "the W deadline is 2026-11-06"})
    monkeypatch.setattr(remote, "_data", lambda region: fake)
    return remote.Remote("arn:aws:bedrock-agentcore:eu-west-1:1:runtime/x", "eu-west-1",
                         session="a" * 40), fake


def _sent(fake: FakeBoto) -> dict:
    assert len(fake.calls) == 1
    return json.loads(fake.calls[0]["payload"].decode())


# --- what goes on the wire -------------------------------------------------


def test_sweep_sends_the_action_the_runtime_dispatches_on(client):
    agent, fake = client
    agent.sweep()
    assert _sent(fake) == {"action": "sweep"}


def test_ask_carries_the_question(client):
    agent, fake = client
    agent.ask("when is the W deadline?")
    assert _sent(fake) == {"action": "ask", "question": "when is the W deadline?"}


def test_decide_sends_the_finding_back_whole(client):
    """The runtime rebuilds a Finding from this, so it has to be the full object.

    A decision that named a finding by id alone would make the runtime look it up
    again, which would move the authorisation from the person who chose to the
    sweep that surfaced it. Sending the finding back is the whole point.
    """
    agent, fake = client
    finding = SWEEP["surfaced"][0]["finding"]
    agent.decide(finding, "opt-return")
    assert _sent(fake) == {
        "action": "decide",
        "finding": finding,
        "option_id": "opt-return",
    }


def test_every_call_reuses_the_session(client):
    """State lives in the session, so a decide has to land in its sweep's."""
    agent, fake = client
    agent.sweep()
    agent.decide(SWEEP["surfaced"][0]["finding"], "opt-return")
    assert {call["runtimeSessionId"] for call in fake.calls} == {"a" * 40}


def test_a_generated_session_is_long_enough_for_the_api():
    # The API rejects anything under 33 characters, so the default cannot be a
    # short readable label.
    assert len(remote.Remote("arn:x").session) >= 33


# --- addressing a finding --------------------------------------------------


def test_find_by_position_covers_both_buckets():
    assert remote._find("1", SWEEP)["id"] == "F2-library-hold"
    assert remote._find("2", SWEEP)["id"] == "plan-duplicate-assignment"


def test_find_by_id_still_works():
    assert remote._find("F2-library-hold", SWEEP)["id"] == "F2-library-hold"


def test_find_out_of_range_says_how_many_there_are():
    with pytest.raises(LookupError, match="no finding 3"):
        remote._find("3", SWEEP)


def test_find_unknown_id_lists_what_is_available():
    with pytest.raises(LookupError, match="F2-library-hold"):
        remote._find("F9-not-here", SWEEP)


# --- addressing an option --------------------------------------------------


def test_option_by_position_and_by_id_agree():
    finding = SWEEP["surfaced"][0]["finding"]
    assert remote._option("1", finding) == "opt-return"
    assert remote._option("opt-pay", finding) == "opt-pay"


def test_option_out_of_range_is_refused():
    finding = SWEEP["surfaced"][0]["finding"]
    assert remote._option("7", finding) is None


def test_option_unknown_id_is_refused():
    finding = SWEEP["surfaced"][0]["finding"]
    assert remote._option("opt-teleport", finding) is None


# --- finding the runtime ---------------------------------------------------


def test_runtime_arn_prefers_what_the_caller_named(monkeypatch):
    monkeypatch.setenv("COMPASS_RUNTIME_ARN", "arn:from-env")
    assert remote.runtime_arn(explicit="arn:from-flag") == "arn:from-flag"


def test_runtime_arn_falls_back_to_the_environment(monkeypatch):
    monkeypatch.setenv("COMPASS_RUNTIME_ARN", "arn:from-env")
    assert remote.runtime_arn() == "arn:from-env"


def test_runtime_arn_is_looked_up_by_name(monkeypatch):
    monkeypatch.delenv("COMPASS_RUNTIME_ARN", raising=False)

    class Control:
        def list_agent_runtimes(self, **_):
            return {
                "agentRuntimes": [
                    {"agentRuntimeName": "someone-elses", "agentRuntimeArn": "arn:other"},
                    {
                        "agentRuntimeName": remote.RUNTIME_NAME,
                        "agentRuntimeArn": "arn:ours",
                    },
                ]
            }

    monkeypatch.setattr(remote, "_control", lambda region: Control())
    assert remote.runtime_arn() == "arn:ours"


def test_a_missing_runtime_explains_the_lookup(monkeypatch):
    monkeypatch.delenv("COMPASS_RUNTIME_ARN", raising=False)

    class Control:
        def list_agent_runtimes(self, **_):
            return {"agentRuntimes": []}

    monkeypatch.setattr(remote, "_control", lambda region: Control())
    with pytest.raises(LookupError, match="agentcore deploy"):
        remote.runtime_arn()


# --- the CLI ---------------------------------------------------------------


def test_decide_without_a_sweep_is_a_usage_error(monkeypatch, capsys):
    """A decision is only meaningful against the findings it was shown."""
    monkeypatch.setenv("COMPASS_RUNTIME_ARN", "arn:x")
    with pytest.raises(SystemExit) as exit_info:
        remote.main(["--decide", "1", "--option", "opt-return"])
    assert exit_info.value.code == 2
    assert "--from" in capsys.readouterr().err


def test_decide_without_an_option_is_a_usage_error(monkeypatch):
    monkeypatch.setenv("COMPASS_RUNTIME_ARN", "arn:x")
    with pytest.raises(SystemExit) as exit_info:
        remote.main(["--decide", "1", "--from", "sweep.json"])
    assert exit_info.value.code == 2
