"""The school data interface, defined once and exposed two ways.

Compass needs its school tools available through two transports:

* **MCP** (``school_mcp_server``) — the primary path, and the one that matters
  architecturally: it puts the integration boundary where the real world puts
  it, so the agent's view of "the university's systems" is an actual protocol
  boundary rather than an in-process import.
* **Direct Strands ``@tool``** — a fallback for environments where running an
  MCP subprocess is awkward (some container runtimes, quick tests).

Two transports is exactly the setup that rots. So the *functions* live here
once, undecorated, and each transport decorates the same objects: FastMCP via
``mcp.tool(fn)`` and Strands via ``tool(fn)``. There is no second
implementation to drift out of sync.

Both derive their JSON schema from the signature and docstring, which is why
the docstrings here are written as tool descriptions and the return types are
plain JSON-able structures.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from strands import tool

from ..store import SchoolStore

_store: SchoolStore | None = None


def store() -> SchoolStore:
    global _store
    env = os.environ.get("COMPASS_DATA_DIR")
    if _store is None:
        _store = SchoolStore(Path(env) if env else None)
    return _store


def reset_store() -> None:
    """Drop the cached store. Used by tests that switch datasets."""
    global _store
    _store = None


def _course_dict(c, *, brief: bool = False) -> dict:
    d = {
        "code": c.code,
        "title": c.title,
        "credits": c.credits,
        "level": c.level,
        "term": c.term.value,
        "prerequisites": c.prerequisites,
        "seats_left": c.seats_left,
        "capacity": c.capacity,
        "enrolled": c.enrolled,
    }
    if not brief:
        d["corequisites"] = c.corequisites
        d["restrictions"] = c.restrictions
        d["summary"] = c.summary
    return d


# --------------------------------------------------------------------------
# The functions. One definition, two transports.
# --------------------------------------------------------------------------


def list_courses(
    prefix: str | None = None,
    level: int | None = None,
    term: str | None = None,
    has_seats: bool = False,
) -> list[dict]:
    """List modules in the catalogue, optionally filtered.

    Args:
        prefix: Module code prefix, e.g. "ECON". Case-insensitive.
        level: Stage level: 1, 2 or 3.
        term: "Autumn", "Spring" or "Both".
        has_seats: If true, only return modules with seats remaining.

    Returns:
        A list of module summaries.
    """
    out = []
    for c in store().courses:
        if prefix and not c.code.upper().startswith(prefix.upper()):
            continue
        if level is not None and c.level != level:
            continue
        if term and c.term.value.lower() != term.lower() and c.term.value != "Both":
            continue
        if has_seats and c.seats_left <= 0:
            continue
        out.append(_course_dict(c, brief=True))
    return out


def get_course(code: str) -> dict:
    """Get one module in full, including its prerequisites and available seats.

    Args:
        code: Module code, e.g. "ECON20030".

    Returns:
        The module, or an ``{"error": ...}`` object if the code is unknown.
    """
    c = store().course(code)
    if c is None:
        return {"error": f"No module with code {code!r} in the catalogue."}
    return _course_dict(c)


def get_degree_requirements() -> dict:
    """Get the programme's requirement groups and its written rules.

    The ``rules`` list is the important part: it holds the constraints that are
    not attached to any single module — the one-group-per-module rule, the term
    credit cap, how prerequisites are satisfied, and the degree-plan
    requirement.

    Returns:
        Requirement groups and the programme's written rules.
    """
    r = store().requirements
    return {
        "programme": r.programme,
        "title": r.title,
        "total_credits": r.total_credits,
        "stages": r.stages,
        "groups": [g.model_dump(mode="json") for g in r.groups],
        "rules": r.rules,
    }


def _hold_dict(h) -> dict:
    """A hold, with its resolved-ness impossible to skim past.

    A cleared hold is history: the description still reads like an alarm
    ("the block propagates to registration") long after the block is gone. The
    status line goes first and says which it is, because an agent that reports a
    resolved hold as active is crying wolf about something the student already
    dealt with — and she will stop believing the next one.
    """
    d = {
        "status": ("CLEARED — resolved, blocking nothing"
                   if h.cleared else "ACTIVE — blocking registration"),
        "cleared": h.cleared,
    }
    d.update(h.model_dump(mode="json"))
    return d


def get_student_record() -> dict:
    """Get the current student's record: completed, registered, planned, holds.

    Read ``active_hold_ids`` before saying anything is blocked: it lists only the
    holds that are still in force. A hold with ``cleared: true`` is settled and
    must not be reported as a problem, however alarming its description reads.

    Returns:
        The student's record. ``draft_plan`` maps requirement group ids to module
        codes, and ``degree_plan_filed`` says whether the plan is already on
        file (if true, filing is done and is not an outstanding task).
    """
    s = store().student
    return {
        "id": s.id,
        "name": s.name,
        "programme": s.programme,
        "stage": s.stage,
        "advisor": s.advisor,
        "first_generation": s.first_generation,
        "international": s.international,
        "degree_plan_filed": s.degree_plan_filed,
        "credits_earned": s.credits_earned,
        "completed": [c.model_dump(mode="json") for c in s.completed],
        "registered": s.registered,
        "spring_registered": s.spring_registered,
        "planned": s.planned,
        "active_hold_ids": [h.id for h in s.active_holds],
        "holds": [_hold_dict(h) for h in s.holds],
        "draft_plan": s.draft_plan,
    }


def get_academic_calendar() -> list[dict]:
    """Get the academic calendar: term dates, registration windows, deadlines.

    Returns:
        Calendar events with their opening and closing dates.
    """
    return [e.model_dump(mode="json") for e in store().calendar]


def list_announcements(
    since: str | None = None,
    only_unannounced: bool = False,
) -> list[dict]:
    """Get programme announcements, most recent first.

    Args:
        since: ISO date, e.g. "2026-09-01". Only announcements published on or
            after this date are returned.
        only_unannounced: If true, only return announcements that were NOT
            pushed to students — the ones published to a handbook or
            noticeboard page that a student would have to go looking for.

    Returns:
        A list of announcements.
    """
    cutoff = date.fromisoformat(since) if since else None
    out = []
    for a in store().announcements:
        if cutoff and a.published < cutoff:
            continue
        if only_unannounced and a.announced_to_students:
            continue
        out.append(a.model_dump(mode="json"))
    out.sort(key=lambda a: a["published"], reverse=True)
    return out


# Plain functions, for the MCP transport to decorate.
SCHOOL_FUNCTIONS = [
    list_courses,
    get_course,
    get_degree_requirements,
    get_student_record,
    get_academic_calendar,
    list_announcements,
]

# Strands-decorated, for the direct transport.
SCHOOL_TOOLS = [tool(fn) for fn in SCHOOL_FUNCTIONS]
