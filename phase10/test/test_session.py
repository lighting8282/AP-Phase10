"""Tests for the client-side bridge. No server, no sockets."""

import random
import unittest

from ..client.session import LEAN_DEAL_PENALTY, Phase10Session
from ..data import (
    BASE_HAND_SIZE, EXTRA_DRAW, HAND_SIZE_UPGRADE, LEAN_DEAL, LOCATION_NAME_TO_ID,
    PHASE_LOCK, PHASE_UNLOCK, WILD_CARD, WILD_THEFT,
)
from ..game.cards import STOCK_WILDS
from ..game.engine import HandState


def session(**slot) -> Phase10Session:
    base = {"goal": 0, "starting_draws": 4, "checks_per_phase": 4, "include_skips": False}
    base.update(slot)
    return Phase10Session.from_slot_data(base)


def played(s: Phase10Session, phase: int, *, state: HandState, wilds: int, draws: int):
    """A finished hand with a forced outcome, so awards can be tested directly."""
    s.items[PHASE_UNLOCK.format(phase)] = 1
    hand = s.start_hand(phase, random.Random(0))
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

    def test_skips_follow_the_option(self) -> None:
        self.assertEqual(session(include_skips=True).config.skips_in_deck, 4)


class TestTraps(unittest.TestCase):
    def test_lean_deal_applies_once_then_is_spent(self) -> None:
        s = session()
        s.set_items([LEAN_DEAL, PHASE_UNLOCK.format(1)])
        self.assertEqual(s.config.hand_size, BASE_HAND_SIZE - LEAN_DEAL_PENALTY)
        s.start_hand(1, random.Random(0))
        self.assertEqual(s.config.hand_size, BASE_HAND_SIZE)

    def test_wild_theft_applies_once_then_is_spent(self) -> None:
        s = session()
        s.set_items([WILD_CARD] * 4 + [WILD_THEFT, PHASE_UNLOCK.format(1)])
        self.assertEqual(s.config.wilds_in_deck, 3)
        s.start_hand(1, random.Random(0))
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
