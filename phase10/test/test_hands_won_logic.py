"""The Hands Won checks never make you replay rounds to move on.

A won round is a cleared one, so clearing N different phases is N wins without
replaying anything. Under new_phases that is what Hands Won: N asks for, and
the milestones no forward play reaches hold nothing required. Without it, fill
put a phase unlock on Hands Won: 12 with nine phases open, and the run could go
on only by winning the same rounds again.
"""

from ..data import HANDS_WON_MILESTONES, PHASE_COUNT, milestone_location_name
from ..items import EARLY_PHASES
from ..options import HandsWonLogic
from ..rules import EASY_PHASES
from .bases import Phase10TestBase


def unlocked(test: Phase10TestBase) -> set[int]:
    return {int(item.name.split()[1])
            for item in test.multiworld.precollected_items[test.player]
            if item.name.endswith("Unlocked")}


class TestNewPhases(Phase10TestBase):
    options = {"starting_phases": 2}

    def setUp(self) -> None:
        super().setUp()
        # Clearing is an event, and the test state starts unswept: without
        # this the starting phases' free clears are not counted, where fill's
        # own state always counts them.
        self.multiworld.state.sweep_for_advancements()

    def test_is_the_default(self) -> None:
        self.assertEqual(int(self.world.options.hands_won_logic),
                         HandsWonLogic.option_new_phases)

    def test_each_new_easy_phase_opens_one_more_milestone(self) -> None:
        # Easy phases clear on the unlock alone, so each one is one more win.
        open_phases = len(unlocked(self))
        self.assertTrue(self.can_reach_location("Hands Won: 2"))
        self.assertFalse(self.can_reach_location("Hands Won: 3"))
        for phase in sorted(EASY_PHASES - unlocked(self)):
            self.collect_by_name(f"Phase {phase} Unlocked")
            open_phases += 1
            for hands in HANDS_WON_MILESTONES:
                self.assertEqual(self.can_reach_location(milestone_location_name(hands)),
                                 hands <= open_phases, f"{hands} with {open_phases} cleared")

    def test_an_unclearable_phase_is_not_a_win(self) -> None:
        # Phase 7 is hard: unlocked, but not clearable without four wilds.
        before = [self.can_reach_location(milestone_location_name(n))
                  for n in HANDS_WON_MILESTONES]
        self.collect_by_name("Phase 7 Unlocked")
        after = [self.can_reach_location(milestone_location_name(n))
                 for n in HANDS_WON_MILESTONES]
        self.assertEqual(before, after)

    def test_milestones_past_every_phase_hold_nothing_required(self) -> None:
        unlock = self.world.create_item("Phase 3 Unlocked")
        for hands in HANDS_WON_MILESTONES:
            location = self.multiworld.get_location(milestone_location_name(hands), self.player)
            self.assertEqual(location.item_rule(unlock), hands <= PHASE_COUNT, hands)
            if location.item:
                self.assertTrue(hands <= PHASE_COUNT or not location.item.advancement,
                                f"{location.item.name} on {location.name}")

    def test_easy_phases_are_placed_early(self) -> None:
        early = self.multiworld.local_early_items[self.player]
        self.assertEqual(sum(early.values()), EARLY_PHASES)
        for name in early:
            phase = int(name.split()[1])
            self.assertIn(phase, EASY_PHASES)
            self.assertNotIn(phase, unlocked(self))


class TestReplays(Phase10TestBase):
    options = {"hands_won_logic": "replays", "starting_phases": 1}

    def test_every_milestone_is_open_from_the_start(self) -> None:
        for hands in HANDS_WON_MILESTONES:
            self.assertTrue(self.can_reach_location(milestone_location_name(hands)), hands)

    def test_nothing_is_placed_early_and_one_phase_stays_one(self) -> None:
        self.assertFalse(self.multiworld.local_early_items[self.player])
        self.assertEqual(len(unlocked(self)), 1)


class TestOneStartingPhase(Phase10TestBase):
    """Fill strands itself in a two-check opening, so new_phases opens with two."""
    options = {"starting_phases": 1}

    def test_raised_to_two(self) -> None:
        self.assertEqual(int(self.world.options.starting_phases), 2)
        self.assertEqual(len(unlocked(self)), 2)


class TestOneCheckPerPhase(Phase10TestBase):
    """At one check a phase new_phases cannot fill, so it falls back."""
    options = {"checks_per_phase": 1}

    def test_falls_back_to_replays(self) -> None:
        self.assertEqual(int(self.world.options.hands_won_logic),
                         HandsWonLogic.option_replays)
        self.assertTrue(self.can_reach_location("Hands Won: 30"))


class TestBigLadder(Phase10TestBase):
    """The ladder's long chain strands fill past six slots under new_phases."""
    options = {"store_slots": 8}

    def test_capped_at_six(self) -> None:
        from ..world import NEW_PHASES_LADDER_SLOTS
        self.assertEqual(int(self.world.options.store_slots), NEW_PHASES_LADDER_SLOTS)


class TestBigOpenStore(Phase10TestBase):
    """Always open asks three points a slot, not a chain, and keeps all eight."""
    options = {"store_slots": 8, "store_gating": "always_open"}

    def test_keeps_eight(self) -> None:
        self.assertEqual(int(self.world.options.store_slots), 8)
