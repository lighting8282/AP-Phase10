"""Drive the client command path without a server.

The live round trip exercises /play and /auto, but whether a Skip Card reaches
you depends on where the fill happened to put one -- so the dig commands need
covering here rather than by luck.
"""

import random
import unittest

# Importing the client pulls in CommonClient, which calls ModuleUpdate.update()
# at import time -- that prompts for missing optional requirements (kivy and
# friends) and dies on EOF with no stdin. Archipelago's own test/__init__.py
# sets this same flag for the same reason; it has to happen before the import.
import ModuleUpdate

ModuleUpdate.update_ran = True

# Note this alone is not sticky. ModuleUpdate.RequirementsSet.add runs
# `update_ran &= _skip_update` every time a world registers a requirements
# file, so any world discovered after this line flips it back, and the next
# update() call blocks on a prompt that EOFs -- naming whichever world import
# order happened to reach, which is what makes it look random. Run the suite
# with SKIP_REQUIREMENTS_UPDATE=1 to pin it properly; that is read before
# ModuleUpdate loads, which a test module cannot be.

from ..client.context import Phase10CommandProcessor
from ..client.session import Phase10Session
from ..data import PHASE_UNLOCK, SKIP_CARD
from ..game.engine import HandState


class FakeContext:
    """Only what the command processor actually touches."""

    def __init__(self, session: Phase10Session) -> None:
        self.session = session
        self.rng = random.Random(11)
        self.settled: list = []
        self.lines: list[str] = []

    def report_table(self) -> None:
        """Read out the seats' turns, as the real context does. Without this
        the fake diverges from the thing it stands in for, and a command that
        calls it dies on an attribute rather than being tested."""
        table = self.session.table
        if table is None:
            return
        for who, what in table.drain_log():
            self.lines.append(f"{who} {what}")

    def settle(self, hand, quiet: bool = False) -> None:
        self.settled.append(hand)
        self.session.finish_hand(hand)


class RecordingProcessor(Phase10CommandProcessor):
    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self.lines: list[str] = []

    def output(self, text: str) -> None:
        self.lines.append(text)


def make(skips: int = 2, phase: int = 1):
    session = Phase10Session.from_slot_data(
        {"goal": 0, "starting_draws": 6, "checks_per_phase": 4}, random.Random(11)
    )
    session.set_items([PHASE_UNLOCK.format(phase)] + [SKIP_CARD] * skips)
    ctx = FakeContext(session)
    return ctx, RecordingProcessor(ctx)


class TestSkipCommands(unittest.TestCase):
    def test_skip_reveals_and_take_keeps(self) -> None:
        ctx, cp = make()
        cp("/play 1")
        hand = ctx.session.hand
        self.assertEqual(hand.skips_in_hand, 2)

        cp("/skip")
        self.assertTrue(hand.dig_pending)
        self.assertTrue(any("top of the pile" in line for line in cp.lines))

        before = len(hand.hand)
        cp("/take 1")
        self.assertFalse(hand.dig_pending)
        self.assertEqual(len(hand.hand), before + 1)
        self.assertEqual(hand.skips_in_hand, 1)
        self.assertEqual(hand.draws_used, 0, "a dig must not spend a draw")

    def test_take_without_a_dig_is_refused(self) -> None:
        ctx, cp = make()
        cp("/play 1")
        cp("/take 0")
        self.assertTrue(any("Play a Skip first" in line for line in cp.lines))

    def test_skip_without_one_in_hand_is_refused(self) -> None:
        ctx, cp = make(skips=0)
        cp("/play 1")
        cp("/skip")
        self.assertTrue(any("no Skip in hand" in line for line in cp.lines))

    def test_hand_readout_advertises_skips(self) -> None:
        ctx, cp = make()
        cp("/play 1")
        self.assertTrue(any("Skip(s) in hand" in line for line in cp.lines))

    def test_status_reports_skips_per_hand(self) -> None:
        ctx, cp = make(skips=3)
        cp("/status")
        self.assertTrue(any("skips per hand 3" in line for line in cp.lines))


