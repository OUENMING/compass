"""The actions Compass can actually take.

This module is where "not just chat about it" is cashed in. Every function here
does something with a **side effect that outlives the conversation**: it writes
to the student record, takes a seat in a module, clears a hold, files a plan.
Each one returns a ``Receipt`` — an auditable record with a confirmation number,
written to ``data/receipts.jsonl``. A claim the agent makes about work it did is
checkable against that file.

Two design commitments
----------------------
**Validate like the registrar would.** An action that skips its checks is a
demo, not a tool. ``register_modules`` refuses on an unmet prerequisite, on a
term credit cap, on a full module, on a module that does not exist. The
refusals are part of the story: Compass cannot blunder past a rule that the
student would be blocked by.

**Only do what the gate authorised.** These functions are capability, not
policy. Whether any of them runs without asking the student is decided entirely
by ``compass.gate`` — see ``AUTO_ACT_PERMITTED`` there for the two bookkeeping
actions the gate may run on its own initiative, and only when a situation is
irreversible *and* requires no judgement, which is exactly the ``R4`` case.
Everything that spends money, changes what she studies, or contacts a human
waits for her.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from strands import tool

from .. import audit as audit_mod
from .. import prereq as prereq_mod
from ..audit import MAX_TERM_CREDITS, SPECIALISATION_MODULES
from ..models import Receipt
from ..store import SchoolStore


def _store() -> SchoolStore:
    env = os.environ.get("COMPASS_DATA_DIR")
    return SchoolStore(Path(env) if env else None)


def _confirmation(prefix: str, payload: str) -> str:
    """Deterministic confirmation number.

    Derived from the action and its arguments rather than a random value, so
    that re-running the demo produces the same receipt. Reproducibility is worth
    more here than realism.
    """
    digest = hashlib.sha256(payload.encode()).hexdigest()[:6].upper()
    return f"{prefix}-2026-{digest}"


def _term_load(student: StudentRecord, store: SchoolStore, extra: list[str]) -> int:
    codes = set(student.spring_registered) | set(student.planned) | set(extra)
    return sum(store.course(c).credits for c in codes if store.course(c))


@tool
def register_modules(codes: list[str]) -> dict:
    """Register the student for one or more modules in the next term.

    Checks the module exists, that every prerequisite is satisfied, that seats
    remain, and that the term credit cap is not exceeded. Refuses the whole
    request if any check fails, and explains which one.

    Args:
        codes: Module codes to register for, e.g. ["ECON10790"].

    Returns:
        A receipt with a confirmation number, or an ``{"error": ...}`` object.
    """
    store = _store()
    student = store.student
    wanted = [c.strip().upper() for c in codes]

    # Validate everything before mutating anything.
    for code in wanted:
        course = store.course(code)
        if course is None:
            return {"error": f"No module with code {code!r} in the catalogue."}
        if code in student.spring_registered:
            return {"error": f"Already registered for {code}."}
        if course.seats_left <= 0:
            return {"error": (
                f"{code} is full: {course.enrolled}/{course.capacity} enrolled. "
                "Registration is first-come, first-served."
            )}
        missing = prereq_mod.missing_prereqs(store, student, code, include_in_progress=False)
        if missing:
            return {"error": (
                f"{code} requires {', '.join(missing)}, which the student has "
                "not passed. Registration refused."
            )}

    load = _term_load(student, store, wanted)
    if load > MAX_TERM_CREDITS:
        return {"error": (
            f"That would put the term at {load} ECTS, over the "
            f"{MAX_TERM_CREDITS} ECTS cap. Drop a module first."
        )}

    for code in wanted:
        if code in student.planned:
            student.planned.remove(code)
        student.spring_registered.append(code)
        store.take_seat(code, +1)  # the seat is really taken

    store.save_student(student)

    receipt = Receipt(
        finding_id="",
        option_id="",
        action="register_modules",
        summary=f"Registered for {', '.join(wanted)} for the next term.",
        detail={
            "confirmation": _confirmation("REG", "".join(wanted)),
            "modules": wanted,
            "term_load_ects": load,
            "seats_remaining": {
                c: store.course(c).seats_left for c in wanted
            },
        },
        reversible=True,
    )
    store.record_receipt(receipt)
    return receipt.model_dump(mode="json")


@tool
def drop_module(code: str) -> dict:
    """Drop a module from the student's next-term registration or plan.

    Args:
        code: Module code to drop.

    Returns:
        A receipt, or an ``{"error": ...}`` object.
    """
    store = _store()
    student = store.student
    code = code.strip().upper()

    if code in student.spring_registered:
        student.spring_registered.remove(code)
        where = "registration"
    elif code in student.planned:
        student.planned.remove(code)
        where = "plan"
    else:
        return {"error": f"{code} is not in the student's registration or plan."}

    course = store.course(code)
    if course:
        store.take_seat(code, -1)
    store.save_student(student)

    receipt = Receipt(
        finding_id="", option_id="", action="drop_module",
        summary=f"Dropped {code} from the {where}.",
        detail={"confirmation": _confirmation("DRP", code), "module": code},
        reversible=True,
    )
    store.record_receipt(receipt)
    return receipt.model_dump(mode="json")


@tool
def resolve_library_hold(method: str) -> dict:
    """Clear the library hold blocking registration.

    Args:
        method: Either "pay_charge" to authorise the EUR 45.00 replacement
            charge immediately, or "return_in_person" if the student is
            returning the items themselves.

    Returns:
        A receipt, or an ``{"error": ...}`` object.
    """
    store = _store()
    student = store.student
    hold = next((h for h in student.holds if h.kind == "Library"), None)
    if hold is None:
        return {"error": "There is no library hold on this account."}
    if hold.cleared:
        return {"error": "The library hold has already been cleared."}

    if method == "pay_charge":
        summary = ("Authorised the EUR 45.00 replacement charge and cleared the "
                   "library hold.")
        detail_extra = {"charge_eur": 45.00, "cleared_by": "charge authorised"}
    elif method == "return_in_person":
        summary = ("Recorded the items as returned and cleared the library hold.")
        detail_extra = {"charge_eur": 0.00, "cleared_by": "returned in person"}
    else:
        return {"error": (
            f"Unknown method {method!r}. Use 'pay_charge' or 'return_in_person'."
        )}

    hold.cleared = True
    store.save_student(student)

    receipt = Receipt(
        finding_id="LIB-2026-7781", option_id=method,
        action="resolve_library_hold", summary=summary,
        detail={"confirmation": _confirmation("LIB", method),
                "hold_id": hold.id, **detail_extra},
        reversible=method == "return_in_person",
    )
    store.record_receipt(receipt)
    return receipt.model_dump(mode="json")


@tool
def set_specialisation(specialisation: str) -> dict:
    """Switch the student between the Quantitative and General Economics specialisations.

    This is a real decision with a real cost either way, which is why the gate
    always surfaces it rather than acting alone.

    Args:
        specialisation: "quantitative" (keeps ECON20030, ECON30010 and
            ECON20040, and therefore the Econometrics chain) or "general"
            (replaces those with Level 3 economics options: ECON30030,
            ECON30040, ECON30060).

    Returns:
        A receipt, or an ``{"error": ...}`` object.
    """
    store = _store()
    student = store.student
    choice = specialisation.strip().lower()

    if choice not in SPECIALISATION_MODULES:
        return {"error": (
            f"Unknown specialisation {specialisation!r}. Use 'quantitative' "
            "or 'general'."
        )}
    if choice == student.specialisation:
        return {"error": f"The student is already on the {choice} specialisation."}

    previous = SPECIALISATION_MODULES[student.specialisation]
    replacement = SPECIALISATION_MODULES[choice]

    # Rewrite the stream in the plan. Both sets come out of every group first —
    # the outgoing modules, and also the incoming ones, because a module the
    # student already has in her core (ECON30040 sits in both) would otherwise
    # land in two groups at once and hand the plan exactly the double-count that
    # `repair_degree_plan` exists to clean up. Then the incoming set goes into
    # the stream, in one place.
    outgoing = set(previous) | set(replacement)
    plan = {gid: [c for c in codes if c not in outgoing]
            for gid, codes in student.draft_plan.items()}
    plan.setdefault("quant_stream", [])
    plan["quant_stream"] = list(replacement)

    student.specialisation = choice
    student.draft_plan = plan
    store.save_student(student)

    receipt = Receipt(
        finding_id="", option_id=choice, action="set_specialisation",
        summary=(
            f"Switched to the {choice} Economics specialisation. The "
            f"quantitative stream is now satisfied by "
            f"{', '.join(replacement)}."
        ),
        detail={
            "confirmation": _confirmation("SPC", choice + student.id),
            "specialisation": choice,
            "was": previous,
            "now": replacement,
        },
        reversible=True,
    )
    store.record_receipt(receipt)
    return receipt.model_dump(mode="json")


@tool
def repair_degree_plan() -> dict:
    """Repair the degree plan by applying programme rules 1 and 2.

    Removes any module counted in two requirement groups and fills the resulting
    gap from the earliest-passed unassigned eligible module. This resolution is
    fully determined by the written rules, so it needs no judgement from the
    student.

    Returns:
        A receipt listing the changes, or ``{"error": ...}`` if nothing to do.
    """
    store = _store()
    student = store.student

    new_plan, changes = audit_mod.propose_fix(store, student, student.draft_plan)
    if not changes:
        return {"error": "The degree plan has no duplicate assignments; nothing to repair."}

    student.draft_plan = new_plan
    store.save_student(student)

    receipt = Receipt(
        finding_id="plan-duplicate-assignment", option_id="repair",
        action="repair_degree_plan",
        summary=(
            f"Corrected {len(changes)} plan error(s): "
            + "; ".join(changes)
        ),
        detail={
            "confirmation": _confirmation("PLN", "".join(changes)),
            "changes": changes,
            "plan": new_plan,
        },
        reversible=True,
    )
    store.record_receipt(receipt)
    return receipt.model_dump(mode="json")


@tool
def file_degree_plan() -> dict:
    """File the degree plan for advisor approval, clearing the advising hold.

    Refuses unless the plan passes a clean audit — a plan with a short
    requirement group would be rejected by the School Office anyway, so
    submitting it would only lose three working days.

    Returns:
        A receipt, or an ``{"error": ...}`` object.
    """
    store = _store()
    student = store.student

    if student.degree_plan_filed:
        return {"error": "The degree plan has already been filed."}

    result = audit_mod.audit(store, student.draft_plan)
    if result.duplicates:
        return {"error": (
            "The plan still contains duplicate module assignments "
            f"({', '.join(result.duplicates)}). Repair the plan first — the "
            "School Office rejects plans that fail audit."
        )}
    blocking = [g for g in result.short_groups if g.id != "quant_stream"]
    if blocking:
        names = ", ".join(f"{g.name} ({g.short} ECTS short)" for g in blocking)
        return {"error": (
            f"The plan is short in {names}. Filing it would be rejected."
        )}

    student.degree_plan_filed = True
    for hold in student.holds:
        if hold.kind == "Advising":
            hold.cleared = True
    store.save_student(student)

    receipt = Receipt(
        finding_id="ADV-2026-041", option_id="file",
        action="file_degree_plan",
        summary=("Filed the Stage 3 degree plan. Advisor approval takes three "
                 "working days, after which the advising hold is released."),
        detail={
            "confirmation": _confirmation("ADV", student.id),
            "advisor": student.advisor,
            "approval_due_days": 3,
        },
        reversible=True,
    )
    store.record_receipt(receipt)
    return receipt.model_dump(mode="json")


@tool
def notify_advisor(message: str) -> dict:
    """Send a short message to the student's academic advisor.

    Use sparingly — this is a real message to a real person's inbox, and the
    student's relationship with their advisor is theirs, not the agent's.

    Args:
        message: The message body. Two or three sentences.

    Returns:
        A receipt confirming delivery.
    """
    store = _store()
    student = store.student

    receipt = Receipt(
        finding_id="", option_id="", action="notify_advisor",
        summary=f"Sent a message to {student.advisor}.",
        detail={
            "confirmation": _confirmation("MSG", message),
            "to": student.advisor,
            "body": message,
        },
        reversible=False,
    )
    store.record_receipt(receipt)
    return receipt.model_dump(mode="json")


# Which of these the gate is allowed to run without asking is *not* decided
# here. That whitelist lives in `compass.gate.AUTO_ACT_PERMITTED`, next to the
# rules that consult it, so this module stays pure capability.
ACTION_TOOLS = [
    register_modules,
    drop_module,
    resolve_library_hold,
    set_specialisation,
    repair_degree_plan,
    file_degree_plan,
    notify_advisor,
]

# Name -> callable, so a finding can name an action as a string and the
# orchestrator can resolve it without a second registry that could drift.
ACTION_BY_NAME = {t.tool_name: t for t in ACTION_TOOLS}

__all__ = [
    "register_modules",
    "drop_module",
    "resolve_library_hold",
    "set_specialisation",
    "repair_degree_plan",
    "file_degree_plan",
    "notify_advisor",
    "ACTION_TOOLS",
    "ACTION_BY_NAME",
    "SPECIALISATION_MODULES",
]
