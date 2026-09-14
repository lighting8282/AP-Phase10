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

    def settle(self, hand) -> None:
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
        {"goal": 0, "starting_draws": 6, "checks_per_phase": 4}
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

    def test_locked_phase_is_refused(self) -> None:
        ctx, cp = make(phase=1)
        cp("/play 7")
        self.assertTrue(any("not unlocked" in line for line in cp.lines))
