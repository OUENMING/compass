"""Compass on Amazon Bedrock AgentCore Runtime.

This is the deployed face of the same agent that runs locally. Nothing about
Compass's behaviour lives here: the entrypoint validates a payload, calls into
``compass.agents.compass``, and serialises the answer. If the deployed version
ever disagreed with the local one, that would be a bug in this file.

Why the file exists at all
--------------------------
AgentCore Runtime gives an agent a session, a health check, and an invokable
endpoint, but it does not give it anywhere to keep files. The dataset Compass
reads is shipped inside the code bundle, and the bundle is treated as read-only:
the first invocation of a session copies it into a writable directory and points
``COMPASS_DATA_DIR`` at the copy, so the student record and the seat counts
behave exactly as they do on a laptop. Within a session that copy is real state
— registering for a module takes a seat, dropping it gives the seat back — and
it disappears with the session, which is the correct lifetime for a demo whose
data is fabricated.

Two invocations, one contract
-----------------------------
``POST /invocations`` with ``{"action": "sweep"}`` runs a full pass and returns
the gate's verdicts. With ``{"action": "decide", "finding": ..., "option_id":
...}`` it carries out the option a person chose.

The asymmetry between those two is the whole design, and it is why ``decide``
takes the finding back from the caller rather than looking it up. **Unattended
work is authorised by the gate; chosen work is authorised by the choice.** A
sweep can only run the two bookkeeping actions ``compass.gate`` whitelists. A
decision carries a human's pick, so it executes what was picked — and the
receipt records which option it was. Neither path can be reached from the other.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

# The deployment bundle is built from the repository root (`codeLocation: "./"`
# in agentcore/agentcore.json), so `src/`, `data/` and `app/` all sit at the
# bundle root. Import the package from the checkout rather than requiring an
# install step inside the build.
_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
if _SRC.is_dir():
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    # The school-data MCP server runs as a subprocess — `python -m
    # compass.tools.school_mcp_server` — and a child process inherits the
    # environment, not this interpreter's sys.path. Without this line the
    # deployed agent would come up holding tools it cannot start.
    _existing = os.environ.get("PYTHONPATH", "")
    if str(_SRC) not in _existing.split(os.pathsep):
        os.environ["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(_SRC), _existing) if part
        )

from bedrock_agentcore.runtime import BedrockAgentCoreApp  # noqa: E402

from compass.agents.compass import Compass, CompassError  # noqa: E402
from compass.models import Finding, GateDecision, Verdict  # noqa: E402

log = logging.getLogger("compass.runtime")

app = BedrockAgentCoreApp()

SHIPPED_DATA = _REPO / "data"


def data_dir() -> Path:
    """A writable copy of the shipped dataset, made once per session.

    Returns the value of ``COMPASS_DATA_DIR`` untouched when it is set, so the
    runtime can be pointed at a mounted volume without changing this file.
    """
    explicit = os.environ.get("COMPASS_DATA_DIR")
    if explicit:
        return Path(explicit)

    scratch = Path(os.environ.get("COMPASS_SCRATCH_DIR", "/tmp/compass-data"))
    if not (scratch / "meta.json").exists():
        if not (SHIPPED_DATA / "meta.json").exists():
            raise RuntimeError(
                f"No dataset at {SHIPPED_DATA}. The code bundle must include "
                f"the repository's data/ directory."
            )
        scratch.mkdir(parents=True, exist_ok=True)
        for source in SHIPPED_DATA.glob("*.json"):
            shutil.copy2(source, scratch / source.name)
        log.info("prepared writable dataset at %s", scratch)

    os.environ["COMPASS_DATA_DIR"] = str(scratch)
    return scratch


def _finding_from(payload: dict) -> Finding:
    """Rebuild a finding the caller received, or explain why it cannot be."""
    raw = payload.get("finding")
    if not isinstance(raw, dict):
        raise ValueError(
            "action 'decide' needs the 'finding' object it is deciding on, "
            "exactly as the sweep returned it."
        )
    try:
        return Finding(**raw)
    except Exception as exc:
        raise ValueError(f"that finding is not readable: {exc}") from exc


def handle(payload: dict, compass: Compass) -> dict:
    """The whole contract, as a pure function of the payload and an agent.

    Kept separate from the entrypoint so it can be tested without a runtime, a
    network, or a model: the tests pass a stand-in agent and assert on the shape
    and the refusals.

    Every failure that a caller could have caused comes back as a value, not an
    exception. Two different things can go wrong and they deserve different
    answers: a payload the runtime cannot make sense of is a *bad request*,
    while an action the programme rules forbid is a *refusal* — the same
    refusal a registrar would give, and worth showing the student verbatim.
    """
    try:
        return _dispatch(payload, compass)
    except CompassError as exc:
        return {"ok": False, "kind": "refused", "error": str(exc)}
    except ValueError as exc:
        return {"ok": False, "kind": "bad_request", "error": str(exc)}


def _dispatch(payload: dict, compass: Compass) -> dict:
    action = str(payload.get("action", "sweep")).strip().lower()

    if action == "sweep":
        sweep = compass.sweep()
        return {
            "ok": True,
            "today": sweep.today.isoformat(),
            "summary": sweep.summary(),
            "data_dir": str(compass.data_dir),
            # Every bucket is returned, including the silences. A deployed agent
            # that reports only what it did is unauditable; the point of the
            # gate is that the things it declined to do are inspectable too.
            "surfaced": [
                {
                    "verdict": d.verdict.value,
                    "reason": d.reason,
                    "finding": d.finding.model_dump(mode="json"),
                }
                for d in sweep.surfaced
            ],
            "handled": [
                {
                    "verdict": d.verdict.value,
                    "reason": d.reason,
                    "finding": d.finding.model_dump(mode="json"),
                }
                for d in sweep.auto_acted
            ],
            "silent": [
                {
                    "verdict": d.verdict.value,
                    "reason": d.reason,
                    "finding_id": d.finding.id,
                    "title": d.finding.title,
                }
                for d in sweep.silent
            ],
            "receipts": [r.model_dump(mode="json") for r in sweep.receipts],
        }

    if action == "decide":
        finding = _finding_from(payload)
        decision = GateDecision(
            verdict=Verdict.SURFACE,
            reason="the student chose this option",
            finding=finding,
        )
        option_id = payload.get("option_id")
        receipts = compass.execute(decision, option_id)
        return {
            "ok": True,
            "receipts": [r.model_dump(mode="json") for r in receipts],
        }

    if action == "ask":
        question = str(payload.get("question", "")).strip()
        if not question:
            raise ValueError("action 'ask' needs a non-empty 'question'.")
        return {"ok": True, "answer": compass.ask(question)}

    raise ValueError(
        f"unknown action {action!r}. Use 'sweep', 'decide' or 'ask'."
    )


@app.entrypoint
def invoke(payload: dict) -> dict:
    """AgentCore entrypoint.

    ``handle`` already turns everything the caller could have caused into a
    value. What is left here is the failure nobody planned for — no dataset, no
    credentials, a model that will not answer. Those still have to come back as
    something, because an entrypoint that raises gives the person invoking it a
    502 and nothing to act on.
    """
    try:
        return handle(payload, Compass(data_dir=data_dir(), use_mcp=True))
    except Exception as exc:  # noqa: BLE001 — the runtime must stay answerable
        log.exception("invocation failed")
        return {"ok": False, "kind": "error", "error": f"{type(exc).__name__}: {exc}"}


if __name__ == "__main__":
    # AgentCore terminates TLS and health-checks in front of this process; all
    # it has to do is listen on the port it is given.
    app.run(port=int(os.environ.get("PORT", "8080")))
