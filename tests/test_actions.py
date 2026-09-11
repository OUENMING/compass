"""The actions — the part of Compass that is not chat.

Every test here is really asking one question: *would the registrar's system
have let this through?* An action that skips its checks is a demo, not a tool,
and the whole submission turns on the agent doing real work under the same rules
the student is bound by. So the refusals get as much attention as the successes:
they are the proof that "not just chat about it" did not become "does whatever it
likes".
"""

from __future__ import annotations

import json

from compass import audit as audit_mod
from compass.audit import MAX_TERM_CREDITS
from compass.tools import actions
from compass.tools.school_tools import get_student_record


def receipts(data_dir):
    path = data_dir / "receipts.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# --------------------------------------------------------------------------
# register_modules
# --------------------------------------------------------------------------


def test_registering_for_a_module_with_an_unmet_prerequisite_is_refused(store):
    """ECON30010 sits behind ECON20030, which sits behind the withdrawn waiver."""
    result = actions.register_modules(["ECON10790"])
    assert "error" not in result, "the prerequisite itself is open"

    blocked = actions.register_modules(["ECON30010"])
    assert "error" in blocked
    assert "ECON20030" in blocked["error"]


def test_registering_twice_is_refused(store):
    assert "error" not in actions.register_modules(["ECON10790"])
    again = actions.register_modules(["ECON10790"])
    assert "error" in again
    assert "Already registered" in again["error"]


def test_registering_for_a_module_that_does_not_exist_is_refused(store):
    assert "error" in actions.register_modules(["ZZZ99999"])


def test_registering_over_the_term_cap_is_refused(store):
    """Fill the term until it would breach the cap, then ask for one more."""
    student = store.student
    already = set(student.spring_registered) | set(student.planned)
    load = sum(store.course(c).credits for c in already if store.course(c))

    wanted = []
    for course in store.courses:
        if load > MAX_TERM_CREDITS:
            break
        if course.code in already or course.seats_left <= 0:
            continue
        if course.code in {c for c in wanted}:
            continue
        wanted.append(course.code)
        load += course.credits

    result = actions.register_modules(wanted)
    assert "error" in result
    assert str(MAX_TERM_CREDITS) in result["error"]
    assert "ECTS cap" in result["error"]


def test_a_refused_registration_takes_no_seat(store):
    """Validation happens before any mutation, or the demo is lying."""
    code = "ECON30010"
    before = store.course(code).enrolled
    assert "error" in actions.register_modules([code])
    assert store.course(code).enrolled == before


def test_a_successful_registration_really_takes_a_seat(store, data_dir):
    code = "ECON10790"
    before = store.course(code).enrolled
    receipt = actions.register_modules([code])

    assert receipt["detail"]["confirmation"].startswith("REG-2026-")
    assert store.course(code).enrolled == before + 1
    assert code in store.student.spring_registered
    assert receipts(data_dir)[-1]["action"] == "register_modules"


def test_confirmation_numbers_are_derived_not_random(store):
    """A replayed demo must produce the same receipt, so nothing here is random."""
    assert actions._confirmation("REG", "ECON10790") == \
        actions._confirmation("REG", "ECON10790")
    assert actions._confirmation("REG", "ECON10790") != \
        actions._confirmation("REG", "ECON20030")


# --------------------------------------------------------------------------
# drop_module
# --------------------------------------------------------------------------


def test_dropping_a_module_the_student_does_not_have_is_refused(store):
    assert "error" in actions.drop_module("ECON10790")


def test_dropping_a_registered_module_frees_the_seat(store):
    actions.register_modules(["ECON10790"])
    seated = store.course("ECON10790").enrolled
    receipt = actions.drop_module("ECON10790")
    assert receipt["detail"]["confirmation"].startswith("DRP-2026-")
    assert store.course("ECON10790").enrolled == seated - 1
    assert "ECON10790" not in store.student.spring_registered


# --------------------------------------------------------------------------
# resolve_library_hold
# --------------------------------------------------------------------------


def test_the_library_hold_offers_two_real_ways_out(store):
    """The choice between money and time is the student's. Both must work."""
    paid = actions.resolve_library_hold("pay_charge")
    assert paid["detail"]["charge_eur"] == 45.00
    assert paid["reversible"] is False


def test_returning_in_person_costs_nothing(store):
    returned = actions.resolve_library_hold("return_in_person")
    assert returned["detail"]["charge_eur"] == 0.00
    assert [h.kind for h in store.student.active_holds] == ["Advising"], (
        "only the library hold is cleared by this action"
    )


def test_an_unknown_method_is_refused(store):
    assert "error" in actions.resolve_library_hold("just_forget_about_it")


