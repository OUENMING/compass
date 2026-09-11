"""Data models for Compass.

Two families live here:

1. **School data** — the synthetic catalogue / degree rules / student record /
   calendar that the MCP server exposes. These mirror the shape of real
   university systems so the agent's reasoning is realistic, but every record
   is fabricated (see ``compass.data.generate``).

2. **Findings & verdicts** — the structured output contract. The Sentinel agent
   does not get to decide whether a student is interrupted; it only reports
   facts about a situation (``Finding``). The deterministic gate in
   ``compass.gate`` owns the decision. Keeping these types explicit is what
   makes "Compass stays silent by default" a testable property rather than a
   prompt suggestion.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# School data
# --------------------------------------------------------------------------


class Term(str, Enum):
    AUTUMN = "Autumn"
    SPRING = "Spring"
    BOTH = "Both"


class Course(BaseModel):
    """One entry in the module catalogue."""

    code: str
    title: str
    credits: int = Field(description="ECTS credits")
    level: int = Field(description="1 = Stage 1, 2 = Stage 2, 3 = Stage 3")
    term: Term
    prerequisites: list[str] = Field(default_factory=list)
    corequisites: list[str] = Field(default_factory=list)
    restrictions: list[str] = Field(default_factory=list)
    capacity: int
    enrolled: int = 0
    summary: str = ""

    @property
    def seats_left(self) -> int:
        return max(self.capacity - self.enrolled, 0)


class RequirementGroup(BaseModel):
    """A bucket of credits the degree requires, e.g. 'Economics Core'."""

    id: str
    name: str
    credits_required: int
    # Either an explicit module list, or a level/prefix filter, or both.
    modules: list[str] = Field(default_factory=list)
    prefixes: list[str] = Field(default_factory=list)
    min_level: int | None = None
    notes: str = ""


class DegreeRequirements(BaseModel):
    programme: str
    title: str
    total_credits: int
    stages: int
    groups: list[RequirementGroup]
    rules: list[str] = Field(
        default_factory=list,
        description="Free-text programme rules, e.g. the double-count rule",
    )


class CompletedCourse(BaseModel):
    code: str
    title: str
    credits: int
    term: str
    grade: str
    status: Literal["passed", "failed", "withdrawn"] = "passed"


class Hold(BaseModel):
    """A block on registration."""

    id: str
    kind: str
    description: str
    blocks_registration: bool = True
    resolvable_by: str = Field(
        description="Human-readable statement of what clears the hold"
    )
    # The action name in compass.tools.actions that clears it, if any.
    action: str | None = None
    cleared: bool = False


class StudentRecord(BaseModel):
    id: str
    name: str
    programme: str
    stage: int
    email: str
    advisor: str
    # Context that matters for the audience story, not for the rules engine.
    first_generation: bool = True
    international: bool = True
    completed: list[CompletedCourse] = Field(default_factory=list)
    registered: list[str] = Field(default_factory=list)
    planned: list[str] = Field(
        default_factory=list,
        description="Modules the student intends to take, not yet registered",
    )
    spring_registered: list[str] = Field(
        default_factory=list,
        description="Modules confirmed for the next term's registration window",
    )
    holds: list[Hold] = Field(default_factory=list)
    degree_plan_filed: bool = False
    specialisation: str = Field(
        default="quantitative",
        description="'quantitative' or 'general'. Determines how the "
                    "quantitative stream requirement is satisfied.",
    )
    # Group id -> module codes. Generated automatically when a student changes
    # programme, and famously not audited for duplicates at that point — which
    # is how a module ends up counted twice and a student ends up short.
    draft_plan: dict[str, list[str]] = Field(default_factory=dict)

    @property
    def credits_earned(self) -> int:
        return sum(c.credits for c in self.completed if c.status == "passed")

    @property
    def active_holds(self) -> list[Hold]:
        return [h for h in self.holds if not h.cleared]


class CalendarEvent(BaseModel):
    id: str
    name: str
    opens: date | None = None
    closes: date | None = None
    kind: Literal["registration", "deadline", "term", "exam", "fees", "other"]
    notes: str = ""


class Announcement(BaseModel):
    """A rule change published mid-year.

    This is the mechanism behind the project's central claim: the rules are not
    only unwritten, they *move* — and the people who find out last are the ones
    with nobody to ask.
    """

    id: str
    published: date
    title: str
    body: str
    affects_modules: list[str] = Field(default_factory=list)
    effective_from: str = ""
    # Whether this was pushed to students or only buried in a handbook page.
    announced_to_students: bool = True


# --------------------------------------------------------------------------
# Findings & verdicts
# --------------------------------------------------------------------------


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Option(BaseModel):
    """One choice on the decision card. Exactly one is the agent's recommendation.

    ``after`` exists because some resolutions are genuinely two steps that the
    programme rules fix in order — you cannot file a degree plan that still
    fails its audit, so the filing option carries the repair with it. Keeping
    the sequence inside one option means the gate authorises the *whole*
    resolution or none of it, never half.
    """

    id: str
    label: str
    consequence: str
    action: str = Field(description="Action name in compass.tools.actions")
    action_args: dict = Field(default_factory=dict)
    after: str | None = Field(
        default=None,
        description="Action that must be carried out before `action`, if any. "
                    "Must also be a name from compass.tools.actions, and is "
                    "called with no arguments — `action_args` belongs to `action`.",
    )
    recommended: bool = False


class Finding(BaseModel):
    """A factual report from Sentinel. Deliberately *not* a recommendation to speak.

    Note there is no "should_surface" field. The agent reports what is true and
    how confident it is; ``compass.gate`` decides what that means for the
    student's attention.
    """

    id: str
    title: str
    what_happened: str
    consequence_if_ignored: str

    severity: Severity
    irreversible_after_deadline: bool = Field(
        description="True if missing the deadline cannot be undone later"
    )
    deadline: date | None = None
    days_until_last_safe_action: int | None = None
    needs_human_choice: bool = Field(
        description="True if a judgement only the student can make is required"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    options: list[Option] = Field(default_factory=list)


class Verdict(str, Enum):
    SILENT = "silent"
    SURFACE = "surface"
    AUTO_ACT = "auto_act"


class GateDecision(BaseModel):
    verdict: Verdict
    reason: str
    finding: Finding | None = None


class Receipt(BaseModel):
    """Proof that the agent actually did something, not just described it."""

    finding_id: str
    option_id: str
    action: str
    summary: str
    detail: dict = Field(default_factory=dict)
    reversible: bool = True
