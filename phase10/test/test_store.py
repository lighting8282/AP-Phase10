"""The points store: the one place a check is bought rather than played for.

Two halves are tested here. The world half is that a store of N slots exists,
is priced, and does not break the pool it is added to -- the inherited
test_fill and test_all_state_can_reach_everything from Phase10TestBase do the
real work under these options. The data half is the price ladder itself, whose
one job is to make every purchase order legal.
"""

from collections import Counter

from BaseClasses import ItemClassification

from ..data import (
    AP_POINT, DEFAULT_BUFF_POINTS, MAX_STORE_SLOTS, STORE_ALL_AT_ONCE,
    STORE_LADDER, STORE_PRICES, STORE_SLACK, store_gate,
    store_location_name, store_points, store_prices,
)
from ..items import plan_store
from .bases import Phase10TestBase


class TestStoreLadder(Phase10TestBase):
    """The ladder, with no world involved."""

    options = {"store_slots": 6}

    def test_prices_never_fall(self) -> None:
        """The gate on a slot is the sum of the cheapest prices up to it, which
        only equals "the first i prices" while the list ascends. A descending
        price would let a player reach slot i's gate while holding less than
        the i cheapest slots cost, and the purchase order would stop being
        free."""
        self.assertEqual(STORE_PRICES, sorted(STORE_PRICES))

    def test_a_gate_is_the_sum_of_the_cheapest_prices(self) -> None:
        for slot in range(1, MAX_STORE_SLOTS + 1):
            self.assertEqual(store_gate(slot), sum(sorted(STORE_PRICES)[:slot]))

    def test_every_order_is_affordable(self) -> None:
        """The property the ladder exists for: hold the last slot's gate worth
        of points and you can buy every slot, in any order."""
        for slots in range(1, MAX_STORE_SLOTS + 1):
            self.assertGreaterEqual(store_points(slots), sum(store_prices(slots)))

    def test_slack_is_on_top_of_the_ladder(self) -> None:
        self.assertEqual(store_points(6), sum(store_prices(6)) + STORE_SLACK)
        self.assertEqual(store_points(0), 0)


class TestStorePlan(Phase10TestBase):
    """Trimming the store to what the location budget can carry."""

    options = {"store_slots": 6}

    def test_a_roomy_seed_keeps_every_slot(self) -> None:
        self.assertEqual(plan_store(50, 6, 29), (6, store_points(6)))

    def test_a_tight_seed_drops_the_slack_before_a_slot(self) -> None:
        """Slack is comfort; a slot is a check. At thirty locations against a
        floor of twenty-nine the store survives only by giving up the slack."""
        slots, points = plan_store(30, 6, 29)
        self.assertEqual((slots, points), (5, sum(store_prices(5))))

    def test_a_store_that_cannot_fit_at_all_is_dropped(self) -> None:
        """Only reachable when the seed is already under its own floor, which
        errors elsewhere -- but the store must not be what tips it over."""
        self.assertEqual(plan_store(20, 6, 29), (0, 0))

    def test_asking_for_none_gets_none(self) -> None:
        self.assertEqual(plan_store(90, 0, 29), (0, 0))


class TestStoreWorld(Phase10TestBase):
    """A store in a real world, at the defaults it ships with."""

    options = {"checks_per_phase": 2, "store_slots": 6}

    def test_the_slots_exist(self) -> None:
        for slot in range(1, 7):
            self.assertIsNotNone(
                self.multiworld.get_location(store_location_name(slot), self.player)
            )

    def test_the_pool_carries_the_points(self) -> None:
        # With the card budget. This compared against store_points(6) alone
        # from the day the budget was added until it was next read -- 10
        # expected, 18 in the pool -- because this file needs an Archipelago
        # checkout and nothing that could run it did.
        pool = Counter(item.name for item in self.multiworld.itempool)
        self.assertEqual(pool[AP_POINT], store_points(6, DEFAULT_BUFF_POINTS))

    def test_points_are_progression(self) -> None:
        """Filler would let fill drop them anywhere, including behind the very
        slots they pay for."""
        point = self.world.create_item(AP_POINT)
        self.assertEqual(point.classification, ItemClassification.progression)

    def test_a_slot_costs_exactly_its_gate(self) -> None:
        """One point short is short. The gate on slot 6 is the sum of the
        cheapest six prices, which is what makes any purchase order legal."""
        self.assertFalse(self.can_reach_location(store_location_name(6)))
        points = self.get_items_by_name(AP_POINT)
        gate = store_gate(6)
        self.collect(points[: gate - 1])
        self.assertFalse(self.can_reach_location(store_location_name(6)))
        self.collect(points[gate - 1])
        self.assertTrue(self.can_reach_location(store_location_name(6)))

    def test_the_first_slot_is_cheap(self) -> None:
        """A store you cannot touch until late is not a store. The first slot
        costs one point, so it opens as soon as a single one turns up."""
        self.assertEqual(store_gate(1), 1)
        self.collect(self.get_items_by_name(AP_POINT)[:1])
        self.assertTrue(self.can_reach_location(store_location_name(1)))

    def test_the_store_pays_for_itself_in_locations(self) -> None:
        """A store of N slots brings N locations, so it only costs the pool the
        points beyond one per slot -- which is what makes it affordable at all.
        """
        self.assertEqual(
            len(self.multiworld.get_unfilled_locations(self.player)),
            len(self.multiworld.itempool),
        )


