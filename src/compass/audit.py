"""Deterministic degree audit.

Why this is plain Python and not a prompt
-----------------------------------------
Counting credits is arithmetic. Arithmetic is the one thing an LLM will get
wrong *confidently* — and a confidently wrong credit count is exactly the
failure mode that costs a student a year. So the audit is code: same plan in,
same numbers out, every time. The model's job is the part code genuinely cannot
do — reading an announcement written in prose and working out that it invalidates
a plan — and it is then handed these numbers as ground truth.

The two rules implemented here are quoted verbatim in the programme's
``rules`` list, so the audit and the handbook cannot drift apart:

* **Rule 1** — a module may satisfy at most one group. Duplicates are discarded
  and the plan is short by that module's credits.
* **Rule 2** — a group left short is filled by the earliest-passed unassigned
  module eligible for it, and a compulsory module always belongs to its
  compulsory group. This rule is what makes the repair in scenario 3
  *mechanical* rather than a judgement call, which is why the gate is allowed
  to apply it without asking.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import DegreeRequirements, StudentRecord
from .store import SchoolStore

# Programme rule: stage credit load may not exceed 30 ECTS in a single term.
MAX_TERM_CREDITS = 30

# The modules that satisfy the quantitative stream, per specialisation. This is
# programme-requirement knowledge, so it lives next to the audit rather than
# next to the actions that happen to read it — both `audit` and the action tools
# need it, and two copies would eventually disagree.
SPECIALISATION_MODULES: dict[str, list[str]] = {
    "quantitative": ["ECON20030", "ECON30010", "ECON20040"],
    "general": ["ECON30030", "ECON30040", "ECON30060"],
}


@dataclass
class GroupStatus:
    id: str
    name: str
    required: int
    awarded: int

    @property
    def short(self) -> int:
        return max(self.required - self.awarded, 0)

    @property
    def met(self) -> bool:
        return self.short == 0


@dataclass
class AuditResult:
    groups: list[GroupStatus]
    duplicates: dict[str, list[str]] = field(default_factory=dict)
    unassigned: list[str] = field(default_factory=list)

    @property
    def short_groups(self) -> list[GroupStatus]:
        return [g for g in self.groups if not g.met]

    @property
    def clean(self) -> bool:
        return not self.short_groups and not self.duplicates


def _credits(store: SchoolStore, code: str) -> int:
    c = store.course(code)
    return c.credits if c else 0


def find_duplicates(plan: dict[str, list[str]]) -> dict[str, list[str]]:
    """Module code -> the groups it appears in, for codes appearing more than once."""
    seen: dict[str, list[str]] = {}
    for group_id, codes in plan.items():
        for code in codes:
            seen.setdefault(code, [])
            if group_id not in seen[code]:
                seen[code].append(group_id)
    return {code: groups for code, groups in seen.items() if len(groups) > 1}


def assigned_codes(plan: dict[str, list[str]]) -> set[str]:
    return {code for codes in plan.values() for code in codes}


def audit(
    store: SchoolStore,
    plan: dict[str, list[str]],
    requirements: DegreeRequirements | None = None,
) -> AuditResult:
    """Audit a plan against the programme's requirement groups.

    A duplicated module is counted once — in the *first* group that claims it,
    matching the handbook's "the duplicate is discarded" behaviour.
    """
    reqs = requirements or store.requirements
    duplicates = find_duplicates(plan)

    claimed: set[str] = set()
    statuses: list[GroupStatus] = []
    for group in reqs.groups:
        codes = plan.get(group.id, [])
        awarded = 0
        for code in codes:
            if code in claimed:
                continue  # duplicate discarded, per rule 1
            if not _credits(store, code):
                continue
            claimed.add(code)
            awarded += _credits(store, code)
        statuses.append(
            GroupStatus(id=group.id, name=group.name,
                        required=group.credits_required, awarded=awarded)
        )

    return AuditResult(groups=statuses, duplicates=duplicates)


def _eligible_for(code: str, group_id: str, store: SchoolStore) -> bool:
    group = next((g for g in store.requirements.groups if g.id == group_id), None)
    if group is None:
        return False
    if group.modules:
        return code in group.modules
    if group.prefixes:
        return any(code.upper().startswith(p.upper()) for p in group.prefixes)
    return True


def propose_fix(
    store: SchoolStore,
    student: StudentRecord,
    plan: dict[str, list[str]],
) -> tuple[dict[str, list[str]], list[str]]:
    """Apply rules 1 and 2 to repair a plan. Returns the new plan and a changelog.

    Pure function: no mutation, no I/O beyond reading the catalogue.
    """
    new_plan = {group_id: list(codes) for group_id, codes in plan.items()}
    changes: list[str] = []

    # Rule 1 — a compulsory module belongs to its compulsory group; drop the
    # duplicate from anywhere else.
    for code, groups in find_duplicates(new_plan).items():
        # Keep the earliest group in programme order, drop the rest.
        order = [g.id for g in store.requirements.groups]
        groups_sorted = sorted(groups, key=order.index)
        for group_id in groups_sorted[1:]:
            new_plan[group_id].remove(code)
            changes.append(
                f"Removed {code} from '{group_id}' — already claimed by "
                f"'{groups_sorted[0]}' (rule 1)."
            )

    # Rule 2 — fill any group left short from the earliest-passed unassigned
    # module that is eligible for it. "Earliest" is by term, so the outcome does
    # not depend on the order records happen to sit in the file.
    passed_order = [
        c.code
        for c in sorted(
            (c for c in student.completed if c.status == "passed"),
            key=lambda c: (c.term, c.code),
        )
    ]
    used = assigned_codes(new_plan)
    for status in audit(store, new_plan).short_groups:
        if status.short <= 0:
            continue
        for code in passed_order:
            if code in used:
                continue
            if _credits(store, code) != status.short:
                continue
            if not _eligible_for(code, status.id, store):
                continue
            new_plan.setdefault(status.id, []).append(code)
            used.add(code)
            changes.append(
                f"Assigned {code} to '{status.id}' — fills the "
                f"{status.short} credit gap (rule 2)."
            )
            break

    return new_plan, changes


def unassigned_modules(store: SchoolStore, student: StudentRecord,
                       plan: dict[str, list[str]]) -> list[str]:
    used = assigned_codes(plan)
    return [c.code for c in student.completed if c.code not in used]
