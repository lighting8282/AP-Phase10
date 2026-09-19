"""Guards on the shared ID tables.

A duplicate location address is only caught when a real seed is generated --
the world builds and fills perfectly happily with two names on one ID, and the
assertion does not fire until the datapackage is written. Phase 10's checks run
to 203 and the milestones originally started at 200, so this happened.
"""

import unittest

from ..data import ITEM_NAME_TO_ID, LOCATION_NAME_TO_ID


class TestIdTables(unittest.TestCase):
    def test_location_ids_are_unique(self) -> None:
        ids = list(LOCATION_NAME_TO_ID.values())
        self.assertEqual(len(ids), len(set(ids)), "duplicate location address")

    def test_item_ids_are_unique(self) -> None:
        ids = list(ITEM_NAME_TO_ID.values())
        self.assertEqual(len(ids), len(set(ids)), "duplicate item code")

    def test_phase_and_milestone_ranges_do_not_overlap(self) -> None:
        phase_ids = {v for k, v in LOCATION_NAME_TO_ID.items() if k.startswith("Phase ")}
        milestone_ids = {v for k, v in LOCATION_NAME_TO_ID.items() if k.startswith("Hands Won")}
        self.assertFalse(phase_ids & milestone_ids)
        self.assertGreater(min(milestone_ids), max(phase_ids))

    def test_world_tables_match_the_shared_ones(self) -> None:
        from ..world import Phase10World

        self.assertEqual(Phase10World.location_name_to_id, LOCATION_NAME_TO_ID)
        self.assertEqual(Phase10World.item_name_to_id, ITEM_NAME_TO_ID)


class TestIdSpaceSurvivesMorePhases(unittest.TestCase):
    """The unlock block and the fixed block must not meet.

    Phase unlocks take 1..PHASE_COUNT. Adding phases 11-20 walked "Phase 20
    Unlocked" straight onto "Wild Card" at ID 20 -- caught only because
    test_item_ids_are_unique existed. This pins the invariant rather than the
    symptom, so the next ten phases fail loudly and early.
    """

    def test_unlocks_stay_below_the_fixed_block(self) -> None:
        from ..data import FIRST_FIXED_ITEM_ID, PHASE_COUNT

        self.assertLess(PHASE_COUNT, FIRST_FIXED_ITEM_ID)

    def test_phase_checks_stay_below_the_milestones(self) -> None:
        """Phase 20's checks reach 303; milestones used to start at 300."""
        from ..data import (HANDS_WON_MILESTONES, PHASE_COUNT, TIERS,
                            LOCATION_NAME_TO_ID, milestone_location_name,
                            phase_location_name)

        highest_phase = max(
            LOCATION_NAME_TO_ID[phase_location_name(PHASE_COUNT, tier)]
            for tier in TIERS
        )
        lowest_milestone = min(
            LOCATION_NAME_TO_ID[milestone_location_name(n)]
            for n in HANDS_WON_MILESTONES
        )
        self.assertLess(highest_phase, lowest_milestone)

    def test_every_phase_has_an_unlock_and_a_spec(self) -> None:
        from ..data import ITEM_NAME_TO_ID, PHASE_COUNT, PHASE_UNLOCK
        from ..game.phases import PHASES

        self.assertEqual(len(PHASES), PHASE_COUNT)
        for phase in range(1, PHASE_COUNT + 1):
            self.assertIn(PHASE_UNLOCK.format(phase), ITEM_NAME_TO_ID)
            self.assertIn(phase, PHASES)

    def test_no_phase_asks_for_more_cards_than_a_hand_holds(self) -> None:
        """A phase needing more than hand size is unclearable at any budget --
        three sets of four wants twelve cards and measured a flat 0%."""
        from ..data import PHASE_COUNT
        from ..game.phases import MAX_PHASE_CARDS, PHASES, phase_card_count

        for phase in range(1, PHASE_COUNT + 1):
            self.assertLessEqual(
                phase_card_count(PHASES[phase]), MAX_PHASE_CARDS,
                f"Phase {phase} asks for more cards than a hand can hold")