def test_clearing_the_hold_twice_is_refused(store):
    actions.resolve_library_hold("return_in_person")
    assert "error" in actions.resolve_library_hold("return_in_person")


# --------------------------------------------------------------------------
# set_specialisation
# --------------------------------------------------------------------------


def test_switching_specialisation_swaps_the_stream(store):
    receipt = actions.set_specialisation("general")
    plan = store.student.draft_plan

    assert store.student.specialisation == "general"
    assert set(plan["quant_stream"]) == set(actions.SPECIALISATION_MODULES["general"])
    assert receipt["detail"]["was"] == actions.SPECIALISATION_MODULES["quantitative"]


def test_switching_does_not_create_the_duplicate_the_plan_exists_to_catch(store):
    """Regression: ECON30040 is in the core as well, so it must be moved, not copied.

    The first version removed the outgoing modules from every group but not the
    incoming ones — so the switch put ECON30040 in both `econ_core` and
    `quant_stream`, and the next sweep's repair silently dropped it back out,
    leaving the stream five credits short. A fix that breaks the plan it is
    meant to complete is worse than no fix.
    """
    actions.set_specialisation("general")
    plan = store.student.draft_plan

    stream = set(plan["quant_stream"])
    elsewhere = set().union(
        *(set(codes) for gid, codes in plan.items() if gid != "quant_stream")
    )
    assert not (stream & elsewhere), "the switch created a double-count"

    # And the stream is still a whole stream, not a stream with a hole in it.
    actions.repair_degree_plan()
    groups = {g.id: g for g in audit_mod.audit(store, store.student.draft_plan).groups}
    assert groups["quant_stream"].met, "the new stream must be complete"
    assert groups["econ_core"].met, "and the core must not have been emptied"
    assert audit_mod.find_duplicates(store.student.draft_plan) == {}


def test_switching_to_the_specialisation_you_are_already_on_is_refused(store):
    assert "error" in actions.set_specialisation("quantitative")


def test_an_unknown_specialisation_is_refused(store):
    assert "error" in actions.set_specialisation("astrophysics")


# --------------------------------------------------------------------------
# repair_degree_plan / file_degree_plan
# --------------------------------------------------------------------------


def test_repair_then_file_is_the_forced_sequence(store, data_dir):
    """You cannot file a plan the School Office would reject."""
    blocked = actions.file_degree_plan()
    assert "error" in blocked
    assert "duplicate" in blocked["error"].lower()

    repaired = actions.repair_degree_plan()
    assert repaired["detail"]["changes"]
    assert "error" not in actions.file_degree_plan()
    assert store.student.degree_plan_filed is True
    assert [r["action"] for r in receipts(data_dir)] == [
        "repair_degree_plan", "file_degree_plan"
    ]


def test_repairing_a_clean_plan_is_refused_rather_than_faked(store):
    actions.repair_degree_plan()
    again = actions.repair_degree_plan()
    assert "error" in again
    assert "nothing to repair" in again["error"]


def test_filing_twice_is_refused(store):
    actions.repair_degree_plan()
    actions.file_degree_plan()
    assert "error" in actions.file_degree_plan()


def test_filing_clears_the_advising_hold(store):
    actions.repair_degree_plan()
    actions.file_degree_plan()
    kinds = {h.kind for h in store.student.active_holds}
    assert "Advising" not in kinds


# --------------------------------------------------------------------------
# notify_advisor
# --------------------------------------------------------------------------


def test_notify_advisor_is_recorded_and_marked_irreversible(store, data_dir):
    """You cannot unsend a message to a person. The receipt must say so."""
    receipt = actions.notify_advisor("Can we discuss the ECON20030 waiver?")
    assert receipt["reversible"] is False
    assert receipts(data_dir)[-1]["detail"]["body"].startswith("Can we discuss")


# --------------------------------------------------------------------------
# The capability index
# --------------------------------------------------------------------------


def test_every_action_is_reachable_by_name(store):
    assert set(actions.ACTION_BY_NAME) == {
        "register_modules", "drop_module", "resolve_library_hold",
        "set_specialisation", "repair_degree_plan", "file_degree_plan",
        "notify_advisor",
    }


def test_the_read_tool_reports_hold_status_unmistakably(store):
    """A cleared hold still reads like an alarm. The record must say otherwise."""
    actions.resolve_library_hold("return_in_person")
    record = get_student_record()

    assert "LIB-2026-7781" not in record["active_hold_ids"]
    library = next(h for h in record["holds"] if h["id"] == "LIB-2026-7781")
    assert library["cleared"] is True
    assert library["status"].startswith("CLEARED")
    # The description is unchanged — that is exactly why `status` has to exist.
    assert "block propagates to registration" in library["description"]
