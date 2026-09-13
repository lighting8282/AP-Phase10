from collections.abc import Mapping
from typing import Any

from worlds.AutoWorld import World

from . import items, locations, regions, rules, web_world
from . import options as phase10_options


class Phase10World(World):
    """
    Phase 10 is a rummy-style card game of ten escalating objectives. This
    implementation is solo: instead of racing opponents to go out, you have a
    limited draw budget to lay each phase down. Archipelago decides which
    phases you may attempt, and how many wild cards and draws you get.
    """

    game = "Phase 10"
    web = web_world.Phase10WebWorld()

    options_dataclass = phase10_options.Phase10Options
    options: phase10_options.Phase10Options

    location_name_to_id = locations.LOCATION_NAME_TO_ID
    item_name_to_id = items.ITEM_NAME_TO_ID

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
            "goal", "starting_draws", "checks_per_phase", "include_skips",
        )
