"""Access rules match the measured difficulty, not the printed phase order."""

from BaseClasses import Item

from .bases import Phase10TestBase


class TestGating(Phase10TestBase):
    options = {"starting_phases": 1, "checks_per_phase": 4}

    def collect_exactly(self, name: str, count: int) -> list[Item]:
        """Collect a precise number of copies.

        collect_by_name() pulls *every* matching item out of the pool, which
        silently turns a threshold test into a no-op -- so slice instead.
        """
        items = self.get_items_by_name(name)[:count]
        self.assertEqual(len(items), count, f"pool holds fewer than {count} {name}")
        self.collect(items)
        return items

    def test_unlock_alone_seats_you_at_a_hard_phase(self) -> None:
        # Unlocking is enough to reach the region; clearing is what costs.
        self.collect_by_name("Phase 7 Unlocked")
        self.assertTrue(self.can_reach_region("Phase 7"))

    def test_hard_phase_cannot_be_cleared_on_the_unlock_alone(self) -> None:
        self.collect_by_name("Phase 7 Unlocked")
        self.assertFalse(self.can_reach_location("Phase 7 - Cleared"))

    def test_hard_phase_needs_four_wilds_exactly(self) -> None:
        self.collect_by_name("Phase 7 Unlocked")
        wilds = self.get_items_by_name("Wild Card")
        self.collect(wilds[:3])
        self.assertFalse(self.can_reach_location("Phase 7 - Cleared"))
        self.collect(wilds[3])
        self.assertTrue(self.can_reach_location("Phase 7 - Cleared"))

    def test_easy_phase_clears_on_the_unlock_alone(self) -> None:
        self.collect_by_name("Phase 2 Unlocked")
        self.assertTrue(self.can_reach_location("Phase 2 - Cleared"))

    def test_no_wilds_tier_needs_five_draws_exactly(self) -> None:
        self.collect_by_name("Phase 2 Unlocked")
        draws = self.get_items_by_name("Extra Draw")
        self.collect(draws[:4])
        self.assertFalse(self.can_reach_location("Phase 2 - No Wilds"))
        self.collect(draws[4])
        self.assertTrue(self.can_reach_location("Phase 2 - No Wilds"))

    def test_went_out_tier_is_cheaper_than_no_wilds(self) -> None:
        self.collect_by_name("Phase 2 Unlocked")
        self.collect(self.get_items_by_name("Extra Draw")[:3])
        self.assertTrue(self.can_reach_location("Phase 2 - Went Out"))
        self.assertFalse(self.can_reach_location("Phase 2 - No Wilds"))
