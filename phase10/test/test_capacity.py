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
        "extra_draw_items": 8,
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


class TestOptionRangesMatchLogic(Phase10TestBase):
    """The option ranges have to be able to satisfy the rules.

    Found by probing: at extra_draw_items 3 or 4 the No Wilds check on every
    phase is unreachable, because it asks for Extra Draw x5 and the pool
    cannot hold five. Generation fails outright. The range start is the fix,
    so it has to stay tied to the floor rather than drift from it.
    """

    options = {"checks_per_phase": 4}

    def test_extra_draw_range_cannot_starve_its_own_logic(self) -> None:
        from ..options import ExtraDrawItems
        from ..rules import MIN_EXTRA_DRAWS

        self.assertGreaterEqual(ExtraDrawItems.range_start, MIN_EXTRA_DRAWS)

    def test_wild_card_range_cannot_starve_its_own_logic(self) -> None:
        from ..options import WildCardItems
        from ..rules import MIN_WILD_CARDS

        self.assertGreaterEqual(WildCardItems.range_start, MIN_WILD_CARDS)

    def test_every_preset_is_inside_its_option_range(self) -> None:
        from ..options import option_presets, Phase10Options

        for name, preset in option_presets.items():
            for key, value in preset.items():
                option = Phase10Options.type_hints[key]
                if hasattr(option, "range_start"):
                    self.assertGreaterEqual(
                        value, option.range_start, f"{name}.{key}")
                    self.assertLessEqual(
                        value, option.range_end, f"{name}.{key}")


class TestPoolStaysMeaningful(Phase10TestBase):
    """Doubling the phases doubled the locations, not the useful items.

    Every power item is capped by something real -- the deck holds eight
    wilds, extra draws stop buying anything past the range, skips and hand
    size have their own limits -- so a bigger location pool can only absorb
    the difference as filler. At four checks a phase it measured 59% filler
    and thirty-five Mulligans, which is an infinite supply of redeals. Two
    checks a phase is the default for that reason.
    """

    options = {"checks_per_phase": 2}

    def test_filler_does_not_dominate_the_default_pool(self) -> None:
        pool = [item.name for item in self.multiworld.itempool]
        filler = sum(1 for n in pool if n in ("Mulligan", "Score Reduction"))
        self.assertLess(filler / len(pool), 0.40, "filler has taken over the pool")

    def test_no_single_filler_is_an_infinite_supply(self) -> None:
        from collections import Counter

        counts = Counter(item.name for item in self.multiworld.itempool)
        self.assertLessEqual(counts["Mulligan"], 15)
