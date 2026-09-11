"""Deterministic analysis tools handed to the reasoning agents.

The split this module embodies is the project's central architectural claim:

* **The school data tools** (in ``school_tools`` / the MCP server) answer
  "what is true" — the catalogue, the record, the calendar, the notices.
* **These tools** answer "what does it add up to" — credit counts, prerequisite
  gaps, days remaining, term load.
* **The model** answers the one question neither can: "what does this *mean*
  for this student, and can it still be fixed?"

Anything that is arithmetic lives here, in Python, where it is exact and
repeatable. A model that is asked to count credits will eventually count them
wrong and sound certain about it, and for this audience a confidently wrong
credit count is the failure that costs a year.

Note on dates: "today" is the demo date stored in the dataset, not the wall
clock. The scenario is a specific week in the academic year, and every deadline
calculation has to agree with the calendar the student is looking at.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from strands import tool

from .. import audit as audit_mod
from .. import prereq as prereq_mod
from ..audit import SPECIALISATION_MODULES
from ..store import SchoolStore


def _store() -> SchoolStore:
    env = os.environ.get("COMPASS_DATA_DIR")
    return SchoolStore(Path(env) if env else None)


@tool
def today() -> dict:
    """Get the current date in the simulation and the next calendar deadlines.

    Returns:
        The current date plus the calendar events that have not yet closed,
        nearest first.
    """
    store = _store()
    now = store.today
    upcoming = []
    for event in store.calendar:
        ref = event.closes or event.opens
        if ref and ref >= now:
            upcoming.append({
                "event": event.name,
                "kind": event.kind,
                "opens": event.opens.isoformat() if event.opens else None,
                "closes": event.closes.isoformat() if event.closes else None,
                "days_until_close": (event.closes - now).days if event.closes else None,
                "notes": event.notes,
            })
    upcoming.sort(key=lambda e: e["closes"] or e["opens"] or "9999")
    return {"today": now.isoformat(), "upcoming": upcoming}


@tool
def days_from_today(iso_date: str) -> dict:
    """Count days from today to a date. Negative means the date has passed.

    Args:
        iso_date: A date in ISO form, e.g. "2026-10-23".

    Returns:
        ``{"days": int, "passed": bool}``.
    """
    store = _store()
    try:
        target = date.fromisoformat(iso_date)
    except ValueError:
        return {"error": f"{iso_date!r} is not an ISO date (YYYY-MM-DD)."}
    delta = (target - store.today).days
    return {"date": iso_date, "today": store.today.isoformat(),
            "days": delta, "passed": delta < 0}


@tool
def audit_degree_plan() -> dict:
    """Audit the student's degree plan against the programme requirements.

    Applies the written programme rules deterministically: counts credits per
    requirement group, finds modules assigned to more than one group, and lists
    modules the student has passed that are not assigned anywhere.

    Returns:
        Per-group awarded/required credits, any duplicate assignments, and any
        unassigned passed modules.
    """
    store = _store()
    student = store.student
    result = audit_mod.audit(store, student.draft_plan)
    return {
        "plan_filed": student.degree_plan_filed,
        "groups": [
            {
                "id": g.id, "name": g.name,
                "awarded": g.awarded, "required": g.required,
                "short": g.short, "met": g.met,
            }
            for g in result.groups
        ],
        "duplicate_assignments": result.duplicates,
        "unassigned_passed_modules": audit_mod.unassigned_modules(
            store, student, student.draft_plan
        ),
        "total_credits_earned": student.credits_earned,
    }


@tool
def check_module_eligibility(code: str) -> dict:
    """Check whether the student can take a module, and how the gap can close.

    Reports unmet prerequisites, remaining seats, and whether the missing
    prerequisite is something the student could still register for. This is the
    tool that turns "you are missing ECON10790" into "you are missing the one
    module the whole quantitative stream stands on".

    Args:
        code: Module code, e.g. "ECON20030".

    Returns:
        Eligibility detail, or ``{"error": ...}`` if the code is unknown.
    """
    store = _store()
    student = store.student
    course = store.course(code)
    if course is None:
        return {"error": f"No module with code {code!r} in the catalogue."}

    missing = prereq_mod.missing_prereqs(store, student, code)
    ok, explanation = prereq_mod.satisfiable(store, student, code)
    return {
        "code": code,
        "title": course.title,
        "credits": course.credits,
        "term": course.term.value,
        "seats_left": course.seats_left,
        "capacity": course.capacity,
        "enrolled": course.enrolled,
        "prerequisites": course.prerequisites,
        "unmet_prerequisites": missing,
        "eligible_today": not missing and course.seats_left > 0,
        "gap_can_still_be_closed": ok,
        "explanation": explanation,
    }


@tool
def trace_prerequisite_chain(code: str) -> dict:
    """Trace everything upstream of a module, and everything it unlocks.

    Args:
        code: Module code to trace, e.g. "ECON30010".

    Returns:
        The upstream prerequisite chain, the modules this one unlocks, and the
        credits sitting downstream of it.
    """
    store = _store()
    upstream = prereq_mod.chain_to(store, code)

    downstream: list[dict] = []
    frontier = [code]
    seen = {code}
    while frontier:
        current = frontier.pop()
        for child in prereq_mod.unlocks(store, current):
            if child.code in seen:
                continue
            seen.add(child.code)
            downstream.append({"code": child.code, "title": child.title,
                               "credits": child.credits, "level": child.level,
                               "requires": child.prerequisites})
            frontier.append(child.code)

    return {
        "code": code,
        "upstream_prerequisites": upstream,
        "unlocks": downstream,
        "downstream_credits": sum(d["credits"] for d in downstream),
    }


@tool
def term_load() -> dict:
    """Get the student's credit load per term, against the 30 ECTS cap.

    Returns:
        Credits currently registered and planned for the next term, with the
        headroom left before the cap.
    """
    store = _store()
    student = store.student

    def total(codes: list[str]) -> int:
        return sum(store.course(c).credits for c in codes if store.course(c))

    current = total(student.registered)
    nxt = total(sorted(set(student.planned) | set(student.spring_registered)))
    return {
        "current_term": {"modules": student.registered, "credits": current},
        "next_term": {
            "modules": sorted(set(student.planned) | set(student.spring_registered)),
            "registered": student.spring_registered,
            "planned": student.planned,
            "credits": nxt,
            "cap": audit_mod.MAX_TERM_CREDITS,
            "headroom": audit_mod.MAX_TERM_CREDITS - nxt,
        },
    }


@tool
def compare_specialisations() -> dict:
    """Compare what the two Economics specialisations actually cost this student.

    For each specialisation, lists the modules that would satisfy the
    quantitative stream, checks each one for unmet prerequisites and remaining
    seats, totals the credits still outstanding, and says whether the stream can
    be completed at all from where she stands today.

    This is the arithmetic behind a choice, not the choice. Which specialisation
    to take — and therefore which thing to give up — is the student's to make,
    which is why Compass surfaces it rather than picking one.

    Returns:
        One entry per specialisation plus which requirement group it fills.
    """
    store = _store()
    student = store.student
    group = next((g for g in store.requirements.groups if g.id == "quant_stream"), None)
    required = group.credits_required if group else 0
    passed_codes = prereq_mod.passed_codes(student)

    options: dict[str, dict] = {}
    for name, codes in SPECIALISATION_MODULES.items():
        modules = []
        credits_now = 0        # usable without taking anything extra first
        credits_with_detour = 0
        detours: list[str] = []
        for code in codes:
            course = store.course(code)
            if course is None:
                continue
            already_passed = code in passed_codes
            missing = [] if already_passed else prereq_mod.missing_prereqs(
                store, student, code
            )
            takeable = already_passed or (not missing and course.seats_left > 0)
            # `satisfiable` is the honest question: not "is it blocked today"
            # but "can the block still be cleared at all". Scenario 1 lives in
            # the gap between those two.
            closable, _ = (True, "") if not missing else prereq_mod.satisfiable(
                store, student, code
            )
            if takeable:
                credits_now += course.credits
            if takeable or closable:
                credits_with_detour += course.credits
            if missing and closable:
                detours.extend(
                    c for c in prereq_mod.chain_to(store, code)
                    if c not in passed_codes and c not in detours
                )
            modules.append({
                "code": code,
                "title": course.title,
                "credits": course.credits,
                "already_passed": already_passed,
                "unmet_prerequisites": missing,
                "seats_left": course.seats_left,
                "takeable_next_term": takeable,
                "gap_can_still_be_closed": closable,
                "already_in_plan": code in student.draft_plan.get("quant_stream", []),
            })

        options[name] = {
            "modules": modules,
            "credits_required": required,
            "credits_available_next_term": credits_now,
            "credits_available_with_detour": credits_with_detour,
            "shortfall_as_it_stands": max(required - credits_now, 0),
            "shortfall_after_closing_gaps": max(required - credits_with_detour, 0),
            "extra_modules_needed_first": detours,
            "stream_completable": credits_with_detour >= required,
        }

    return {
        "current_specialisation": student.specialisation,
        "requirement_group": "quant_stream",
        "options": options,
    }


ANALYSIS_TOOLS = [
    today,
    days_from_today,
    audit_degree_plan,
    check_module_eligibility,
    trace_prerequisite_chain,
    term_load,
    compare_specialisations,
]
