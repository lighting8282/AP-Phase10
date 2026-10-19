"""Universal Tracker can rebuild this world from slot data alone.

The tracker regenerates the world with no YAML, passing the seed's slot data
back through `interpret_slot_data`, and reads what is in logic off the result.
So a regeneration has to land on the same options, the same starting phases
and the same locations as the real seed, or the tracker shows the wrong things
as reachable.
"""

from argparse import Namespace

from BaseClasses import CollectionState, MultiWorld
from worlds.AutoWorld import call_all

from ..data import GAME_NAME
from ..world import Phase10World
from .bases import Phase10TestBase

STEPS = ("generate_early", "create_regions", "create_items", "set_rules")


def regenerate(slot_data: dict, seed: int) -> MultiWorld:
    """What the tracker does: default options, slot data passed through."""
    multiworld = MultiWorld(1)
    multiworld.game = {1: GAME_NAME}
    multiworld.player_name = {1: "Tracker"}
    multiworld.set_seed(seed)
    args = Namespace(**{name: {1: option.from_any(option.default)}
                        for name, option in Phase10World.options_dataclass.type_hints.items()})
    multiworld.set_options(args)
    multiworld.state = CollectionState(multiworld)
    multiworld.re_gen_passthrough = {GAME_NAME: Phase10World.interpret_slot_data(slot_data)}
    for step in STEPS:
        call_all(multiworld, step)
    return multiworld


class TrackerCase(Phase10TestBase):
    def check_matches(self) -> None:
        slot_data = dict(self.world.fill_slot_data())
        # A different seed on purpose: nothing the tracker needs may come
        # from rolling the same dice.
        tracked = regenerate(slot_data, seed=self.multiworld.seed + 1)
        world = tracked.worlds[1]
        for name in ("goal", "phases_to_win", "checks_per_phase", "store_slots",
                     "store_gating", "hands_won_logic", "starting_phases"):
            self.assertEqual(int(getattr(world.options, name)),
                             int(getattr(self.world.options, name)), name)

        def starters(mw: MultiWorld) -> list[str]:
            return sorted(i.name for i in mw.precollected_items[1] if i.name.endswith("Unlocked"))

        self.assertEqual(starters(tracked), starters(self.multiworld))

        def names(mw: MultiWorld) -> set[str]:
            return {loc.name for loc in mw.get_locations(1) if loc.address is not None}

        self.assertEqual(names(tracked), names(self.multiworld))

        # Same rules: what the starting state reaches agrees, location by location.
        def reachable(mw: MultiWorld) -> set[str]:
            state = CollectionState(mw)
            state.sweep_for_advancements()
            return {loc.name for loc in mw.get_locations(1)
                    if loc.address is not None and loc.can_reach(state)}

        self.assertEqual(reachable(tracked), reachable(self.multiworld))


class TestDefaults(TrackerCase):
    def test_regenerates_the_same_world(self) -> None:
        self.check_matches()


class TestNonDefaults(TrackerCase):
    options = {"checks_per_phase": 3, "starting_phases": 4, "store_slots": 4,
               "store_gating": "always_open", "goal": "phase_ten",
               "hands_won_logic": "replays", "phases_to_win": 12}

    def test_regenerates_the_same_world(self) -> None:
        self.check_matches()


class TestAdjustedOptions(TrackerCase):
    """Options fit_hands_won_logic changed: the tracker must see the result."""
    options = {"checks_per_phase": 1, "starting_phases": 1, "store_slots": 8}

    def test_regenerates_the_same_world(self) -> None:
        self.check_matches()
