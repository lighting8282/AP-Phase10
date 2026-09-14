"""Tests for the multi-hand game and its scorecard. Runnable directly."""

import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "phase10"))

import random

from game.cards import SKIP, WILD, hand_score, number_card
from game.cards import Color
from game.engine import GameConfig, HandState, PhaseHand
from game.game import Phase10Game, RoundResult

R = Color.RED


def finished(game, phase, state, leftovers, config=None):
    """Run a round to a forced outcome with a known leftover hand."""
    hand = game.start_round(phase, config or GameConfig(max_draws=8))
    hand.state = state
    hand.hand = list(leftovers)
    return game.finish_round(hand)


def test_round_numbers_increment():
    g = Phase10Game(random.Random(1))
    assert g.round_number == 1
    finished(g, 1, HandState.PHASE_LAID, [])
    assert g.round_number == 2
    finished(g, 2, HandState.FAILED, [WILD])
    assert g.round_number == 3
    assert [r.number for r in g.rounds] == [1, 2]


def test_going_out_scores_nothing():
    g = Phase10Game(random.Random(1))
    r = finished(g, 3, HandState.WENT_OUT, [])
    assert r.score == 0
    assert r.went_out and r.cleared
    assert g.total_score == 0


def test_leftovers_after_laying_down_still_cost():
    g = Phase10Game(random.Random(1))
    leftovers = [number_card(4, R), number_card(11, R), WILD]
    r = finished(g, 5, HandState.PHASE_LAID, leftovers)
    assert r.score == hand_score(leftovers) == 5 + 10 + 25
    assert r.cleared and not r.went_out


def test_a_failed_hand_costs_the_whole_hand():
    g = Phase10Game(random.Random(1))
    leftovers = [number_card(2, R), SKIP, WILD]
    r = finished(g, 7, HandState.FAILED, leftovers)
    assert r.score == 5 + 15 + 25
    assert not r.cleared


def test_total_score_accumulates_across_rounds():
    g = Phase10Game(random.Random(1))
    finished(g, 1, HandState.PHASE_LAID, [number_card(3, R)])      # 5
    finished(g, 2, HandState.FAILED, [number_card(12, R), WILD])   # 35
    finished(g, 3, HandState.WENT_OUT, [])                          # 0
    assert g.total_score == 40
    assert g.rounds_won == 2


def test_cleared_phases_tracks_only_wins():
    g = Phase10Game(random.Random(1))
    finished(g, 4, HandState.PHASE_LAID, [])
    finished(g, 6, HandState.FAILED, [WILD])
    assert g.cleared_phases == {4}


def test_best_round_is_the_cheapest_win():
    g = Phase10Game(random.Random(1))
    finished(g, 1, HandState.PHASE_LAID, [number_card(12, R)])  # 10
    finished(g, 2, HandState.WENT_OUT, [])                       # 0
    finished(g, 3, HandState.FAILED, [])                         # a loss, ignored
    assert g.best_round.phase == 2
    assert g.best_round.score == 0


def test_best_round_is_none_before_any_win():
    g = Phase10Game(random.Random(1))
    finished(g, 1, HandState.FAILED, [WILD])
    assert g.best_round is None


def test_history_is_per_phase():
    g = Phase10Game(random.Random(1))
    finished(g, 2, HandState.PHASE_LAID, [])
    finished(g, 5, HandState.FAILED, [WILD])
    finished(g, 2, HandState.WENT_OUT, [])
    assert [r.phase for r in g.history_for(2)] == [2, 2]
    assert len(g.history_for(5)) == 1


def test_cannot_start_a_round_while_one_is_live():
    g = Phase10Game(random.Random(1))
    g.start_round(1, GameConfig(max_draws=8))
    try:
        g.start_round(2, GameConfig(max_draws=8))
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected a refusal while a round is in progress")


def test_cannot_finish_a_round_still_in_progress():
    g = Phase10Game(random.Random(1))
    g.start_round(1, GameConfig(max_draws=8))
    try:
        g.finish_round()
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected a refusal for an unfinished round")


def test_config_is_taken_per_round_not_frozen():
    """Items keep arriving, so later rounds must see the newer deck."""
    g = Phase10Game(random.Random(1))
    lean = GameConfig(hand_size=8, wilds_in_deck=0, max_draws=8)
    rich = GameConfig(hand_size=12, wilds_in_deck=8, max_draws=20)
    first = g.start_round(1, lean)
    assert len(first.hand) == 8
    g.finish_round(_forced(first))
    second = g.start_round(1, rich)
    assert len(second.hand) == 12
    assert second.config.max_draws == 20


def _forced(hand):
    hand.state = HandState.FAILED
    return hand


def test_scorecard_reports_totals():
    g = Phase10Game(random.Random(1))
    assert "No rounds played yet." in g.scorecard()
    finished(g, 1, HandState.WENT_OUT, [])
    finished(g, 2, HandState.FAILED, [WILD])
    card = g.scorecard()
    assert any("2 rounds | 1 won | 25 points total" in line for line in card)
    assert any(line.startswith("best:") for line in card)


def test_scorecard_elides_old_rounds():
    g = Phase10Game(random.Random(1))
    for _ in range(15):
        finished(g, 1, HandState.WENT_OUT, [])
    card = g.scorecard(limit=5)
    assert any("10 earlier round(s)" in line for line in card)


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