class TestNoStore(Phase10TestBase):
    """store_slots: 0 has to leave no trace, since that is what every seed
    generated before the store existed looks like."""

    options = {"checks_per_phase": 2, "store_slots": 0}

    def test_no_slots_and_no_points(self) -> None:
        pool = Counter(item.name for item in self.multiworld.itempool)
        self.assertEqual(pool[AP_POINT], 0)
        names = {location.name for location in self.multiworld.get_locations(self.player)}
        self.assertFalse({n for n in names if n.startswith("Store Slot")})


class TestStoreInATightSeed(Phase10TestBase):
    """One check a phase: thirty locations against a floor of twenty-nine
    required items. The store has to trim itself rather than fail."""

    options = {"checks_per_phase": 1, "store_slots": MAX_STORE_SLOTS}

    def test_the_store_was_trimmed(self) -> None:
        self.assertLess(int(self.world.options.store_slots), MAX_STORE_SLOTS)
        self.assertGreater(int(self.world.options.store_slots), 0)

    def test_the_pool_still_fits(self) -> None:
        self.assertEqual(
            len(self.multiworld.get_unfilled_locations(self.player)),
            len(self.multiworld.itempool),
        )


class TestStoreAllAtOnce(Phase10TestBase):
    """`store_gating: all_at_once` in a real world: every slot one point, and
    one gate for all of them at the store's total."""

    options = {"checks_per_phase": 2, "store_slots": 6, "store_gating": "all_at_once"}

    def test_nothing_opens_one_point_short(self) -> None:
        points = self.get_items_by_name(AP_POINT)
        self.collect(points[:5])
        for slot in range(1, 7):
            self.assertFalse(self.can_reach_location(store_location_name(slot)), slot)

    def test_everything_opens_together(self) -> None:
        points = self.get_items_by_name(AP_POINT)
        self.collect(points[:6])
        for slot in range(1, 7):
            self.assertTrue(self.can_reach_location(store_location_name(slot)), slot)

    def test_the_pool_carries_the_flat_store(self) -> None:
        pool = Counter(item.name for item in self.multiworld.itempool)
        self.assertEqual(pool[AP_POINT],
                         store_points(6, DEFAULT_BUFF_POINTS, STORE_ALL_AT_ONCE))

    def test_the_clients_are_told_the_shape(self) -> None:
        self.assertEqual(self.world.fill_slot_data()["store_gating"], STORE_ALL_AT_ONCE)

    def test_the_pool_still_fits(self) -> None:
        self.assertEqual(
            len(self.multiworld.get_unfilled_locations(self.player)),
            len(self.multiworld.itempool),
        )


class TestStoreAllAtOnceInATightSeed(Phase10TestBase):
    """Where the ladder trims to five slots, a store of ones pays for itself
    exactly -- one point, one location -- so the whole store fits."""

    options = {"checks_per_phase": 1, "store_slots": MAX_STORE_SLOTS,
               "store_gating": "all_at_once"}

    def test_the_whole_store_fits(self) -> None:
        self.assertEqual(int(self.world.options.store_slots), MAX_STORE_SLOTS)

    def test_the_pool_still_fits(self) -> None:
        self.assertEqual(
            len(self.multiworld.get_unfilled_locations(self.player)),
            len(self.multiworld.itempool),
        )


class TestStoreLadderIsTheDefault(Phase10TestBase):
    options = {"checks_per_phase": 2, "store_slots": 6}

    def test_slot_data_says_ladder(self) -> None:
        self.assertEqual(self.world.fill_slot_data()["store_gating"], STORE_LADDER)
