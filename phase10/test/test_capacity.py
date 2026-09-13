"""Option combinations that squeeze the location pool.

The pool has to stay large enough to absorb every progression item, and the
seed has to open with something reachable. Both of those broke during initial
development, so the tightest and loosest settings are pinned here. The inherited
default tests (test_fill, test_empty_state_can_reach_something) do the real
work; these classes exist to run them under the extreme options.
"""

from .bases import Phase10TestBase


class TestMinimumCapacity(Phase10TestBase):
    """Fewest locations and fewest items logic will tolerate."""

    options = {
        "checks_per_phase": 2,
        "starting_phases": 1,
        "extra_draw_items": 5,
        "wild_card_items": 4,
        "hand_size_upgrades": 0,
        "trap_chance": 0,
    }

    def test_pool_fits_locations(self) -> None:
        locations = len(self.multiworld.get_unfilled_locations(self.player))
        self.assertEqual(len(self.multiworld.itempool), locations)


class TestMaximumItems(Phase10TestBase):
    """Most power items requested against the smallest location pool.

    The surplus must be trimmed rather than overflowing the pool.
    """

    options = {
        "checks_per_phase": 2,
        "starting_phases": 1,
        "extra_draw_items": 16,
        "wild_card_items": 8,
        "hand_size_upgrades": 2,
    }

    def test_pool_fits_locations(self) -> None:
        locations = len(self.multiworld.get_unfilled_locations(self.player))
        self.assertEqual(len(self.multiworld.itempool), locations)

    def test_logic_floors_survive_trimming(self) -> None:
        from ..rules import MIN_EXTRA_DRAWS, MIN_WILD_CARDS

        self.assertGreaterEqual(len(self.get_items_by_name("Wild Card")), MIN_WILD_CARDS)
        self.assertGreaterEqual(len(self.get_items_by_name("Extra Draw")), MIN_EXTRA_DRAWS)


class TestFullSize(Phase10TestBase):
    options = {"checks_per_phase": 4, "starting_phases": 4}
