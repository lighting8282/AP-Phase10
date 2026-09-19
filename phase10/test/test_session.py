"""Tests for the client-side bridge. No server, no sockets."""

import random
import unittest

from ..client.session import LEAN_DEAL_PENALTY, Phase10Session
from ..data import (
    BASE_HAND_SIZE, EXTRA_DRAW, HAND_SIZE_UPGRADE, LEAN_DEAL, LOCATION_NAME_TO_ID,
    MAX_SKIPS, MULLIGAN, PHASE_LOCK, PHASE_UNLOCK, SCORE_REDUCTION,
    SCORE_REDUCTION_VALUE, SKIP_CARD, WILD_CARD, WILD_THEFT,
)
from ..game.cards import STOCK_WILDS, Color, number_card
from ..game.engine import HandState


def session(**slot) -> Phase10Session:
    base = {"goal": 0, "starting_draws": 4, "checks_per_phase": 4}
    base.update(slot)
    return Phase10Session.from_slot_data(base, random.Random(0))


def played(s: Phase10Session, phase: int, *, state: HandState, wilds: int, draws: int):
    """A finished hand with a forced outcome, so awards can be tested directly."""
    s.items[PHASE_UNLOCK.format(phase)] = 1
    hand = s.start_hand(phase)
    hand.state = state
    hand.used_wilds_in_layout = wilds
    hand.draws_used = draws
    return hand


class TestConfigDerivation(unittest.TestCase):
    def test_baseline_with_no_items(self) -> None:
        c = session().config
        self.assertEqual(c.hand_size, BASE_HAND_SIZE)
        self.assertEqual(c.wilds_in_deck, 0)
        self.assertEqual(c.max_draws, 4)
        self.assertEqual(c.starting_skips, 0)
        # Skips are granted into hand, never shuffled into the draw pile.
        self.assertEqual(c.skips_in_deck, 0)

    def test_items_feed_straight_into_the_knobs(self) -> None:
        s = session(starting_draws=3)
        s.set_items([WILD_CARD] * 5 + [EXTRA_DRAW] * 4 + [HAND_SIZE_UPGRADE])
        c = s.config
        self.assertEqual(c.wilds_in_deck, 5)
        self.assertEqual(c.max_draws, 7)
        self.assertEqual(c.hand_size, BASE_HAND_SIZE + 1)

    def test_wilds_cannot_exceed_the_real_deck(self) -> None:
        s = session()
        s.set_items([WILD_CARD] * 20)
        self.assertEqual(s.config.wilds_in_deck, STOCK_WILDS)

    def test_skip_cards_are_granted_into_hand(self) -> None:
        s = session()
        s.set_items([SKIP_CARD] * 3)
        self.assertEqual(s.config.starting_skips, 3)
        self.assertEqual(s.config.skips_in_deck, 0)

    def test_skip_cards_are_capped(self) -> None:
        s = session()
        s.set_items([SKIP_CARD] * 9)
        self.assertEqual(s.config.starting_skips, MAX_SKIPS)


class TestTraps(unittest.TestCase):
    def test_lean_deal_applies_once_then_is_spent(self) -> None:
        s = session()
        s.set_items([LEAN_DEAL, PHASE_UNLOCK.format(1)])
        self.assertEqual(s.config.hand_size, BASE_HAND_SIZE - LEAN_DEAL_PENALTY)
        s.start_hand(1)
        s.game.hand = None  # abandon it; only the trap consumption matters here
        self.assertEqual(s.config.hand_size, BASE_HAND_SIZE)

    def test_wild_theft_applies_once_then_is_spent(self) -> None:
        s = session()
        s.set_items([WILD_CARD] * 4 + [WILD_THEFT, PHASE_UNLOCK.format(1)])
        self.assertEqual(s.config.wilds_in_deck, 3)
        s.start_hand(1)
        s.game.hand = None  # abandon it; only the trap consumption matters here
        self.assertEqual(s.config.wilds_in_deck, 4)

    def test_phase_lock_pins_you_after_a_failed_hand(self) -> None:
        s = session()
        s.set_items([PHASE_LOCK, PHASE_UNLOCK.format(1), PHASE_UNLOCK.format(2)])
        hand = played(s, 1, state=HandState.FAILED, wilds=0, draws=9)
        s.finish_hand(hand)
        self.assertEqual(s.locked_phase, 1)
        self.assertIsNotNone(s.can_play(2))
        self.assertIsNone(s.can_play(1))

    def test_clearing_the_locked_phase_releases_it(self) -> None:
        s = session()
        s.set_items([PHASE_LOCK, PHASE_UNLOCK.format(1)])
        s.finish_hand(played(s, 1, state=HandState.FAILED, wilds=0, draws=9))
        self.assertEqual(s.locked_phase, 1)
        s.finish_hand(played(s, 1, state=HandState.PHASE_LAID, wilds=1, draws=3))
        self.assertIsNone(s.locked_phase)


