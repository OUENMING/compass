"""Compass — the orchestrator.

This module is where the project's central claim is cashed in: **the decision to
interrupt a person is made by code, not by a model.**

The shape of a sweep
--------------------
1. ``sentinel`` reads the institution's rules and this student's record and
   reports facts (``Finding``).
2. ``compass.gate`` — plain Python, six numbered rules — turns those facts into
   verdicts: stay silent, act and leave a receipt, or interrupt.
3. Anything the gate marked ``AUTO_ACT`` is executed here, for real, against the
   student record. Anything it marked ``SURFACE`` is put in front of her with
   its options and its reason; nothing happens until she picks one.

Note what is *not* here: nothing asks a model "should I bother her?" That
question is answered by ``gate.decide``, which is deterministic, citable, and
covered by tests. The agents below are used for the parts that genuinely need
language — reading a regulation, tracing a prerequisite chain, explaining a rule
in plain English — and for nothing else.

The second, quieter property: a sweep is idempotent in the sense that matters.
Once a situation is resolved, the next sweep does not mention it again. An agent
that keeps re-raising things it already fixed trains you to ignore it, which is
the failure this whole design exists to avoid.
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
from datetime import date
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field

from ..gate import auto_chain, decide_all
from ..llm import build_model, describe
from ..models import Finding, GateDecision, Option, Receipt, Verdict
from ..store import SchoolStore, default_data_dir
from ..tools.actions import ACTION_BY_NAME
from ..tools.registry import agent_tools
from .explainer import build_explainer
from .pathfinder import build_pathfinder
from .sentinel import build_sentinel, scan


class CompassError(RuntimeError):
    """Raised when a requested action is unknown or refused by the tools."""


# The router has no school-data tools of its own, and that is deliberate: it
# cannot answer from memory because it has nothing to answer from. All it can do
# is hand the question to a specialist that reads the actual records.
ROUTER_PROMPT = """\
You are Compass, the agent that sits between one student and her university's
rules. You have two specialists:

* **pathfinder** — for "what happens if", "can I still", "how much longer",
  "is that module still open", and any question about the *cost of a choice*.
* **explainer** — for "what is", "what does this mean", "why is", and any
  question about the *meaning of a rule, notice, term or block*.

Pick one and hand the question to it. If a question genuinely needs both, ask
both, then join the answers — but that is rare, and asking one specialist the
right question beats asking two the wrong one.