class TestPlayCommands(unittest.TestCase):
    def test_auto_finishes_the_hand_and_settles(self) -> None:
        ctx, cp = make(skips=2)
        cp("/play 1")
        cp("/auto")
        self.assertEqual(len(ctx.settled), 1)
        self.assertIsNot(ctx.settled[0].state, HandState.IN_PROGRESS)

    def test_grind_plays_many_rounds(self) -> None:
        ctx, cp = make(skips=1)
        cp("/grind 1 6")
        self.assertEqual(len(ctx.session.game.rounds), 6)
        self.assertTrue(any("Played 6 round(s)" in line for line in cp.lines))

    def test_grind_is_capped(self) -> None:
        ctx, cp = make()
        cp("/grind 1 500")
        self.assertLessEqual(len(ctx.session.game.rounds), 50)

    def test_grind_refuses_mid_round(self) -> None:
        ctx, cp = make()
        cp("/play 1")
        cp("/grind 1 3")
        self.assertTrue(any("Finish the current round first" in line for line in cp.lines))

    def test_grind_stops_on_a_locked_phase(self) -> None:
        ctx, cp = make()
        cp("/grind 7 3")
        self.assertEqual(len(ctx.session.game.rounds), 0)
        self.assertTrue(any("not unlocked" in line for line in cp.lines))

    def test_score_reports_the_running_total(self) -> None:
        ctx, cp = make()
        cp("/grind 1 3")
        cp.lines.clear()
        cp("/score")
        self.assertTrue(any("3 rounds" in line and "points total" in line for line in cp.lines))

    def test_score_is_empty_before_play(self) -> None:
        ctx, cp = make()
        cp("/score")
        self.assertTrue(any("No rounds played yet" in line for line in cp.lines))

    def test_status_shows_round_and_score(self) -> None:
        ctx, cp = make()
        cp("/grind 1 2")
        cp.lines.clear()
        cp("/status")
        self.assertTrue(any("round 3" in line and "points" in line for line in cp.lines))

    def test_locked_phase_is_refused(self) -> None:
        ctx, cp = make(phase=1)
        cp("/play 7")
        self.assertTrue(any("not unlocked" in line for line in cp.lines))


class TestSortCommand(unittest.TestCase):
    """`/sort` is the Kivy client's half of the browser's Sort button."""

    def test_sort_orders_the_hand_by_number(self) -> None:
        ctx, cp = make()
        cp("/play 1")
        ranks = [c.rank for c in ctx.session.hand.hand if c.is_number]
        cp("/sort")
        sorted_ranks = [c.rank for c in ctx.session.hand.hand if c.is_number]
        self.assertEqual(sorted_ranks, sorted(ranks))
        self.assertTrue(any("sorted by number" in line for line in cp.lines))

    def test_sort_c_groups_the_colours(self) -> None:
        ctx, cp = make()
        cp("/play 1")
        cp("/sort c")
        colours = [c.color for c in ctx.session.hand.hand if c.is_number]
        # Grouped means each colour forms one unbroken run, so the list of
        # colours with repeats collapsed has no colour in it twice.
        runs = [colour for i, colour in enumerate(colours)
                if i == 0 or colours[i - 1] != colour]
        self.assertEqual(len(runs), len(set(runs)), f"a colour was split up: {colours}")
        self.assertTrue(any("sorted by colour" in line for line in cp.lines))

    def test_the_specials_sort_to_the_end(self) -> None:
        ctx, cp = make(skips=2)
        cp("/play 1")
        cp("/sort")
        tail = ctx.session.hand.hand[-2:]
        self.assertTrue(all(c.is_skip for c in tail), "the two Skips should be last")

    def test_sorting_spends_no_draw_and_ends_no_turn(self) -> None:
        ctx, cp = make()
        cp("/play 1")
        hand = ctx.session.hand
        cp("/sort")
        self.assertEqual(hand.draws_used, 0)
        self.assertFalse(hand.drew_this_turn)
        self.assertIs(hand.state, HandState.IN_PROGRESS)

    def test_sorting_without_a_hand_says_so(self) -> None:
        ctx, cp = make()
        cp("/sort")
        self.assertTrue(any("No hand" in line for line in cp.lines))
