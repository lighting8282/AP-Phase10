"""Which phase the computer players play reaches the clients."""

from .bases import Phase10TestBase


class TestOpponentPhaseDefault(Phase10TestBase):
    options = {}

    def test_seeds_match_by_default(self) -> None:
        self.assertEqual(self.world.fill_slot_data()["opponent_phase"], "match")


class TestOpponentPhaseOwn(Phase10TestBase):
    options = {"opponent_phase": "own"}

    def test_own_is_sent_when_chosen(self) -> None:
        self.assertEqual(self.world.fill_slot_data()["opponent_phase"], "own")
