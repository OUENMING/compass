"""Prerequisites — where the irreversibility in scenario 1 actually comes from.

The interesting thing about a prerequisite gap is that "is it blocked?" and "can
it still be closed?" are different questions with different answers, and the
whole scenario lives in the gap between them. ECON20030 is unreachable today and
reachable next year, and the difference between those two facts is a year of this
student's life.
"""

from __future__ import annotations

from compass import prereq


def test_the_waiver_withdrawal_creates_a_real_gap(store):
    """She passed ECON10730 but not ECON10790, and the waiver covering that is gone."""
    missing = prereq.missing_prereqs(store, store.student, "ECON20030")
    assert missing == ["ECON10790"]


def test_the_gap_can_still_be_closed_but_only_through_one_module(store):
    ok, explanation = prereq.satisfiable(store, store.student, "ECON20030")
    assert ok is True, "her options have to be real, or the card is a dead end"
    assert "ECON10790" in explanation


def test_a_satisfied_prerequisite_reports_no_gap(store):
    assert prereq.missing_prereqs(store, store.student, "ECON30010") == []


def test_a_gap_that_cannot_be_closed_is_distinguished_from_one_that_can(store):
    """No seats left in the only route means the answer is genuinely no."""
    # Fill the only route. This has to go through the store: `store.course(...)`
    # hands back a fresh object, so assigning to it would change nothing on disk
    # and the test would "pass" against a world it never actually altered.
    store.take_seat("ECON10790", store.course("ECON10790").seats_left)
    assert store.course("ECON10790").seats_left == 0

    ok, explanation = prereq.satisfiable(store, store.student, "ECON20030")
    assert ok is False
    assert "no seats left" in explanation


def test_the_upstream_chain_is_the_full_path_not_just_one_hop(store):
    chain = prereq.chain_to(store, "ECON30010")
    assert "ECON20030" in chain
    assert "ECON10790" in chain, "the chain must go past the first blocked hop"


def test_unlocks_is_the_inverse_of_the_prerequisite_graph(store):
    """If A unlocks B, then B must list A as a prerequisite. Both directions or neither."""
    for course in store.courses:
        for unlocked in prereq.unlocks(store, course.code):
            assert course.code in unlocked.prerequisites


def test_a_module_unlocks_the_credits_sitting_behind_it(store):
    downstream = prereq.unlocks(store, "ECON10790")
    assert downstream, "ECON10790 is the gate to the whole quantitative stream"
    assert {c.code for c in downstream} >= {"ECON20030", "ECON20040"}


def test_in_progress_modules_can_count_or_not_depending_on_the_question(store):
    """Registering for the prerequisite is not the same as having passed it.

    The distinction is load-bearing: `check_module_eligibility` must say she is
    *not* eligible for ECON20030 until ECON10790 is a passed module, or the card
    would tell her she is fine when she is not.
    """
    from compass.tools.actions import register_modules
    assert "error" not in register_modules(["ECON10790"])

    strict = prereq.missing_prereqs(store, store.student, "ECON20030",
                                    include_in_progress=False)
    assert strict == ["ECON10790"]


def test_an_unknown_module_has_no_chain_and_no_prerequisites(store):
    assert prereq.chain_to(store, "NOPE101") == []
    assert prereq.unlocks(store, "NOPE101") == []


def test_a_passed_module_is_no_longer_missing(store):
    passed = prereq.passed_codes(store.student)
    assert "ECON10730" in passed
    assert "ECON10790" not in passed
