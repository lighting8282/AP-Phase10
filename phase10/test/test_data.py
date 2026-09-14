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
