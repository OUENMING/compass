"""The synthetic dataset, and the promises made about it.

Two of these tests are not really about code. The submission warrants that all
data is synthetic and that no real institution's rules are being asserted, and a
warranty that nothing checks is a sentence in a README. These check it.
"""

from __future__ import annotations

import json
from datetime import date

from compass.data.generate import (
    DEMO_TODAY,
    INSTITUTION,
    REGISTRATION_CLOSES,
    REGISTRATION_OPENS,
    build_announcements,
    build_student,
    write_all,
)

# Names that must never appear in the dataset. If a generated record starts
# reading like a real university's handbook, the privacy claim stops being true.
REAL_INSTITUTIONS = [
    "University College Dublin", "UCD", "Trinity College", "TCD",
    "Dublin City University", "DCU", "University of Limerick",
]


def test_the_demo_date_is_fixed():
    """Every deadline calculation has to agree with the calendar on screen."""
    assert DEMO_TODAY == date(2026, 9, 28)


def test_the_registration_window_is_after_the_demo_date(store):
    assert REGISTRATION_OPENS > DEMO_TODAY
    assert REGISTRATION_CLOSES > REGISTRATION_OPENS
    assert store.today == DEMO_TODAY


def test_the_institution_is_fictional():
    assert INSTITUTION not in REAL_INSTITUTIONS
    assert "Harbour" in INSTITUTION


def test_no_real_institution_is_named_anywhere_in_the_dataset(data_dir):
    blob = " ".join(
        path.read_text() for path in sorted(data_dir.glob("*.json"))
    )
    for name in REAL_INSTITUTIONS:
        assert name not in blob, f"{name!r} appears in the generated dataset"


def test_the_student_is_a_person_the_scenario_is_actually_about():
    """First-generation and international is the audience, not a decoration."""
    student = build_student()
    assert student.first_generation is True
    assert student.international is True
    assert student.stage == 2


def test_generating_twice_produces_byte_identical_data(tmp_path):
    """Reproducibility is what makes the recorded demo and the tests the same thing."""
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    write_all(first)
    write_all(second)

    for path in sorted(first.glob("*.json")):
        other = second / path.name
        assert path.read_bytes() == other.read_bytes(), f"{path.name} differs"


def test_regenerating_clears_previous_receipts(tmp_path):
    """A demo rerun must not inherit the last run's audit trail."""
    target = tmp_path / "data"
    target.mkdir()
    write_all(target)
    (target / "receipts.jsonl").write_text('{"action": "leftover"}\n')
    write_all(target)
    assert not (target / "receipts.jsonl").exists()


def test_the_announcement_that_drives_the_prerequisite_scenario_is_buried(store):
    """The scenario only exists because nobody pushed this one to students."""
    prereq = next(a for a in store.announcements if "waiver" in a.title.lower())
    assert prereq.announced_to_students is False
    assert "ECON20030" in prereq.affects_modules


def test_the_dataset_carries_at_least_one_quiet_announcement(store):
    """Not every rule change is a crisis; the sweep has to tell them apart."""
    assert any(not a.announced_to_students for a in store.announcements)
    assert any(a.announced_to_students for a in store.announcements)


def test_the_catalogue_is_internally_consistent(store):
    codes = {c.code for c in store.courses}
    for course in store.courses:
        assert course.capacity > 0
        assert course.enrolled <= course.capacity, f"{course.code} is oversubscribed"
        for prereq in course.prerequisites:
            assert prereq in codes, f"{course.code} requires unknown {prereq}"


def test_the_requirement_groups_cover_the_degree(store):
    reqs = store.requirements
    assert sum(g.credits_required for g in reqs.groups) <= reqs.total_credits
    assert {g.id for g in reqs.groups} == {
        "econ_core", "quant_stream", "general_elective"
    }


def test_the_written_rules_include_the_double_count_rule(store):
    """The repair is only mechanical because a written rule says what to do."""
    text = " ".join(store.requirements.rules).lower()
    assert "once" in text and "group" in text


def test_every_hold_names_the_action_that_clears_it(store):
    from compass.tools.actions import ACTION_BY_NAME

    for hold in store.student.holds:
        assert hold.action in ACTION_BY_NAME, (
            f"hold {hold.id} names {hold.action!r}, which is not an action"
        )


def test_meta_records_that_the_data_is_fabricated(data_dir):
    meta = json.loads((data_dir / "meta.json").read_text())
    assert meta["synthetic"] is True
    assert meta["institution"] == INSTITUTION
    assert meta["demo_today"] == DEMO_TODAY.isoformat()


def test_announcements_are_all_really_dated():
    """A notice with no publication date could not be reasoned about at all."""
    for announcement in build_announcements():
        assert isinstance(announcement.published, date)
