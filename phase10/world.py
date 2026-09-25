from collections.abc import Mapping
from typing import Any

from worlds.AutoWorld import World

from . import items, locations, regions, rules, web_world
from . import options as phase10_options
from .data import GAME_NAME, HANDS_WON_MILESTONES, PHASE_COUNT


class Phase10World(World):
    """
    Phase 10 is a rummy-style card game of ten escalating objectives. This
    implementation seats you against computer players who race you to go out,
    and gives you a draw budget on top -- a round ends on whichever comes
    first. Archipelago decides which phases you may attempt, and how many wild
    cards, draws and skips you get. Set opponents to 0 for the solo game.
    """

    game = GAME_NAME
    web = web_world.Phase10WebWorld()

    options_dataclass = phase10_options.Phase10Options
    options: phase10_options.Phase10Options

    location_name_to_id = locations.LOCATION_NAME_TO_ID
    item_name_to_id = items.ITEM_NAME_TO_ID

    #: Decided in generate_early, because the store's locations are built
    #: before the item pool is and both have to agree on its size.
    store_points: int = 0

    def generate_early(self) -> None:
        """Trim the store to what the location budget can carry.

        The slot count is an option, but at one check a phase there are thirty
        locations against a floor of twenty-nine required items, so a six-slot
        store asks for points there is nowhere to put. Trimming here rather
        than raising an error keeps a legal option combination generating.
        """
        from .rules import MIN_EXTRA_DRAWS, MIN_WILD_CARDS

        base = PHASE_COUNT * int(self.options.checks_per_phase) + len(HANDS_WON_MILESTONES)
        floor = PHASE_COUNT + MIN_WILD_CARDS + MIN_EXTRA_DRAWS
        slots, points = items.plan_store(base, int(self.options.store_slots), floor)
        self.options.store_slots.value = slots
        self.store_points = points

    def create_regions(self) -> None:
        regions.create_and_connect_regions(self)
        locations.create_all_locations(self)

    def set_rules(self) -> None:
        rules.set_all_rules(self)

    def create_items(self) -> None:
        items.create_all_items(self)

    def create_item(self, name: str) -> items.Phase10Item:
        return items.create_item_with_correct_classification(self, name)

    def get_filler_item_name(self) -> str:
        return items.get_random_filler_item_name(self)

    def fill_slot_data(self) -> Mapping[str, Any]:
        # The client builds its GameConfig from these; the engine's knobs map
        # one-to-one onto the option names.
        return self.options.as_dict(
            "goal", "starting_draws", "checks_per_phase", "death_link",
            "opponents", "store_slots",
        )
