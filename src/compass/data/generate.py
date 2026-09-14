"""Generate the synthetic university dataset Compass reasons over.

Everything this module writes is **fabricated**. No real student record, no
real institution's private data. The module codes follow the conventions of
Irish/EU universities so the reasoning looks like the real thing, but the
programme structure, calendar, prerequisites and the student herself are all
invented. The dataset carries ``"synthetic": true`` so that is never in doubt.

Why synthetic matters here
--------------------------
Compass holds a student's holds, grades and registration state. Building that on
real records would be a privacy problem with no upside for a demo, and the
hackathon's rules require that third-party data be used within its terms. A
generated dataset sidesteps both, and has a third benefit: it is *deterministic*,
so the scenario that the screen recording shows is the same scenario the tests
assert on.

The scenario, in one paragraph
------------------------------
Our student transferred into Economics from Engineering at the end of Stage 1.
Her credit total looks fine — 60 ECTS — but only 20 of those ECTS are Economics,
and the transfer path substituted a module that does not satisfy the
Econometrics prerequisite chain. She is a first-generation international
student, nobody in her family has navigated this, and the rules that would have
caught it are split across a handbook, a calendar and a mid-term announcement.
That is the trap Compass exists to catch.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from ..models import (
    Announcement,
    CalendarEvent,
    CompletedCourse,
    Course,
    DegreeRequirements,
    Hold,
    RequirementGroup,
    StudentRecord,
    Term,
)

# The date the demo pretends it is. Fixed so the recording and the tests agree.
DEMO_TODAY = date(2026, 9, 28)

INSTITUTION = "Harbour University Dublin"

# Window students register in for Spring 2026/27 modules.
REGISTRATION_OPENS = date(2026, 10, 5)
REGISTRATION_CLOSES = date(2026, 10, 23)


# --------------------------------------------------------------------------
# Catalogue
# --------------------------------------------------------------------------


def build_courses() -> list[Course]:
    def c(
        code: str,
        title: str,
        credits: int,
        level: int,
        term: Term,
        prereq: list[str] | None = None,
        capacity: int = 80,
        enrolled: int = 0,
        summary: str = "",
    ) -> Course:
        return Course(
            code=code,
            title=title,
            credits=credits,
            level=level,
            term=term,
            prerequisites=prereq or [],
            capacity=capacity,
            enrolled=enrolled,
            summary=summary,
        )

    return [
        # ---- Stage 1 ----------------------------------------------------
        c("ECON10770", "Introduction to Economics", 5, 1, Term.AUTUMN),
        c("ECON10730", "Data Analysis for Economists", 5, 1, Term.SPRING),
        c("ECON10740", "Exploring Economics", 5, 1, Term.SPRING,
          summary="Policy-facing, experience-based introduction. Counts toward "
                  "the Economics option list but not the quantitative stream."),
        c("ECON10790", "Mathematical Economics", 5, 1, Term.SPRING,
          capacity=60, enrolled=47,
          summary="Required bridge into ECON20030 and ECON20040. Runs once a "
                  "year, Spring only, and historically fills."),
        c("SOC10020", "Introduction to Sociology", 5, 1, Term.AUTUMN),
        c("PHIL10020", "Ethics and Society", 5, 1, Term.AUTUMN),
        c("LANG10010", "Academic Writing", 5, 1, Term.AUTUMN),
        c("HIST10020", "Modern Irish History", 5, 1, Term.SPRING),
        c("GEOG10030", "Human Geography", 5, 1, Term.AUTUMN),
        # Transfer credits from the Engineering pathway
        c("ENGR10010", "Engineering Design", 5, 1, Term.AUTUMN),
        c("MATH10040", "Linear Algebra", 5, 1, Term.AUTUMN),
        c("COMP10030", "Programming I", 5, 1, Term.AUTUMN),
        c("PHYS10020", "Physics for Engineers", 5, 1, Term.SPRING),

        # ---- Stage 2 ----------------------------------------------------
        c("ECON20010", "Microeconomic Theory", 5, 2, Term.AUTUMN,
          prereq=["ECON10770"]),
        c("ECON20020", "Macroeconomic Theory", 5, 2, Term.SPRING,
          prereq=["ECON10770"]),
        c("ECON20030", "Econometrics I", 5, 2, Term.SPRING,
          prereq=["ECON10730", "ECON10790"],
          summary="Gateway to the quantitative stream. Requires BOTH the data "
                  "analysis module and Mathematical Economics."),
        c("ECON20040", "Mathematical Economics II", 5, 2, Term.AUTUMN,
          prereq=["ECON10790"]),
        c("STAT20110", "Probability and Inference", 5, 2, Term.AUTUMN),
        c("PHIL20030", "Philosophy of Science", 5, 2, Term.AUTUMN),
        c("SOC20040", "Research Methods", 5, 2, Term.SPRING),

        # ---- Stage 3 ----------------------------------------------------
        c("ECON30010", "Econometrics II", 5, 3, Term.AUTUMN,
          prereq=["ECON20030"],
          summary="Required for the Quantitative Economics specialisation."),
        c("ECON30020", "Advanced Microeconomics", 5, 3, Term.AUTUMN,
          prereq=["ECON20010", "ECON20040"]),
        c("ECON30040", "Public Economics", 5, 3, Term.SPRING,
          prereq=["ECON20020"]),
        c("ECON30030", "International Trade", 5, 3, Term.SPRING,
          prereq=["ECON20010"]),
        c("ECON30060", "Economics of Inequality", 5, 3, Term.SPRING,
          prereq=["ECON20020"]),
        c("ECON30050", "Economics Dissertation", 10, 3, Term.BOTH,
          prereq=["ECON30020"]),
    ]


def build_requirements() -> DegreeRequirements:
    return DegreeRequirements(
        programme="ECS4",
        title="BSc Economics",
        total_credits=180,
        stages=3,
        groups=[
            RequirementGroup(
                id="econ_core",
                name="Economics Core",
                credits_required=40,
                prefixes=["ECON"],
                notes="Compulsory economics modules across all three stages.",
            ),
            RequirementGroup(
                id="quant_stream",
                name="Quantitative Economics Specialisation",
                credits_required=15,
                modules=["ECON20030", "ECON30010", "ECON20040"],
                notes="Required only for the Quantitative Economics "
                      "specialisation. Students on the General Economics "
                      "specialisation replace this with 15 credits of Level 3 "
                      "economics options (ECON30030, ECON30040, ECON30060).",
            ),
            RequirementGroup(
                id="general_elective",
                name="General Electives",
                credits_required=20,
                notes="Any modules outside the programme, including transferred "
                      "credit from a previous pathway.",
            ),
        ],
        rules=[
            "A module may satisfy the requirements of at most one group. "
            "Where a module appears in more than one place in a plan, the "
            "duplicate is discarded at audit and the plan is short by that "
            "module's credits.",
            "Where a plan leaves a group short, the group is filled by the "
            "earliest-passed unassigned module that is eligible for it. A "
            "compulsory module always belongs to its compulsory group.",
            "Stage credit load may not exceed 30 ECTS in any single term.",
            "A prerequisite is satisfied only by a passed module. Standing "
            "waivers granted under a previous programme version do not carry "
            "forward once the waiver is withdrawn (see programme "
            "announcements).",
            "The degree plan must be filed and advisor-approved before the "
            "student's registration window opens each year.",
        ],
    )


# --------------------------------------------------------------------------
# The student
# --------------------------------------------------------------------------


def build_student() -> StudentRecord:
    completed = [
        # Economics — the four modules that survived the transfer
        CompletedCourse(code="ECON10770", title="Introduction to Economics",
                        credits=5, term="2025/26 Autumn", grade="B+"),
        CompletedCourse(code="ECON10730", title="Data Analysis for Economists",
                        credits=5, term="2025/26 Spring", grade="A-"),
        CompletedCourse(code="ECON10740", title="Exploring Economics",
                        credits=5, term="2025/26 Spring", grade="B"),
        CompletedCourse(code="SOC10020", title="Introduction to Sociology",
                        credits=5, term="2025/26 Autumn", grade="A-"),
        # Carried over from the Engineering pathway — credits count, but only
        # as general electives.
        CompletedCourse(code="ENGR10010", title="Engineering Design",
                        credits=5, term="2025/26 Autumn", grade="C+"),
        CompletedCourse(code="MATH10040", title="Linear Algebra",
                        credits=5, term="2025/26 Autumn", grade="B-"),
        CompletedCourse(code="COMP10030", title="Programming I",
                        credits=5, term="2025/26 Spring", grade="B"),
        CompletedCourse(code="PHYS10020", title="Physics for Engineers",
                        credits=5, term="2025/26 Spring", grade="C"),
        # General electives
        CompletedCourse(code="PHIL10020", title="Ethics and Society",
                        credits=5, term="2025/26 Autumn", grade="B+"),
        CompletedCourse(code="LANG10010", title="Academic Writing",
                        credits=5, term="2025/26 Autumn", grade="A"),
        CompletedCourse(code="HIST10020", title="Modern Irish History",
                        credits=5, term="2025/26 Spring", grade="B"),
        CompletedCourse(code="GEOG10030", title="Human Geography",
                        credits=5, term="2025/26 Spring", grade="B-"),
    ]

    return StudentRecord(
        id="STU-2214773",
        name="Aisha Nwosu",
        programme="ECS4",
        stage=2,
        email="aisha.nwosu@example.edu",
        advisor="Dr. M. Kavanagh",
        first_generation=True,
        international=True,
        completed=completed,
        registered=["ECON20010", "STAT20110", "PHIL20030"],
        planned=["ECON20020", "ECON20030", "SOC20040"],
        holds=[
            Hold(
                id="LIB-2026-7781",
                kind="Library",
                description="3 items from the Short Loan collection are 21 days "
                            "overdue. The library account is blocked and the "
                            "block propagates to registration. Items not "
                            "resolved within 28 days of the due date convert "
                            "to a replacement charge and the block is "
                            "escalated to a financial hold, which only the "
                            "Fees Office can clear. Fees Office clearance "
                            "takes 10 working days and is not expedited "
                            "during a registration period.",
                resolvable_by="Return the items in person (no charge) or "
                              "authorise the replacement charge of EUR 45.00. "
                              "Either must happen before the escalation date.",
                action="resolve_library_hold",
            ),
            Hold(
                id="ADV-2026-041",
                kind="Advising",
                description="Stage 3 degree plan has not been filed. The plan "
                            "must be advisor-approved before the Spring "
                            "registration window opens.",
                resolvable_by="File a degree plan that satisfies all programme "
                              "requirements, then obtain advisor approval "
                              "(3 working days).",
                action="file_degree_plan",
            ),
        ],
        degree_plan_filed=False,
        # Auto-generated when she transferred in, and never audited. Note
        # ECON10740 appearing in *two* groups — that is the whole bug — and
        # ENGR10010 sitting unassigned, which is the fix: rule 2 fills the
        # gap with the earliest-passed unassigned eligible module, and every
        # module is eligible for general electives. The plan also parks the
        # quantitative stream at 10 of its 15 credits before the
        # prerequisite break is even considered.
        draft_plan={
            "econ_core": [
                "ECON10770", "ECON10730", "ECON10740",
                "ECON20010", "ECON20020",
                "ECON30020", "ECON30040", "ECON30050",
            ],
            "quant_stream": ["ECON20030", "ECON30010"],
            "general_elective": [
                "ECON10740", "SOC10020", "PHIL10020", "LANG10010",
            ],
        },
    )


# --------------------------------------------------------------------------
# Calendar and announcements
# --------------------------------------------------------------------------


def build_calendar() -> list[CalendarEvent]:
    return [
        CalendarEvent(id="cal-autumn-start", name="Autumn term begins",
                      opens=date(2026, 9, 14), kind="term"),
        CalendarEvent(id="cal-autumn-adddrop",
                      name="Autumn add / drop deadline",
                      closes=date(2026, 10, 2), kind="deadline",
                      notes="After this date a module change is recorded as a "
                            "withdrawal and appears on the transcript."),
        CalendarEvent(id="cal-reg-spring",
                      name="Spring 2026/27 registration window",
                      opens=REGISTRATION_OPENS, closes=REGISTRATION_CLOSES,
                      kind="registration",
                      notes="Seat allocation is first-come, first-served within "
                            "each registration group."),
        CalendarEvent(id="cal-autumn-w",
                      name="Autumn withdrawal (W) deadline",
                      closes=date(2026, 11, 13), kind="deadline"),
        CalendarEvent(id="cal-library-escalation",
                      name="Library items escalate to a financial hold",
                      closes=date(2026, 10, 5), kind="deadline",
                      notes="Unresolved Short Loan items convert to a "
                            "replacement charge on this date and the block "
                            "becomes a financial hold clearable only by the "
                            "Fees Office (10 working days)."),
        CalendarEvent(id="cal-fees-spring", name="Spring fee payment due",
                      closes=date(2027, 1, 15), kind="fees",
                      notes="A late payment is accepted for 14 days with a EUR "
                            "50 administration charge."),
        CalendarEvent(id="cal-spring-start", name="Spring term begins",
                      opens=date(2027, 1, 19), kind="term"),
        CalendarEvent(id="cal-graduation-apply",
                      name="Graduation application closes",
                      closes=date(2027, 3, 1), kind="other"),
    ]


def build_announcements() -> list[Announcement]:
    return [
        Announcement(
            id="ann-prereq-2026-09",
            published=date(2026, 9, 22),
            title="Withdrawal of standing prerequisite waiver for ECON20030",
            body=(
                "The standing waiver that permitted students who had completed "
                "ECON10730 (Data Analysis for Economists) to enrol in ECON20030 "
                "(Econometrics I) without ECON10790 (Mathematical Economics) is "
                "withdrawn with effect from the 2026/27 academic year. From that "
                "year, ECON20030 requires both listed prerequisites to be "
                "satisfied by a passed module. Students who enrolled under the "
                "previous waiver are unaffected in modules already completed, "
                "but the waiver does not carry forward to new enrolments. "
                "Queries to the School Office."
            ),
            affects_modules=["ECON20030", "ECON30010", "ECON10790"],
            effective_from="2026/27",
            # The detail that matters: this went to a handbook page, not to inboxes.
            announced_to_students=False,
        ),
        Announcement(
            id="ann-plan-2026-09",
            published=date(2026, 9, 11),
            title="Degree plans must be approved before registration opens",
            body=(
                "Students progressing to Stage 3 must have an advisor-approved "
                "degree plan on file before their registration window opens. "
                "Plans are reviewed within three working days. Registration "
                "cannot be released while a plan is outstanding."
            ),
            announced_to_students=True,
        ),
        Announcement(
            id="ann-audit-2026-08",
            published=date(2026, 8, 20),
            title="Annual plan audit: duplicate module assignments",
            body=(
                "Plans generated automatically at programme transfer are not "
                "audited for duplicate assignments. A module appearing in two "
                "requirement groups is counted once, and the shortfall is "
                "reported to the student only at the graduation audit."
            ),
            affects_modules=["ECON10740", "PHIL10020"],
            effective_from="2026/27",
            announced_to_students=False,
        ),
    ]


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------


def build_meta() -> dict:
    return {
        "synthetic": True,
        "notice": (
            "This dataset is entirely fabricated for demonstration purposes. "
            "No real student, institution or programme data is included. "
            "Module codes follow common Irish/EU conventions for realism only."
        ),
        "institution": INSTITUTION,
        "demo_today": DEMO_TODAY.isoformat(),
        "generated_by": "compass.data.generate",
    }


def write_all(out_dir: Path) -> dict[str, Path]:
    """Write the dataset to ``out_dir``. Returns the paths written."""

    out_dir.mkdir(parents=True, exist_ok=True)
    payloads: dict[str, object] = {
        "courses": build_courses(),
        "degree_requirements": build_requirements(),
        "student": build_student(),
        "calendar": build_calendar(),
        "announcements": build_announcements(),
        "meta": build_meta(),
    }

    written: dict[str, Path] = {}
    for name, payload in payloads.items():
        path = out_dir / f"{name}.json"
        if isinstance(payload, list):
            data = [
                item.model_dump(mode="json") if hasattr(item, "model_dump")
                else item
                for item in payload
            ]
        elif hasattr(payload, "model_dump"):
            data = payload.model_dump(mode="json")  # type: ignore[union-attr]
        else:
            data = payload  # plain dict
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        written[name] = path

    # A fresh dataset means the demo is back at its starting point.
    receipts = out_dir / "receipts.jsonl"
    if receipts.exists():
        receipts.unlink()

    return written


def default_data_dir() -> Path:
    """``<repo>/data`` — resolved from this file's location, not the cwd."""
    return Path(__file__).resolve().parents[3] / "data"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the synthetic university dataset for Compass."
    )
    parser.add_argument("--out", type=Path, default=default_data_dir(),
                        help="Output directory (default: <repo>/data)")
    args = parser.parse_args()

    written = write_all(args.out)
    print(f"Wrote synthetic dataset to {args.out}")
    for name, path in written.items():
        print(f"  {name:22s} {path.name}")
    print("\nAll records are fabricated. Demo 'today' is "
          f"{DEMO_TODAY.isoformat()}.")


if __name__ == "__main__":
    main()
