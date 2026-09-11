"""The prerequisite graph.

Prerequisites are the sharpest example of a rule that is written down, public,
and still catches people — because they are *transitive*. "ECON30010 requires
ECON20030" is on one page. "ECON20030 requires ECON10790" is on another. The
student sees the first, has never heard of the second, and finds out in Stage 3
that the door shut two years earlier.

This module walks the graph so nobody has to hold it in their head:

* ``missing_prereqs`` — what a module needs that the student has not passed
* ``blocked_by`` — which specific unmet prerequisite is doing the blocking
* ``unlocks`` — the inverse edge, used to explain *why* a module matters
* ``satisfiable`` — whether the gap can still be closed, or is a dead end

Same principle as ``compass.audit``: graph traversal is arithmetic. It is code,
not a prompt.
"""

from __future__ import annotations

from .models import Course, StudentRecord
from .store import SchoolStore

# A prerequisite is treated as "will be satisfied" if the student has already
# passed it or is registered/planned for it. Planning must look forward, or
# every chain would read as broken until the very last module.
FORWARD_LOOKING_STATES = {"registered", "planned", "spring_registered"}


def _status_map(student: StudentRecord) -> dict[str, str]:
    status = {c.code: c.status for c in student.completed}
    for code in student.registered:
        status.setdefault(code, "registered")
    for code in student.spring_registered:
        status.setdefault(code, "spring_registered")
    for code in student.planned:
        status.setdefault(code, "planned")
    return status


def passed_codes(student: StudentRecord) -> set[str]:
    return {c.code for c in student.completed if c.status == "passed"}


def missing_prereqs(
    store: SchoolStore,
    student: StudentRecord,
    code: str,
    *,
    include_in_progress: bool = True,
) -> list[str]:
    """Prerequisites of ``code`` the student has not satisfied.

    With ``include_in_progress`` (the default) a module the student is
    registered or planned for counts as satisfied, which is what planning
    needs. Turn it off to ask the stricter question "is this student eligible
    *today*".
    """
    course = store.course(code)
    if course is None:
        return []
    status = _status_map(student)
    out = []
    for prereq in course.prerequisites:
        state = status.get(prereq)
        ok = state == "passed" or (
            include_in_progress and state in FORWARD_LOOKING_STATES
        )
        if not ok:
            out.append(prereq)
    return out


def blocked_by(store: SchoolStore, student: StudentRecord, code: str) -> str | None:
    """Return the unmet prerequisite blocking ``code``, if any."""
    missing = missing_prereqs(store, student, code)
    return missing[0] if missing else None


def unlocks(store: SchoolStore, code: str, level: int | None = None) -> list[Course]:
    """Modules that directly require ``code``.

    Used to turn "you are missing ECON10790" into "you are missing the module
    that the entire quantitative stream is standing on".
    """
    out = []
    for c in store.courses:
        if code in c.prerequisites:
            if level is not None and c.level != level:
                continue
            out.append(c)
    return out


def chain_to(store: SchoolStore, target: str, seen: set[str] | None = None) -> list[str]:
    """Every module upstream of ``target``, nearest prerequisites first."""
    seen = seen if seen is not None else set()
    course = store.course(target)
    if course is None:
        return []
    out: list[str] = []
    for prereq in course.prerequisites:
        if prereq in seen:
            continue
        seen.add(prereq)
        out.append(prereq)
        out.extend(chain_to(store, prereq, seen))
    return out


def satisfiable(
    store: SchoolStore,
    student: StudentRecord,
    code: str,
    *,
    within_terms: list[str] | None = None,
) -> tuple[bool, str]:
    """Can the student still satisfy ``code``'s prerequisites?

    Returns ``(ok, explanation)``. This is where the *irreversibility* in
    scenario 1 actually comes from: the missing prerequisite exists in the
    catalogue, so on paper the gap is closable — but only if the student
    registers for it in the one term it runs, while seats remain.
    """
    missing = missing_prereqs(store, student, code)
    if not missing:
        return True, f"All prerequisites for {code} are satisfied."

    for prereq in missing:
        course = store.course(prereq)
        if course is None:
            return False, (
                f"{code} requires {prereq}, which is not in the catalogue. "
                "This gap cannot be closed by module selection."
            )
        if course.seats_left <= 0:
            return False, (
                f"{code} requires {prereq}, but {prereq} has no seats left "
                f"this year ({course.enrolled}/{course.capacity} enrolled)."
            )
    listed = ", ".join(missing)
    return True, (
        f"{code} requires {listed}, which the student has not taken. "
        f"It can still be closed, but only by registering for it in the term "
        f"it runs."
    )
