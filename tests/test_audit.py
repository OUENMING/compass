"""The deterministic degree audit.

This is the arithmetic behind the "hidden rule" scenario: a module counted in
two requirement groups, a group left short by exactly that, and a fix that the
written programme rules determine completely. If this file is right then the
repair needs no judgement from the student, which is what lets the gate run it
without asking.
"""

from __future__ import annotations

from compass import audit as audit_mod
from compass.audit import MAX_TERM_CREDITS, SPECIALISATION_MODULES


def test_the_transfer_plan_really_does_double_count_a_module(store):
    """The scenario is a property of the dataset, not of the prompt."""
    duplicates = audit_mod.find_duplicates(store.student.draft_plan)
    assert "ECON10740" in duplicates
    assert set(duplicates["ECON10740"]) == {"econ_core", "general_elective"}


def test_audit_reports_the_groups_the_scenario_depends_on(store):
    result = audit_mod.audit(store, store.student.draft_plan)
    groups = {g.id: g for g in result.groups}

    assert groups["econ_core"].awarded == 45      # over the 40 required, because
    assert groups["econ_core"].met                # the duplicate is counted here
    assert groups["general_elective"].awarded == 15
    assert groups["general_elective"].short == 5  # ...and leaves a hole here


def test_propose_fix_resolves_the_duplicate_by_the_written_rules(store):
    plan, changes = audit_mod.propose_fix(store, store.student, store.student.draft_plan)

    assert changes, "the scenario must have something to repair"
    assert not audit_mod.find_duplicates(plan), "the fix must remove the duplicate"
    # ECON10740 stays where it was first claimed; the hole is filled instead.
    assert "ECON10740" in plan["econ_core"]
    assert "ECON10740" not in plan["general_elective"]

    after = audit_mod.audit(store, plan)
    assert all(g.met for g in after.groups if g.id != "quant_stream")


def test_propose_fix_is_reproducible(store):
    """Determinism is the whole reason the gate may run this unattended."""
    first = audit_mod.propose_fix(store, store.student, store.student.draft_plan)
    second = audit_mod.propose_fix(store, store.student, store.student.draft_plan)
    assert first == second


def test_the_filler_module_is_a_passed_module_the_student_already_has(store):
    plan, _ = audit_mod.propose_fix(store, store.student, store.student.draft_plan)
    passed = {c.code for c in store.student.completed if c.status == "passed"}
    added = set(plan["general_elective"]) - set(store.student.draft_plan["general_elective"])
    assert added, "a gap must have been filled"
    assert added <= passed, "a repair may only spend credits she has already earned"


def test_repairing_twice_is_a_no_op_the_second_time(store):
    """Idempotence matters: a sweep runs repeatedly over the same record."""
    once, changes = audit_mod.propose_fix(store, store.student, store.student.draft_plan)
    assert changes
    _, again = audit_mod.propose_fix(store, store.student, once)
    assert again == []


def test_unassigned_modules_are_the_passed_modules_nobody_counted(store):
    unassigned = audit_mod.unassigned_modules(store, store.student, store.student.draft_plan)
    assigned = audit_mod.assigned_codes(store.student.draft_plan)
    passed = {c.code for c in store.student.completed if c.status == "passed"}
    assert set(unassigned) == passed - assigned
    assert "HIST10020" in unassigned


def test_term_cap_is_a_programme_constant_not_a_local_guess():
    assert MAX_TERM_CREDITS == 30


def test_both_specialisations_satisfy_the_same_stream_requirement(store):
    """Switching specialisation must be a swap, not a shortfall."""
    for modules in SPECIALISATION_MODULES.values():
        credits = sum(
            store.course(c).credits for c in modules if store.course(c)
        )
        assert credits == 15, f"{modules} is not 15 ECTS of stream"
