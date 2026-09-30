"""Tests for the client-side bridge. No server, no sockets."""

import random
import unittest

from ..client.session import LEAN_DEAL_PENALTY, Phase10Session
from ..data import (
    AP_POINT,
    BASE_HAND_SIZE, EXTRA_DRAW, HAND_SIZE_UPGRADE, LEAN_DEAL, LOCATION_NAME_TO_ID,
    MAX_SKIPS, MULLIGAN, PHASE_COUNT, PHASE_LOCK, PHASE_UNLOCK, SCORE_REDUCTION,
    SCORE_REDUCTION_VALUE, SKIP_CARD, WILD_CARD, WILD_THEFT,
    BUFF_SKIP, BUFF_WILD, DEFAULT_BUFF_POINTS,
    store_gate, store_location_name, store_points, store_prices,
)
from ..game.cards import STOCK_WILDS, WILD, Color, number_card
from ..game.engine import HandState
from ..game.game import RoundResult


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
        from ..data import TIERS

        s = session()
        hand = played(s, 5, state=HandState.WENT_OUT, wilds=0, draws=1)
        # Compared against TIERS rather than a literal list: the order is a
        # tuning decision that has changed once and may again, and what this
        # pins is "a perfect hand earns every tier", not which order they sit in.
        self.assertEqual(s.earned_tiers(hand), list(TIERS))

    def test_tiers_beyond_the_option_are_never_reported(self) -> None:
        # Those locations do not exist on the server. checks_per_phase takes a
        # prefix of TIERS, so a perfect hand earns exactly that prefix.
        from ..data import TIERS

        for count in range(1, len(TIERS) + 1):
            s = session(checks_per_phase=count)
            hand = played(s, 5, state=HandState.WENT_OUT, wilds=0, draws=1)
            self.assertEqual(s.earned_tiers(hand), list(TIERS[:count]),
                             f"checks_per_phase={count}")

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
        # Deal, discard and stock still account for every card dealt --
        # including the hands the opponents are holding, since they come off
        # the same deck.
        seated = sum(len(seat.hand) for seat in s.seats)
        self.assertEqual(
            len(hand.hand) + seated + len(hand.discard) + len(hand.stock),
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


class TestOpponents(unittest.TestCase):
    def opened(self, count=3, phase=1):
        s = session(opponents=count)
        s.set_items([PHASE_UNLOCK.format(phase)])
        hand = s.start_hand(phase)
        return s, hand

    def test_three_by_default(self) -> None:
        self.assertEqual(session().opponents, 3)

    def test_slot_data_carries_the_count(self) -> None:
        self.assertEqual(session(opponents=0).opponents, 0)
        self.assertEqual(session(opponents=2).opponents, 2)

    def test_seats_are_dealt_from_the_same_deck(self) -> None:
        s, hand = self.opened()
        self.assertEqual(len(s.seats), 3)
        seated = sum(len(seat.hand) for seat in s.seats)
        self.assertEqual(
            len(hand.hand) + seated + len(hand.discard) + len(hand.stock),
            96 + s.config.wilds_in_deck,
        )

    def test_no_opponents_means_an_empty_table(self) -> None:
        s, hand = self.opened(count=0)
        self.assertEqual(s.seats, [])
        self.assertEqual(
            len(hand.hand) + len(hand.discard) + len(hand.stock),
            96 + s.config.wilds_in_deck,
        )

    def test_seats_start_on_phase_one(self) -> None:
        s, _ = self.opened()
        self.assertEqual([seat.phase for seat in s.seats], [1, 1, 1])

    def test_a_seat_that_laid_down_moves_up_a_phase(self) -> None:
        s, hand = self.opened()
        s.seats[0].laid_down = True
        s.seats[1].laid_down = False
        hand.mark_failed("test")
        s.finish_hand(hand)
        self.assertEqual(s.opponent_phases[0], 2)
        self.assertEqual(s.opponent_phases[1], 1)

    def test_progress_stops_at_the_last_phase(self) -> None:
        # Against PHASE_COUNT, not a literal: this was hardcoded to 10 and
        # stayed there when the phases went to 20, so every seat stalled
        # halfway up the ladder while the player kept climbing.
        last = PHASE_COUNT
        # Seated on the last phase from the start: seats are built from
        # opponent_phases, so setting it after start_hand would only desync
        # the two.
        s = session(opponents=3)
        s._opponent_phases = [last] * 3
        s.set_items([PHASE_UNLOCK.format(1)])
        hand = s.start_hand(1)
        self.assertEqual([seat.phase for seat in s.seats], [last] * 3)
        for seat in s.seats:
            seat.laid_down = True
        hand.mark_failed("test")
        s.finish_hand(hand)
        self.assertEqual(s.opponent_phases, [last] * 3)

    def test_a_seat_below_the_last_phase_still_climbs(self) -> None:
        """The cap has to stop the top seat without pinning the rest -- a
        `min` that fired one phase early would pass the test above."""
        s = session(opponents=1)
        s._opponent_phases = [PHASE_COUNT - 1]
        s.set_items([PHASE_UNLOCK.format(1)])
        hand = s.start_hand(1)
        s.seats[0].laid_down = True
        hand.mark_failed("test")
        s.finish_hand(hand)
        self.assertEqual(s.opponent_phases, [PHASE_COUNT])

    # -- what the seats are caught holding ---------------------------------
    def test_a_seat_scores_what_it_is_caught_holding(self) -> None:
        s, hand = self.opened()
        s.seats[0].hand = [number_card(12, Color.RED), number_card(5, Color.BLUE)]
        s.seats[1].hand = []
        hand.mark_failed("test")
        s.finish_hand(hand)
        self.assertEqual(s.opponent_scores[0], 10 + 5)
        self.assertEqual(s.opponent_scores[1], 0)

    def test_seat_scores_accumulate_across_rounds(self) -> None:
        """A per-round number would read as a scoreboard and not be one."""
        s = session(opponents=1)
        s.set_items([PHASE_UNLOCK.format(1)])
        for _ in range(2):
            hand = s.start_hand(1)
            s.seats[0].hand = [number_card(3, Color.GREEN)]
            hand.mark_failed("test")
            s.finish_hand(hand)
        self.assertEqual(s.opponent_scores, [10])

    def test_seat_scores_survive_a_reconnect(self) -> None:
        s = session(opponents=2)
        s.set_items([PHASE_UNLOCK.format(1)])
        hand = s.start_hand(1)
        s.seats[0].hand = [WILD]
        s.seats[1].hand = []
        hand.mark_failed("test")
        s.finish_hand(hand)
        self.assertEqual(s.opponent_scores, [25, 0])

        fresh = session(opponents=2)
        self.assertTrue(fresh.load_payload(s.to_payload()))
        self.assertEqual(fresh.opponent_scores, s.opponent_scores)

    def test_a_save_without_seat_scores_still_loads(self) -> None:
        """Saves written before the seats kept score are the common case on
        the first connect after an update, and refusing one would throw away
        a run rather than a field."""
        s = session(opponents=2)
        payload = s.to_payload()
        del payload["opponent_scores"]
        fresh = session(opponents=2)
        self.assertTrue(fresh.load_payload(payload))
        self.assertEqual(fresh.opponent_scores, [0, 0])

    def test_progress_survives_a_reconnect(self) -> None:
        """Without this a reconnect reseats everyone on phase 1, which quietly
        hands the player an easier table than they had earned."""
        s = session(opponents=3)
        s._opponent_phases = [4, 2, 7]
        s.set_items([PHASE_UNLOCK.format(1)])
        hand = s.start_hand(1)
        hand.mark_failed("test")
        s.finish_hand(hand)

        fresh = session(opponents=3)
        self.assertTrue(fresh.load_payload(s.to_payload()))
        self.assertEqual(fresh.opponent_phases, s.opponent_phases)

    def test_losing_the_race_is_a_lost_round(self) -> None:
        s, hand = self.opened()
        for seat in s.seats:
            seat.laid_down, seat.hand, seat.went_out = True, [], False
        s.seats[0].hand = []
        s.table.end_of_turn()
        hand.draw()
        hand.discard_card(hand.hand[0])
        self.assertIs(hand.state, HandState.FAILED)
        self.assertEqual(hand.events[-1].detail["reason"], "opponent_out")
        self.assertEqual(hand.events[-1].detail["opponent"], s.seats[0].name)
        self.assertEqual(s.finish_hand(hand), [])


class TestStore(unittest.TestCase):
    """Buying a check instead of playing for it.

    Two numbers, deliberately: a slot opens at a gate on points *received*,
    which is what the seed's logic was generated against, and costs a price out
    of points *unspent*. The gate is what keeps the client from reporting a
    location the server thinks is unreachable; the price is what makes it a
    store rather than a threshold.
    """

    def store(self, slots=6, points=0) -> Phase10Session:
        s = session(store_slots=slots)
        s.set_items([AP_POINT] * points)
        return s

    def test_no_points_buys_nothing(self) -> None:
        s = self.store(points=0)
        self.assertIn("opens at 1", s.can_buy(1))

    def test_one_point_buys_the_first_slot(self) -> None:
        s = self.store(points=1)
        self.assertIsNone(s.can_buy(1))
        location = s.buy_slot(1)
        self.assertEqual(location, LOCATION_NAME_TO_ID[store_location_name(1)])
        self.assertEqual(s.points_left, 0)

    def test_a_slot_cannot_be_bought_twice(self) -> None:
        s = self.store(points=4)
        s.buy_slot(1)
        self.assertIn("already bought", s.can_buy(1))
        with self.assertRaises(RuntimeError):
            s.buy_slot(1)

    def test_the_gate_is_on_points_received_not_left(self) -> None:
        """Spending does not close a slot you had already opened. The gate is
        what the seed was generated against, and that never goes down."""
        s = self.store(points=store_gate(2))
        s.buy_slot(1)
        self.assertEqual(s.points_left, store_gate(2) - s.store_price(1))
        self.assertIsNone(s.can_buy(2))

    def test_an_open_slot_is_always_affordable(self) -> None:
        """The invariant the ladder exists for, checked exhaustively.

        A slot's gate is the sum of the cheapest prices up to it, so any set of
        slots whose gates you have met costs at most that gate -- which you
        have, or the gate would not be met. So the price can never strand a
        slot the gate has opened, whatever order you buy in. Every point count
        against every purchase order:
        """
        from itertools import permutations

        for points in range(store_points(6) + 1):
            for order in permutations(range(1, 7)):
                s = self.store(points=points)
                for slot in order:
                    refusal = s.can_buy(slot)
                    if refusal is None:
                        s.buy_slot(slot)
                    else:
                        self.assertNotIn(
                            "costs", refusal,
                            f"{points} points, order {order}: {refusal}",
                        )

    def test_every_order_is_affordable_with_a_full_purse(self) -> None:
        """The property the ladder exists for. Buying the dearest slots first
        must not strand the cheap ones."""
        s = self.store(points=store_points(6))
        for slot in (6, 5, 4, 3, 2, 1):
            self.assertIsNone(s.can_buy(slot), slot)
            s.buy_slot(slot)
        self.assertEqual(len(s.bought_slots), 6)

    def test_a_seed_without_a_store_refuses(self) -> None:
        s = self.store(slots=0, points=10)
        self.assertEqual(s.can_buy(1), "This seed has no store.")

    def test_a_slot_past_the_end_refuses(self) -> None:
        s = self.store(slots=4, points=10)
        self.assertIn("slots 1 to 4", s.can_buy(5))

    def test_purchases_survive_a_reconnect(self) -> None:
        s = self.store(points=store_points(6))
        s.buy_slot(1)
        s.buy_slot(5)
        fresh = session(store_slots=6)
        fresh.set_items([AP_POINT] * store_points(6))
        self.assertTrue(fresh.load_payload(s.to_payload()))
        self.assertEqual(fresh.bought_slots, {1, 5})
        self.assertEqual(fresh.points_left, s.points_left)

    # -- the one-use cards -------------------------------------------------

    def buying(self, buff_points=DEFAULT_BUFF_POINTS, slots=6):
        """A store with spare points and a hand open to buy a card into."""
        s = self.store(slots=slots, points=store_points(slots, buff_points))
        s.items[PHASE_UNLOCK.format(1)] = 1
        s.start_hand(1)
        return s

    def test_a_one_use_card_lands_in_your_hand(self) -> None:
        s = self.buying()
        held = len(s.hand.hand)
        card = s.buy_buff(BUFF_WILD)
        self.assertTrue(card.is_wild)
        self.assertEqual(len(s.hand.hand), held + 1)
        self.assertIn(card, s.hand.hand)
        self.assertEqual(s.hand.bought_cards, 1)

    def test_it_costs_no_draw(self) -> None:
        """It is not a draw. Spending the budget on it would make the card a
        worse deal than the draw it replaced, on the hand that could least
        afford it."""
        s = self.buying()
        before = s.hand.draws_used
        s.buy_buff(BUFF_SKIP)
        self.assertEqual(s.hand.draws_used, before)
        self.assertFalse(s.hand.drew_this_turn)

    def test_it_is_rebuyable(self) -> None:
        """Every point the ladder does not need, not just the buff budget. The
        slack is spendable too, and deliberately: it existed so the last slot
        was not hostage to where the final point landed, and the reservation
        now does that job outright, so holding it back on top would only make
        it a point nobody could ever use."""
        s = self.buying()
        spare = s.buff_points_left
        self.assertEqual(
            spare,
            store_points(6, DEFAULT_BUFF_POINTS) - sum(store_prices(6)))
        times = 0
        while s.can_buy_buff(BUFF_SKIP) is None:
            s.buy_buff(BUFF_SKIP)
            times += 1
        self.assertEqual(times, spare)
        self.assertEqual(s.buff_points_left, 0)

    def test_buying_a_card_can_never_strand_a_slot(self) -> None:
        """The property the reservation exists for, and the only thing about
        this feature that could break a seed rather than a round.

        Archipelago's logic reasons about points *received*; it cannot model
        one being spent. A player who spent the store's own money on cards
        would leave locations the seed was generated as reachable with no way
        left to reach them. So: every point count a default store can hold,
        spent down to the last card the store will sell, and then all 720
        orders the six slots can be bought in.
        """
        from itertools import permutations

        total = store_points(6, DEFAULT_BUFF_POINTS)
        for held in range(total + 1):
            spent = self.store(points=held)
            spent.items[PHASE_UNLOCK.format(1)] = 1
            spent.start_hand(1)
            while spent.can_buy_buff(BUFF_SKIP) is None:
                spent.buy_buff(BUFF_SKIP)
            bought = dict(spent.buffs_bought)
            for order in permutations(range(1, 7)):
                s = self.store(points=held)
                s.buffs_bought = dict(bought)
                for slot in order:
                    refusal = s.can_buy(slot)
                    if refusal is None:
                        s.buy_slot(slot)
                    else:
                        # Not affordable is the failure. Gated is fine: that is
                        # the seed's own logic, and it is on points received,
                        # which spending does not touch.
                        self.assertNotIn(
                            "unspent", refusal,
                            f"{held} points, spent on {bought}, "
                            f"order {order}: {refusal}",
                        )

    def test_every_order_still_works_after_buying_cards(self) -> None:
        """The dearest-first order is the one that strands the cheap slots, so
        it is the one worth spending against."""
        s = self.buying()
        while s.can_buy_buff(BUFF_WILD) is None:
            s.buy_buff(BUFF_WILD)
        for slot in (6, 5, 4, 3, 2, 1):
            self.assertIsNone(s.can_buy(slot), f"slot {slot}: {s.can_buy(slot)}")
            s.buy_slot(slot)
        self.assertEqual(len(s.bought_slots), 6)

    def test_the_refusal_says_where_the_points_went(self) -> None:
        # Exactly what the six slots cost, and no more.
        s = self.store(slots=6, points=sum(store_prices(6)))
        s.items[PHASE_UNLOCK.format(1)] = 1
        s.start_hand(1)
        refusal = s.can_buy_buff(BUFF_WILD)
        self.assertIsNotNone(refusal)
        self.assertIn("held for", refusal)

    def test_a_card_needs_a_hand_to_land_in(self) -> None:
        s = self.store(slots=6, points=store_points(6, DEFAULT_BUFF_POINTS))
        self.assertIn("start a round first", s.can_buy_buff(BUFF_WILD))

    def test_cards_bought_survive_a_reconnect(self) -> None:
        """Or a reload would hand the points back, and the cards would be free
        to anybody willing to restart the client."""
        s = self.buying()
        s.buy_buff(BUFF_WILD)
        fresh = session(store_slots=6)
        fresh.set_items([AP_POINT] * store_points(6, DEFAULT_BUFF_POINTS))
        self.assertTrue(fresh.load_payload(s.to_payload()))
        self.assertEqual(fresh.buffs_bought, {BUFF_WILD: 1})
        self.assertEqual(fresh.points_left, s.points_left)

    def test_a_save_from_before_the_cards_existed_still_loads(self) -> None:
        s = self.store(points=4)
        payload = s.to_payload()
        del payload["buffs_bought"]
        fresh = session(store_slots=6)
        self.assertTrue(fresh.load_payload(payload))
        self.assertEqual(fresh.buffs_bought, {})

    def test_a_save_without_purchases_still_loads(self) -> None:
        s = self.store(points=4)
        payload = s.to_payload()
        del payload["bought_slots"]
        fresh = session(store_slots=6)
        self.assertTrue(fresh.load_payload(payload))
        self.assertEqual(fresh.bought_slots, set())


class TestGoal(unittest.TestCase):
    """Mirrors the block of the same name in docs/test/session_test.mjs.

    The client and the world have to agree about what finishes a slot. A
    client that declares victory on a different count than the seed was
    generated for sends the goal early, and the server believes it.
    """

    def goal(self, **slot) -> Phase10Session:
        return session(**slot)

    def clear_up_to(self, s: Phase10Session, upto: int) -> Phase10Session:
        for phase in range(1, upto + 1):
            s.game.rounds.append(RoundResult(
                number=phase, phase=phase, state=HandState.WENT_OUT,
                score=0, draws_used=1, wilds_used=0, skips_played=0,
            ))
        return s

    def test_ten_of_twenty_is_not_the_default_goal(self) -> None:
        """The bug this class exists for. Ten was hardcoded when there were ten
        phases and never moved when the other ten arrived, so a default seed --
        whose own rule is HasAll(Phase 1..20 Clear) -- was won at half."""
        self.assertFalse(self.clear_up_to(self.goal(), 10).goal_met)

    def test_twenty_of_twenty_is(self) -> None:
        self.assertTrue(self.clear_up_to(self.goal(), PHASE_COUNT).goal_met)

    def test_phases_to_win_sets_the_length(self) -> None:
        self.assertTrue(self.clear_up_to(self.goal(phases_to_win=10), 10).goal_met)
        self.assertFalse(self.clear_up_to(self.goal(phases_to_win=14), 10).goal_met)
        self.assertTrue(self.clear_up_to(self.goal(phases_to_win=14), 14).goal_met)

    def test_it_is_the_named_phases_not_a_count(self) -> None:
        """Any three standing in for the first three is not what
        HasAll(Phase 1..N Clear) says, and the seed is generated on that."""
        s = self.goal(phases_to_win=3)
        for phase in (1, 2, 7):
            s.game.rounds.append(RoundResult(
                number=phase, phase=phase, state=HandState.WENT_OUT,
                score=0, draws_used=1, wilds_used=0, skips_played=0,
            ))
        self.assertEqual(len(s.cleared_phases), 3)
        self.assertFalse(s.goal_met)

    def test_a_seed_without_the_key_wants_every_phase(self) -> None:
        self.assertEqual(self.goal().phases_to_win, PHASE_COUNT)

    def test_phase_ten_is_untouched(self) -> None:
        s = self.clear_up_to(self.goal(goal=1, phases_to_win=PHASE_COUNT), 10)
        self.assertTrue(s.goal_met)


class TestRunEnds(unittest.TestCase):
    """Mirrors the block of the same name in docs/test/client_test.mjs.

    Reported from a real run: a seat finished phase 10 of a ten-phase run and
    the game carried on. Two things were wrong. Seats climbed to PHASE_COUNT
    rather than the run's cap, so one was on phase 16 of a ten-phase run; and
    nothing ended a free-play run in either direction, ever.
    """

    def free(self) -> Phase10Session:
        s = session(starting_draws=0, skip_mode="deny", checks_per_phase=0,
                    skips_in_deck=4, race_to_end=True, opponents=3)
        s.phase_cap = 10
        return s

    def test_a_seed_is_never_ended_by_a_seat(self) -> None:
        """It has its own goal; an opponent finishing is not an AP notion."""
        s = session()
        self.assertFalse(s.race_to_end)
        self.assertEqual(s.phase_cap, PHASE_COUNT)
        s.opponent_phases[0] = 99
        self.assertFalse(s.run_over)
        # Unlocked first: a seed gates on items, so "still playable" has to be
        # asked of a phase the slot actually holds.
        s.items[PHASE_UNLOCK.format(1)] = 1
        self.assertIsNone(s.can_play(1))

    def test_a_seat_past_the_cap_has_finished_and_ends_the_run(self) -> None:
        s = self.free()
        self.assertFalse(s.run_over)
        s.opponent_phases[2] = 11
        s._opponent_scores = [300, 200, 75]
        self.assertTrue(s.seat_finished(2))
        self.assertTrue(s.run_over)
        self.assertEqual(s.run_winner, ("Cy", 75))
        self.assertIn("run is over", s.can_play(1) or "")

    def test_the_lowest_score_among_finishers_wins(self) -> None:
        """More than one can finish in the round that ends it, and the box
        breaks that tie on score."""
        s = self.free()
        # Two finishers: a seat, and a second seat that scored less.
        s.opponent_phases[0] = 11
        s.opponent_phases[1] = 11
        s._opponent_scores = [120, 40, 0]
        self.assertTrue(s.run_over)
        self.assertEqual(s.run_winner, ("Bo", 40))
        # Cy scored least of all but never finished, so it does not win.
        self.assertFalse(s.seat_finished(2))

    def test_seats_stop_one_past_the_cap(self) -> None:
        """Not a phase anybody plays: it is where 'finished' is recorded."""
        s = self.free()
        s._opponent_phases = [10, 10, 10]
        for seat in s.seats:
            seat.laid_down = True
        s.advance_opponents()
        for phase in s.opponent_phases:
            self.assertLessEqual(phase, s.phase_cap + 1)
