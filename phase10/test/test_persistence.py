"""Scorecard persistence across reconnect.

The payload round-trips through Archipelago's Data Storage, so it arrives back
over the network. Nothing in it is trusted: a malformed or foreign payload must
be discarded whole rather than half-applied.
"""

import random
import unittest

from ..client.session import Phase10Session
from ..data import PHASE_LOCK, PHASE_UNLOCK
from ..game.engine import HandState
from ..game.game import SAVE_VERSION


def session() -> Phase10Session:
    return Phase10Session.from_slot_data(
        {"goal": 0, "starting_draws": 6, "checks_per_phase": 4}, random.Random(3)
    )


def play(s: Phase10Session, phase: int, state: HandState) -> None:
    s.items[PHASE_UNLOCK.format(phase)] = 1
    hand = s.start_hand(phase)
    hand.state = state
    if state is HandState.WENT_OUT:
        hand.hand = []
    s.finish_hand(hand)


class TestRoundTrip(unittest.TestCase):
    def test_score_and_rounds_survive(self) -> None:
        before = session()
        play(before, 2, HandState.PHASE_LAID)
        play(before, 5, HandState.FAILED)
        play(before, 7, HandState.WENT_OUT)
        payload = before.to_payload()

        after = session()
        self.assertTrue(after.load_payload(payload))
        self.assertEqual(len(after.game.rounds), 3)
        self.assertEqual(after.total_score, before.total_score)
        self.assertEqual(after.hands_won, before.hands_won)
        self.assertEqual(after.cleared_phases, before.cleared_phases)
        self.assertEqual(after.game.round_number, 4)

    def test_goal_progress_survives(self) -> None:
        before = session()
        for phase in range(1, 11):
            play(before, phase, HandState.PHASE_LAID)
        self.assertTrue(before.goal_met)

        after = session()
        self.assertFalse(after.goal_met)
        self.assertTrue(after.load_payload(before.to_payload()))
        self.assertTrue(after.goal_met)

    def test_round_details_survive(self) -> None:
        before = session()
        play(before, 4, HandState.WENT_OUT)
        after = session()
        after.load_payload(before.to_payload())
        a, b = after.game.rounds[0], before.game.rounds[0]
        self.assertEqual((a.number, a.phase, a.state, a.score), (b.number, b.phase, b.state, b.score))
        self.assertTrue(a.went_out and a.cleared)

    def test_consumed_traps_survive(self) -> None:
        before = session()
        before.items[PHASE_LOCK] = 1
        play(before, 1, HandState.FAILED)
        self.assertEqual(before.locked_phase, 1)

        after = session()
        after.items[PHASE_LOCK] = 1
        self.assertTrue(after.load_payload(before.to_payload()))
        self.assertEqual(after.locked_phase, 1)
        self.assertEqual(after.pending(PHASE_LOCK), 0, "a spent trap must not come back")


class TestUntrustedPayloads(unittest.TestCase):
    def rejects(self, payload) -> None:
        s = session()
        play(s, 1, HandState.PHASE_LAID)
        rounds_before = list(s.game.rounds)
        self.assertFalse(s.load_payload(payload))
        self.assertEqual(s.game.rounds, rounds_before, "a rejected payload must change nothing")

    def test_none_is_rejected(self) -> None:
        self.rejects(None)

    def test_wrong_type_is_rejected(self) -> None:
        self.rejects("not a scorecard")
        self.rejects([1, 2, 3])
        self.rejects(42)

    def test_wrong_version_is_rejected(self) -> None:
        self.rejects({"version": SAVE_VERSION + 99, "game": {"version": 1, "rounds": []}})

    def test_missing_game_is_rejected(self) -> None:
        self.rejects({"version": SAVE_VERSION})

    def test_rounds_of_the_wrong_shape_are_rejected(self) -> None:
        self.rejects({
            "version": SAVE_VERSION,
            "game": {"version": SAVE_VERSION, "rounds": [{"phase": 1}]},
        })

    def test_an_unknown_hand_state_is_rejected(self) -> None:
        self.rejects({
            "version": SAVE_VERSION,
            "game": {"version": SAVE_VERSION, "rounds": [{
                "number": 1, "phase": 1, "state": "teleported", "score": 0,
                "draws_used": 0, "wilds_used": 0, "skips_played": 0,
            }]},
        })

    def test_an_out_of_range_locked_phase_is_dropped(self) -> None:
        s = session()
        payload = {
            "version": SAVE_VERSION,
            "game": {"version": SAVE_VERSION, "rounds": []},
            "locked_phase": 99,
        }
        self.assertTrue(s.load_payload(payload))
        self.assertIsNone(s.locked_phase)

    def test_junk_traps_do_not_crash(self) -> None:
        s = session()
        payload = {
            "version": SAVE_VERSION,
            "game": {"version": SAVE_VERSION, "rounds": []},
            "consumed_traps": {"Phase Lock": "lots"},
        }
        self.assertTrue(s.load_payload(payload))
        self.assertEqual(s.pending(PHASE_LOCK), 0)


class TestPayloadShape(unittest.TestCase):
    def test_checked_locations_are_not_stored(self) -> None:
        # The server is the authority on checks; a second copy could disagree.
        s = session()
        play(s, 1, HandState.PHASE_LAID)
        self.assertTrue(s.checked_locations)
        self.assertNotIn("checked_locations", s.to_payload())

    def test_payload_is_json_safe(self) -> None:
        import json

        s = session()
        play(s, 3, HandState.PHASE_LAID)
        restored = json.loads(json.dumps(s.to_payload()))
        fresh = session()
        self.assertTrue(fresh.load_payload(restored))
        self.assertEqual(fresh.total_score, s.total_score)
