"""The seed must open with something playable.

An early version gated every location behind a phase unlock, which left sphere
zero empty and made fill impossible. The milestone checks and the precollected
starting phases are what fix that, so both are pinned.
"""

from .bases import Phase10TestBase

from ..rules import EASY_PHASES


class TestOpening(Phase10TestBase):
    options = {"starting_phases": 2}

    def test_milestones_need_no_items(self) -> None:
        self.assertTrue(self.can_reach_location("Hands Won: 1"))
        self.assertTrue(self.can_reach_location("Hands Won: 30"))

    def test_starting_phases_are_precollected(self) -> None:
        precollected = [
            item.name
            for item in self.multiworld.precollected_items[self.player]
            if item.name.endswith("Unlocked")
        ]
        self.assertEqual(len(precollected), 2)

    def test_starting_phases_are_easy_ones(self) -> None:
        # A hard phase as your only starter is unclearable until wilds arrive.
        for item in self.multiworld.precollected_items[self.player]:
            if item.name.endswith("Unlocked"):
                phase = int(item.name.split()[1])
                self.assertIn(phase, EASY_PHASES)

    def test_a_started_phase_is_immediately_clearable(self) -> None:
        reachable = [
            phase
            for phase in EASY_PHASES
            if self.can_reach_location(f"Phase {phase} - Cleared")
        ]
        self.assertTrue(reachable, "no phase is clearable at game start")