You have no other tools. You cannot look anything up yourself, so do not try:
route the question, then return what the specialist said. Return it as your own
answer — do not mention that a specialist produced it, do not refer to
"the pathfinder" or "the explainer" in the third person, do not add a closing
sentence of your own. Do not add advice, do not pick an option for her, and do
not soften a specialist's "no" into a "maybe".
"""

def _option(finding: Finding, option_id: str | None) -> Option:
    """Pick the option to execute: the named one, the recommended one, or the only one."""
    if option_id is not None:
        match = next((o for o in finding.options if o.id == option_id), None)
        if match is None:
            known = ", ".join(o.id for o in finding.options) or "none"
            raise CompassError(
                f"Finding {finding.id!r} has no option {option_id!r} (known: {known})."
            )
        return match
    if not finding.options:
        raise CompassError(f"Finding {finding.id!r} offers no option to execute.")
    return next((o for o in finding.options if o.recommended), finding.options[0])


class Sweep(BaseModel):
    """The full result of one pass, including the silences."""

    today: date
    decisions: list[GateDecision] = Field(default_factory=list)
    # Receipts from actions the gate authorised on its own initiative.
    receipts: list[Receipt] = Field(default_factory=list)

    @property
    def surfaced(self) -> list[GateDecision]:
        return [d for d in self.decisions if d.verdict is Verdict.SURFACE]

    @property
    def auto_acted(self) -> list[GateDecision]:
        return [d for d in self.decisions if d.verdict is Verdict.AUTO_ACT]

    @property
    def silent(self) -> list[GateDecision]:
        return [d for d in self.decisions if d.verdict is Verdict.SILENT]

    def summary(self) -> str:
        return (
            f"{len(self.decisions)} finding(s): "
            f"{len(self.surfaced)} surfaced, "
            f"{len(self.auto_acted)} handled, "
            f"{len(self.silent)} deliberately passed over."
        )


class Compass:
    """One student, one institution, one sweep loop.

    ``use_mcp`` switches the school-data transport between the FastMCP server
    (subprocess, the deployment path) and the in-process Strands tools (the test
    path). Everything above the transport is identical, which is the point.
    """

    def __init__(
        self,
        data_dir: Path | str | None = None,
        model=None,
        use_mcp: bool = True,
        on_event: Callable[[dict], None] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir else default_data_dir()
        # The action tools resolve the store from the environment, because the
        # model calls them by name and cannot pass a directory. Setting it here
        # is what keeps the agent's writes and this object's reads on one file.
        os.environ["COMPASS_DATA_DIR"] = str(self.data_dir)
        self.model = model if model is not None else build_model()
        self.use_mcp = use_mcp
        self.on_event = on_event

    def _emit(self, stage: str, **fields) -> None:
        if self.on_event is not None:
            self.on_event({"stage": stage, **fields})

    # -- reading ----------------------------------------------------------

    def sweep(self, findings: list[Finding] | None = None) -> Sweep:
        """Run one full pass: observe, judge, and act on what needs no asking."""
        today = SchoolStore(self.data_dir).today
        self._emit("sweep_start", today=today.isoformat())

        if findings is None:
            self._emit("sentinel_start")
            with agent_tools(use_mcp=self.use_mcp, data_dir=self.data_dir) as tools:
                findings = scan(build_sentinel(self.model, tools))
            self._emit("sentinel_done", findings=len(findings))

        sweep = Sweep(today=today, decisions=decide_all(findings, today))
        self._emit(
            "gate_done",
            findings=len(findings),
            surfaced=len(sweep.surfaced),
            auto_acted=len(sweep.auto_acted),
            silent=len(sweep.silent),
        )

        for decision in sweep.auto_acted:
            try:
                receipts = self.execute(decision)
            except CompassError as exc:
                # The gate only authorises actions it can complete alone, so
                # this should be unreachable. If it happens, the honest move is
                # to stop acting, not to retry something the rules refused.
                self._emit("auto_act_refused", finding_id=decision.finding.id,
                           error=str(exc))
                continue
            sweep.receipts.extend(receipts)
            self._emit("auto_acted", finding_id=decision.finding.id,
                       receipts=[r.model_dump(mode="json") for r in receipts])

        self._emit("sweep_done", summary=sweep.summary())
        return sweep

    # -- writing ----------------------------------------------------------

    def execute(self, decision: GateDecision, option_id: str | None = None) -> list[Receipt]:
        """Carry out a decision's option, running `after` first when it has one.

        This is the only place a side effect happens without a person in the
        loop, and it is reached from exactly two places: the gate's ``R4``
        verdict, and a student clicking a button on a card. Both have a finding
        behind them that says what the action is and why.
        """
        if decision.finding is None:
            raise CompassError("Cannot execute a decision with no finding attached.")

        option = _option(decision.finding, option_id)
        chain = [a for a in (option.after, option.action) if a]

        # A student may authorise anything the tools can do; the gate may not.
        # Refuse an `after` that names something Compass cannot perform rather
        # than silently skipping a step the option's label promised.
        unknown = [name for name in chain if name not in ACTION_BY_NAME]
        if unknown:
            raise CompassError(
                f"Action(s) {', '.join(repr(u) for u in unknown)} are not "
                f"available to Compass."
            )

        receipts: list[Receipt] = []
        # `after` is the forced first step and takes no arguments of its own —
        # `action_args` belongs to `action`. The only sequence the programme
        # rules force is repair-then-file, and repair needs nothing.
        steps = [(option.after, {})] if option.after else []
        steps.append((option.action, option.action_args or {}))
        for name, args in steps:
            receipts.append(Receipt(**self._call(name, args)))
        return receipts

    @staticmethod
    def _call(name: str, args: dict) -> dict:
        """Invoke one action tool, turning every failure into a CompassError.

        The arguments come from the model, so a wrong parameter name is a
        realistic failure. Check the signature here rather than letting Python
        raise a TypeError somewhere the UI would show as a 500: a mis-named
        argument should read as "this action was refused", which is what it is.
        """
        tool = ACTION_BY_NAME[name]
        try:
            signature = inspect.signature(tool)
            signature.bind(**args)
        except TypeError as exc:
            raise CompassError(
                f"{name} was called with the wrong arguments ({exc})."
            ) from exc

        result = tool(**args)
        if isinstance(result, dict) and "error" in result:
            raise CompassError(result["error"])
        return result

    # -- answering --------------------------------------------------------

    def ask(self, question: str) -> str:
        """Answer a free-form question by routing it to a specialist agent.

        This is the conversational half of Compass, and it is deliberately
        downstream of the gate: a person asking a question has already given
        Compass their attention, so there is nothing to decide about whether to
        interrupt. Which is why this is the only entry point with no gate in it.
        """
        from strands import Agent  # local: the router exists only for this call

        with agent_tools(use_mcp=self.use_mcp, data_dir=self.data_dir) as tools:
            pathfinder = build_pathfinder(self.model, tools)
            explainer = build_explainer(self.model, tools)
            router = Agent(
                model=self.model,
                name="compass",
                description="Routes a student's question to the right specialist.",
                system_prompt=ROUTER_PROMPT,
                tools=[pathfinder, explainer],
                callback_handler=None,
            )
            return str(router(question)).strip()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _print_sweep(sweep: Sweep, verbose: bool) -> None:
    print(f"Compass sweep — {sweep.today.isoformat()}")
    print(f"  {sweep.summary()}\n")

    labels = {
        Verdict.SURFACE: ("SURFACE", "the student is asked"),
        Verdict.AUTO_ACT: ("ACT", "handled, receipt left"),
        Verdict.SILENT: ("SILENT", "deliberately not raised"),
    }
    for decision in sweep.decisions:
        finding = decision.finding
        if finding is None:
            continue
        label, _ = labels[decision.verdict]
        print(f"[{label:7s}] {finding.id}")
        print(f"          {finding.title}")
        if verbose:
            print(f"          {decision.reason}")
            for option in finding.options:
                star = "*" if option.recommended else " "
                steps = " then ".join(a for a in (option.after, option.action) if a)
                print(f"            {star} {option.id}: {option.label}  [{steps}]")
        print()

    if sweep.receipts:
        print("Receipts:")
        for receipt in sweep.receipts:
            number = receipt.detail.get("confirmation", "?")
            print(f"  [{number}] {receipt.summary}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="compass", description="Run one Compass sweep and report what it did."
    )
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument(
        "--direct-tools",
        action="store_true",
        help="Skip the MCP subprocess and call the school tools in-process.",
    )
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show the gate's reason and each option.")
    parser.add_argument("--json", action="store_true", help="Emit the sweep as JSON.")
    parser.add_argument("--ask", metavar="QUESTION", default=None,
                        help="Answer a free-form question instead of sweeping.")
    args = parser.parse_args(argv)

    compass = Compass(data_dir=args.data_dir, use_mcp=not args.direct_tools)

    if args.ask:
        print(compass.ask(args.ask))
        return 0

    if args.verbose:
        print(f"model: {describe()}\n")
    sweep = compass.sweep()

    if args.json:
        print(json.dumps(sweep.model_dump(mode="json"), indent=2))
    else:
        _print_sweep(sweep, args.verbose)

    # Exit code says what a caller can assert on: 0 when nothing needed the
    # student, 10 when at least one card went up.
    return 10 if sweep.surfaced else 0


if __name__ == "__main__":
    raise SystemExit(main())