class TestAwards(unittest.TestCase):
    def test_a_failed_hand_awards_nothing(self) -> None:
        s = session()
        hand = played(s, 1, state=HandState.FAILED, wilds=0, draws=9)
        self.assertEqual(s.finish_hand(hand), [])
        self.assertEqual(s.hands_won, 0)

    def test_a_plain_clear_awards_only_cleared(self) -> None:
        s = session()
        s.set_items([EXTRA_DRAW] * 8 + [PHASE_UNLOCK.format(3)])
        hand = played(s, 3, state=HandState.PHASE_LAID, wilds=2, draws=10)
        self.assertEqual(s.earned_tiers(hand), ["Cleared"])

    def test_going_out_without_wilds_and_fast_awards_all_four(self) -> None:
        s = session()
        hand = played(s, 5, state=HandState.WENT_OUT, wilds=0, draws=1)
        self.assertEqual(s.earned_tiers(hand), ["Cleared", "Went Out", "No Wilds", "Under Par"])

    def test_tiers_beyond_the_option_are_never_reported(self) -> None:
        # Those locations do not exist on the server.
        s = session(checks_per_phase=2)
        hand = played(s, 5, state=HandState.WENT_OUT, wilds=0, draws=1)
        self.assertEqual(s.earned_tiers(hand), ["Cleared", "Went Out"])

    def test_awarded_ids_match_the_world_tables(self) -> None:
        s = session()
        hand = played(s, 7, state=HandState.PHASE_LAID, wilds=3, draws=10)
        ids = s.finish_hand(hand)
        self.assertIn(LOCATION_NAME_TO_ID["Phase 7 - Cleared"], ids)
        self.assertIn(LOCATION_NAME_TO_ID["Hands Won: 1"], ids)

    def test_checks_are_never_reported_twice(self) -> None:
        s = session()
        first = s.finish_hand(played(s, 1, state=HandState.PHASE_LAID, wilds=1, draws=10))
        second = s.finish_hand(played(s, 1, state=HandState.PHASE_LAID, wilds=1, draws=10))
        self.assertIn(LOCATION_NAME_TO_ID["Phase 1 - Cleared"], first)
        self.assertNotIn(LOCATION_NAME_TO_ID["Phase 1 - Cleared"], second)
        # ...but the second win still crosses a new milestone.
        self.assertIn(LOCATION_NAME_TO_ID["Hands Won: 2"], second)


class TestGoal(unittest.TestCase):
    def test_all_phases_needs_all_ten(self) -> None:
        s = session(goal=0)
        for phase in range(1, 10):
            s.finish_hand(played(s, phase, state=HandState.PHASE_LAID, wilds=1, draws=10))
        self.assertFalse(s.goal_met)
        s.finish_hand(played(s, 10, state=HandState.PHASE_LAID, wilds=1, draws=10))
        self.assertTrue(s.goal_met)

    def test_phase_ten_goal_ignores_the_others(self) -> None:
        s = session(goal=1)
        s.finish_hand(played(s, 1, state=HandState.PHASE_LAID, wilds=1, draws=10))
        self.assertFalse(s.goal_met)
        s.finish_hand(played(s, 10, state=HandState.PHASE_LAID, wilds=1, draws=10))
        self.assertTrue(s.goal_met)


class TestPlayability(unittest.TestCase):
    def test_locked_phases_are_refused(self) -> None:
        s = session()
        self.assertIsNotNone(s.can_play(4))
        s.set_items([PHASE_UNLOCK.format(4)])
        self.assertIsNone(s.can_play(4))


class TestDeathLink(unittest.TestCase):
    def test_off_by_default(self) -> None:
        self.assertFalse(session().death_link)

    def test_read_from_slot_data(self) -> None:
        self.assertTrue(session(death_link=True).death_link)

    def test_a_death_fails_the_hand_in_progress(self) -> None:
        s = session(death_link=True)
        s.items[PHASE_UNLOCK.format(1)] = 1
        hand = s.start_hand(1)
        killed = s.kill_hand()
        self.assertIs(killed, hand)
        self.assertIs(hand.state, HandState.FAILED)

    def test_a_death_between_rounds_costs_nothing(self) -> None:
        # Nothing to lose, so no invented penalty the player cannot see coming.
        s = session(death_link=True)
        self.assertIsNone(s.kill_hand())

    def test_a_death_cannot_undo_a_cleared_phase(self) -> None:
        s = session(death_link=True)
        hand = played(s, 2, state=HandState.PHASE_LAID, wilds=0, draws=2)
        self.assertIsNone(s.kill_hand(), "a finished hand must not be re-failed")
        self.assertIs(hand.state, HandState.PHASE_LAID)

    def test_a_killed_hand_still_settles_as_a_loss(self) -> None:
        s = session(death_link=True)
        s.items[PHASE_UNLOCK.format(1)] = 1
        s.start_hand(1)
        hand = s.kill_hand()
        self.assertEqual(s.finish_hand(hand), [], "a lost hand awards nothing")
        self.assertEqual(s.hands_won, 0)
        self.assertEqual(len(s.game.rounds), 1, "it still counts as a round played")


