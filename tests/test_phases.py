"""Tests for the phase solver. Runnable via pytest or directly."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import random
import time

from phase10.cards import (
    Color, Kind, Card, SKIP, WILD, build_deck, number_card, shuffled_deck, hand_score,
)
from phase10.phases import (
    PHASES, SET, RUN, COLOR, solve_phase, can_complete, phase_card_count, phase_description,
)

R, B, G, Y = Color.RED, Color.BLUE, Color.GREEN, Color.YELLOW
n = number_card


def _ranks(group):
    return sorted(c.rank for c in group if c.is_number)


def _wilds(group):
    return sum(1 for c in group if c.is_wild)


def test_deck_composition():
    d = build_deck()
    assert len(d) == 108
    assert sum(c.is_number for c in d) == 96
    assert sum(c.is_wild for c in d) == 8
    assert sum(c.is_skip for c in d) == 4
    assert build_deck(wilds=0, skips=0) == [c for c in build_deck() if c.is_number]


def test_scoring_values():
    assert n(1, R).points == 5 and n(9, R).points == 5
    assert n(10, R).points == 10 and n(12, R).points == 10
    assert SKIP.points == 15 and WILD.points == 25
    assert hand_score([n(3, R), n(11, B), WILD, SKIP]) == 5 + 10 + 25 + 15


def test_phase_1_two_sets_of_three():
    hand = [n(4, R), n(4, B), n(4, G), n(9, R), n(9, B), n(9, Y)]
    layout = solve_phase(hand, PHASES[1])
    assert layout is not None
    assert sorted(len(g) for g in layout) == [3, 3]
    assert {tuple(_ranks(g)) for g in layout} == {(4, 4, 4), (9, 9, 9)}


def test_phase_1_fails_without_second_set():
    hand = [n(4, R), n(4, B), n(4, G), n(9, R), n(9, B), n(7, Y)]
    assert solve_phase(hand, PHASES[1]) is None


def test_wild_substitutes_in_run():
    # Phase 6 is a run of 9; supply 8 naturals and one wild for the gap.
    hand = [n(r, R) for r in (2, 3, 4, 6, 7, 8, 9, 10)] + [WILD]
    layout = solve_phase(hand, PHASES[6])
    assert layout is not None
    assert len(layout[0]) == 9
    assert _wilds(layout[0]) == 1


def test_wild_must_go_inside_the_run():
    """The case that forces real search rather than greedy natural-first.

    Phase 2 is SET(3) + RUN(4). The only rank with three copies is 5, and the
    run 8-9-10-11 is missing its 10 with no natural 10 in hand. Spending the
    wild on the set would leave the run unfillable, so the only lay-down that
    works puts the wild inside the run.
    """
    hand = [n(5, R), n(5, B), n(5, G), n(8, R), n(9, R), n(11, R), WILD]
    layout = solve_phase(hand, PHASES[2])
    assert layout is not None
    the_set = next(g for g in layout if len(g) == 3)
    the_run = next(g for g in layout if len(g) == 4)
    assert _ranks(the_set) == [5, 5, 5] and _wilds(the_set) == 0
    assert _ranks(the_run) == [8, 9, 11] and _wilds(the_run) == 1


def test_same_shape_fails_without_the_wild():
    # Identical to the above but the wild is replaced by a useless 2.
    hand = [n(5, R), n(5, B), n(5, G), n(8, R), n(9, R), n(11, R), n(2, B)]
    assert solve_phase(hand, PHASES[2]) is None


def test_multiple_valid_layouts_any_accepted():
    """Several legal lay-downs exist here; the solver need only find one."""
    hand = [n(5, R), n(5, B), n(5, G), n(3, R), n(4, R), n(6, R), WILD]
    layout = solve_phase(hand, PHASES[2])
    assert layout is not None
    assert sorted(len(g) for g in layout) == [3, 4]
    used = [c for g in layout for c in g]
    assert len(used) == 7 and sum(1 for c in used if c.is_wild) <= 1


def test_runs_do_not_wrap_around():
    hand = [n(r, R) for r in (10, 11, 12, 1, 2, 3, 4)]
    assert solve_phase(hand, PHASES[4]) is None  # RUN(7)
    ok = [n(r, R) for r in (3, 4, 5, 6, 7, 8, 9)]
    assert solve_phase(ok, PHASES[4]) is not None


def test_run_rejects_duplicate_ranks():
    # Seven cards but only six distinct ranks -- not a run of 7.
    hand = [n(r, R) for r in (3, 4, 5, 5, 6, 7, 8)]
    assert solve_phase(hand, PHASES[4]) is None


def test_all_wild_group_rejected_by_default():
    hand = [WILD] * 6
    assert solve_phase(hand, PHASES[1]) is None
    assert solve_phase(hand, PHASES[1], min_naturals_per_group=0) is not None


def test_skips_are_never_usable():
    hand = [n(4, R), n(4, B), SKIP, n(9, R), n(9, B), SKIP]
    assert solve_phase(hand, PHASES[1]) is None
    # Skips cannot stand in even when the rest is present.
    hand2 = [n(4, R), n(4, B), n(4, G), n(9, R), n(9, B), SKIP]
    assert solve_phase(hand2, PHASES[1]) is None


def test_phase_8_seven_of_one_color():
    hand = [n(r, B) for r in (1, 3, 5, 7, 9, 11)] + [WILD] + [n(2, R)]
    layout = solve_phase(hand, PHASES[8])
    assert layout is not None
    assert len(layout[0]) == 7
    assert all(c.color is Color.BLUE for c in layout[0] if c.is_number)


def test_phase_8_rejects_mixed_colors():
    hand = [n(1, B), n(2, B), n(3, B), n(4, R), n(5, R), n(6, G), n(7, Y)]
    assert solve_phase(hand, PHASES[8]) is None


def test_phase_9_uneven_sets():
    hand = [n(6, R), n(6, B), n(6, G), n(6, Y), n(6, R), n(2, R), n(2, B)]
    layout = solve_phase(hand, PHASES[9])  # SET(5) + SET(2)
    assert layout is not None
    assert sorted(len(g) for g in layout) == [2, 5]


def test_layout_uses_only_cards_from_hand():
    hand = [n(5, R), n(5, B), n(5, G), n(3, R), n(4, R), n(6, R), WILD]
    layout = solve_phase(hand, PHASES[2])
    used = [c for g in layout for c in g]
    pool = list(hand)
    for c in used:
        assert c in pool, f"{c} not available in hand"
        pool.remove(c)
    assert len(used) == phase_card_count(PHASES[2]) == 7


def test_all_phases_have_sane_specs():
    for p in range(1, 11):
        assert phase_card_count(PHASES[p]) <= 10, p
        assert phase_description(p)


def test_solver_is_fast_on_random_hands():
    rng = random.Random(1234)
    start = time.perf_counter()
    solved = 0
    trials = 0
    for _ in range(400):
        deck = shuffled_deck(rng)
        hand = deck[:11]
        for p in range(1, 11):
            trials += 1
            if solve_phase(hand, PHASES[p]) is not None:
                solved += 1
    elapsed = time.perf_counter() - start
    assert elapsed < 10.0, f"solver too slow: {elapsed:.2f}s for {trials} solves"
    print(f"    [perf] {trials} solves in {elapsed:.2f}s, {solved} satisfiable")


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as e:
            failed += 1
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
