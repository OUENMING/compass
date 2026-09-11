"""Talk to the deployed Compass, from wherever you happen to be.

The local CLI (``python -m compass.agents.compass``) imports the package and
runs everything in this process. This one does not: it posts a payload to the
AgentCore runtime in ``eu-west-1`` and prints what comes back. Same agent, same
dataset, same gate — the only difference is that the code is on the other side
of an HTTPS call, which is exactly the thing worth being able to demonstrate.

Why this file exists next to the CLI
------------------------------------
``agentcore invoke`` is the natural way to poke a deployed agent, and it works
here for questions: ``agentcore invoke "when is the W deadline?"`` arrives as a
prompt and Compass answers it. What it cannot do is send a *structured* payload,
because it always wraps whatever you give it in ``{"prompt": ...}``. A sweep
needs ``{"action": "sweep"}`` to arrive intact, and a decision needs the finding
it is deciding on. So the two actions that matter most to this project are the
two the vendor CLI cannot reach, and this module is the small amount of code
that closes the gap.

It is also the honest way to show the deployed agent doing work. A screenshot of
a chat reply proves a model answered; ``remote sweep`` proves the gate ran, the
verdicts came back, and the receipts exist — on the real endpoint.

Sessions
--------
AgentCore gives every session its own microVM and its own ``/tmp``, so a session
is the unit of state: the sweep's writable copy of the dataset lives and dies
with it. A ``decide`` therefore has to name the session its ``sweep`` ran in, or
it will be deciding against a pristine dataset instead of the one it just read.
Every call prints the session id it used, and ``--session`` takes one back.

Nothing here is needed to run Compass locally, and nothing here is imported by
the agent. It is a client.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from typing import Any

# The runtime name as it appears in the AgentCore control plane, i.e. what
# `agentcore status` prints. Used only when neither --arn nor COMPASS_RUNTIME_ARN
# says otherwise, so a renamed deployment is a flag away rather than a patch.
RUNTIME_NAME = "compass_Compass"

DEFAULT_REGION = "eu-west-1"


def _control(region: str):
    import boto3

    return boto3.client("bedrock-agentcore-control", region_name=region)


def _data(region: str):
    import boto3

    return boto3.client("bedrock-agentcore", region_name=region)


def runtime_arn(region: str = DEFAULT_REGION, explicit: str | None = None) -> str:
    """Find the deployed runtime's ARN.

    Three sources, in order of how much they should be trusted: the caller's
    ``--arn``, then ``COMPASS_RUNTIME_ARN`` for scripted use, then the control
    plane. The lookup is by name so that redeploying — which mints a new ARN
    every time — does not invalidate anything checked in or written down.

    Deliberately not read from ``agentcore/.cli/deployed-state.json``: that file
    is the vendor CLI's private bookkeeping, and a client that depends on it
    breaks the first time the CLI changes its mind about the format.
    """
    if explicit:
        return explicit.strip()
    from_env = os.environ.get("COMPASS_RUNTIME_ARN", "").strip()
    if from_env:
        return from_env

    wanted = os.environ.get("COMPASS_RUNTIME_NAME", RUNTIME_NAME).strip()
    found = [
        runtime["agentRuntimeArn"]
        for runtime in _control(region).list_agent_runtimes(maxResults=50).get(
            "agentRuntimes", []
        )
        if runtime.get("agentRuntimeName") == wanted
    ]
    if not found:
        raise LookupError(
            f"No AgentCore runtime named {wanted!r} in {region}. Deploy one with "
            f"`agentcore deploy`, or point at an existing one with --arn."
        )
    return found[0]


class Remote:
    """The deployed agent, as an object that answers four verbs.

    Each verb is one ``InvokeAgentRuntime`` call carrying one payload. The
    methods return the runtime's own JSON rather than a translated shape: the
    deployed agent answers in the same envelope the local one does, and
    re-wrapping that here would be a second contract to keep in sync.
    """

    def __init__(self, arn: str, region: str = DEFAULT_REGION, session: str | None = None):
        self.arn = arn
        self.region = region
        # The API requires at least 33 characters; a bare uuid4 is 36, so the
        # only reason to pad is to make hand-made ids legal.
        self.session = session or f"compass-{uuid.uuid4()}"

    def call(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = _data(self.region).invoke_agent_runtime(
            agentRuntimeArn=self.arn,
            payload=json.dumps(payload).encode(),
            runtimeSessionId=self.session,
        )
        body = response["response"].read().decode()
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"The runtime returned something that is not JSON: {body[:400]!r}"
            ) from exc

    def sweep(self) -> dict[str, Any]:
        return self.call({"action": "sweep"})

    def ask(self, question: str) -> dict[str, Any]:
        return self.call({"action": "ask", "question": question})

    def decide(self, finding: dict[str, Any], option_id: str) -> dict[str, Any]:
        return self.call(
            {"action": "decide", "finding": finding, "option_id": option_id}
        )

    def reset(self) -> dict[str, Any]:
        """Put the session's dataset back the way the bundle shipped it.

        The runtime is one session per visitor, so this matters less than it
        sounds: close the session and the next one is already clean. It exists
        for the case where someone clears a hold and wants to see it come back
        without waiting out the session.
        """
        return self.call({"action": "reset"})


def _flatten(sweep: dict[str, Any]) -> list[dict[str, Any]]:
    """Every finding a person can act on, in the order the sweep reported them.

    Surfaced first, because those are the ones waiting on a choice; handled ones
    follow because their receipts are worth being able to re-read.
    """
    return [d["finding"] for d in sweep.get("surfaced", [])] + [
        d["finding"] for d in sweep.get("handled", [])
    ]


def _find(reference: str, sweep: dict[str, Any]) -> dict[str, Any]:
    """Resolve a ``--decide`` argument against a sweep response.

    Accepts either the position the report printed (``--decide 1``) or the
    finding's own id, because both are reasonable things to reach for and only
    one of them is stable. Ids are written by the model on every sweep, so the
    same finding can be named differently on two runs; the position cannot move,
    because the report and this function walk the same list in the same order.

    That is a deliberately unglamorous answer to a real seam: the sweep is the
    only place a finding exists, so the client addresses findings by where they
    appeared rather than by pretending they have a durable key.
    """
    findings = _flatten(sweep)
    if reference.isdigit():
        index = int(reference)
        if not 1 <= index <= len(findings):
            raise LookupError(
                f"There is no finding {index} in that sweep; it has {len(findings)}."
            )
        return findings[index - 1]

    for finding in findings:
        if finding.get("id") == reference:
            return finding
    raise LookupError(
        f"No finding {reference!r} in that sweep. Available: "
        + ", ".join(
            f"{i + 1}:{f.get('id')}" for i, f in enumerate(findings)
        )
    )


def _option(reference: str, finding: dict[str, Any]) -> str | None:
    """Resolve a ``--option`` argument, by the number printed or by its id.

    Same reasoning as ``_find``: option ids are the model's invention and change
    between runs, while the order the report printed them in does not. Returns
    ``None`` after explaining itself, so the caller can exit non-zero without
    raising past the user.
    """
    options = finding.get("options", [])
    if reference.isdigit():
        index = int(reference)
        if not 1 <= index <= len(options):
            print(
                f"{finding.get('id')} has {len(options)} option(s), not an option "
                f"numbered {index}.",
                file=sys.stderr,
            )
            return None
        return options[index - 1]["id"]

    if any(option.get("id") == reference for option in options):
        return reference

    print(
        f"Finding {finding.get('id')!r} has no option {reference!r} (known: "
        + ", ".join(option.get("id", "?") for option in options)
        + ").",
        file=sys.stderr,
    )
    return None


def _report_sweep(result: dict[str, Any]) -> None:
    """Print a sweep the way a person reads one: what it wants, then what it did."""
    if not result.get("ok"):
        print(f"the runtime refused: {result.get('error')}", file=sys.stderr)
        return

    print(f"{result.get('today')} — {result.get('summary')}\n")

    def show(label: str, decisions: list[dict[str, Any]], verbose: bool) -> None:
        for decision in decisions:
            finding = decision["finding"]
            position = next(
                i + 1 for i, f in enumerate(_flatten(result)) if f is finding
            )
            print(f"  [{position}] {label}: {finding['title']}")
            if verbose:
                # The numbers come from the finding, not from the sentence below
                # it. A model wrote the rationale; the deadline, the countdown
                # and the confidence were computed, and they are the parts a
                # person should act on.
                days = finding.get("days_until_last_safe_action")
                print(
                    f"          by {finding.get('deadline')}"
                    f" ({days} day(s) left)"
                    f"  ·  severity {finding.get('severity')}"
                    f"  ·  confidence {finding.get('confidence')}"
                )
                print(f"          why: {decision['reason']}")
                for i, option in enumerate(finding.get("options", []), start=1):
                    print(f"          -> {i}. {option['id']}: {option['label']}")
                print(f"          choose with: --decide {position} --option 1")

    show("surfaced", result.get("surfaced", []), True)
    show("handled", result.get("handled", []), False)
    for decision in result.get("silent", []):
        print(f"  [--] passed over: {decision['title']}")

    if result.get("receipts"):
        print("\nReceipts:")
        for receipt in result["receipts"]:
            print(f"  [{receipt.get('detail', {}).get('confirmation', '?')}] {receipt['summary']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="compass-remote",
        description="Run Compass's four verbs against the deployed AgentCore runtime.",
    )
    parser.add_argument("--arn", default=None,
                        help="Runtime ARN. Defaults to a lookup by name.")
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--session", default=None,
                        help="Reuse a session. A decide must share its sweep's session.")
    parser.add_argument("--ask", metavar="QUESTION", default=None,
                        help="Ask a question instead of sweeping.")
    parser.add_argument("--decide", metavar="POSITION", default=None,
                        help="Carry out a choice: the number the sweep report printed "
                             "for that finding, or its id. Needs --from and --option.")
    parser.add_argument("--option", metavar="OPTION_ID", default=None,
                        help="Which option to carry out. Required with --decide.")
    parser.add_argument("--from", dest="source", metavar="SWEEP_JSON", default=None,
                        help="A sweep response saved with --json, to take the finding from.")
    parser.add_argument("--reset", action="store_true",
                        help="Restore the session's dataset to its shipped state.")
    parser.add_argument("--json", action="store_true", help="Emit the raw response.")
    args = parser.parse_args(argv)

    try:
        arn = runtime_arn(args.region, args.arn)
    except Exception as exc:  # noqa: BLE001 — this is a client; say what broke
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    remote = Remote(arn, args.region, args.session)
    # Always on stderr, so `--json` stays machine-readable on stdout while a
    # person still sees which session to pass to `decide`.
    print(f"session {remote.session}", file=sys.stderr)

    if args.decide:
        if not args.option:
            parser.error("--decide needs --option, the id of the option to carry out.")
        if not args.source:
            parser.error(
                "--decide needs --from, the sweep it is deciding on. A decision is "
                "only meaningful against the findings it was shown."
            )
        with open(args.source) as handle:
            sweep = json.load(handle)
        try:
            finding = _find(args.decide, sweep)
        except LookupError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        option = _option(args.option, finding)
        if option is None:
            return 2
        result = remote.decide(finding, option)
    elif args.reset:
        result = remote.reset()
    elif args.ask:
        result = remote.ask(args.ask)
    else:
        result = remote.sweep()

    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1

    if not result.get("ok"):
        print(f"the runtime refused: {result.get('error')}", file=sys.stderr)
        return 1

    if args.ask:
        print(result.get("answer", ""))
    elif args.decide or args.reset:
        for receipt in result.get("receipts", []):
            print(f"[{receipt.get('detail', {}).get('confirmation', '?')}] {receipt['summary']}")
        if args.reset:
            print("dataset restored to its shipped state.")
    else:
        _report_sweep(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