class TestMulligan(unittest.TestCase):
    def opened(self, copies: int = 1) -> Phase10Session:
        s = session()
        s.set_items([MULLIGAN] * copies + [PHASE_UNLOCK.format(1)])
        s.start_hand(1)
        return s

    def test_none_without_the_item(self) -> None:
        s = session()
        s.set_items([PHASE_UNLOCK.format(1)])
        s.start_hand(1)
        self.assertEqual(s.mulligans_left, 0)
        self.assertEqual(s.can_mulligan(), "No Mulligans left.")

    def test_redeals_the_hand(self) -> None:
        s = self.opened()
        before = [str(c) for c in s.hand.hand]
        self.assertIsNone(s.can_mulligan())
        s.use_mulligan()
        self.assertNotEqual(before, [str(c) for c in s.hand.hand])

    def test_costs_no_draw_and_leaves_a_full_table(self) -> None:
        s = self.opened()
        draws = s.hand.draws_left
        s.use_mulligan()
        hand = s.hand
        self.assertEqual(hand.draws_left, draws)
        self.assertEqual(len(hand.hand), s.config.hand_size)
        self.assertEqual(len(hand.discard), 1)
        # Deal, discard and stock still account for every card dealt.
        self.assertEqual(
            len(hand.hand) + len(hand.discard) + len(hand.stock),
            96 + s.config.wilds_in_deck,
        )

    def test_is_spent_once_used(self) -> None:
        s = self.opened(copies=2)
        s.use_mulligan()
        self.assertEqual(s.mulligans_left, 1)
        s.use_mulligan()
        self.assertEqual(s.mulligans_left, 0)
        self.assertEqual(s.can_mulligan(), "No Mulligans left.")

    def test_refused_after_the_first_draw(self) -> None:
        """The whole point of the restriction: insurance, not a free reroll."""
        s = self.opened()
        s.hand.draw()
        self.assertEqual(
            s.can_mulligan(), "A Mulligan only works before your first draw."
        )
        with self.assertRaises(ValueError):
            s.use_mulligan()
        self.assertEqual(s.mulligans_left, 1)  # a refusal must not spend it

    def test_refused_between_rounds(self) -> None:
        s = session()
        s.set_items([MULLIGAN])
        self.assertEqual(s.can_mulligan(), "No hand in progress.")

    def test_survives_a_reconnect(self) -> None:
        s = self.opened(copies=2)
        s.use_mulligan()
        s.game.hand = None

        fresh = session()
        fresh.set_items([MULLIGAN] * 2)
        self.assertTrue(fresh.load_payload(s.to_payload()))
        self.assertEqual(fresh.mulligans_left, 1)

    def test_old_saves_restore_with_none_spent(self) -> None:
        """Payloads written before Mulligans did anything must still load."""
        s = self.opened(copies=2)
        payload = s.to_payload()
        del payload["mulligans_used"]

        fresh = session()
        fresh.set_items([MULLIGAN] * 2)
        self.assertTrue(fresh.load_payload(payload))
        self.assertEqual(fresh.mulligans_left, 2)


class TestScoreReduction(unittest.TestCase):
    def scored(self, points: int, reductions: int = 0) -> Phase10Session:
        """A session carrying one lost round worth exactly `points`.

        Low number cards are five each, so the leftover hand is sized to the
        score wanted. What is under test is the reduction arithmetic, not how a
        hand comes to be worth points.
        """
        assert points % 5 == 0
        s = session()
        s.set_items([SCORE_REDUCTION] * reductions)
        hand = played(s, 1, state=HandState.FAILED, wilds=0, draws=9)
        hand.hand = [number_card(5, Color.RED) for _ in range(points // 5)]
        s.finish_hand(hand)
        assert s.game.total_score == points
        return s

    def test_no_reductions_leaves_the_score_alone(self) -> None:
        s = self.scored(80)
        self.assertEqual(s.score_reduction, 0)
        self.assertEqual(s.total_score, 80)

    def test_each_copy_takes_off_its_value(self) -> None:
        s = self.scored(80, reductions=2)
        self.assertEqual(s.score_reduction, 2 * SCORE_REDUCTION_VALUE)
        self.assertEqual(s.total_score, 80 - 2 * SCORE_REDUCTION_VALUE)

    def test_floored_at_zero(self) -> None:
        s = self.scored(10, reductions=4)
        self.assertEqual(s.total_score, 0)

    def test_the_scorecard_still_shows_what_the_round_cost(self) -> None:
        """A reduction forgives points; it does not rewrite the history."""
        s = self.scored(80, reductions=1)
        self.assertEqual(s.game.total_score, 80)
        self.assertEqual(s.total_score, 55)
