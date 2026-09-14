from __future__ import annotations

from typing import TYPE_CHECKING

from BaseClasses import Location

from . import items
from .data import (
    GAME_NAME,
    HANDS_WON_MILESTONES, LOCATION_NAME_TO_ID, TIERS,
    milestone_location_name, phase_location_name,
)

if TYPE_CHECKING:
    from .world import Phase10World

class Phase10Location(Location):
    game = GAME_NAME


def create_all_locations(world: Phase10World) -> None:
    tiers = TIERS[: int(world.options.checks_per_phase)]

    table = world.get_region("Table")
    milestone_names = [milestone_location_name(n) for n in HANDS_WON_MILESTONES]
    table.add_locations(
        {name: LOCATION_NAME_TO_ID[name] for name in milestone_names}, Phase10Location
    )

    for phase in range(1, 11):
        region = world.get_region(f"Phase {phase}")
        names = [phase_location_name(phase, tier) for tier in tiers]
        region.add_locations(
            {name: LOCATION_NAME_TO_ID[name] for name in names}, Phase10Location
        )
        # Clearing a phase is an event so the goal can depend on it without
        # caring where the "Cleared" check's item happened to land.
        region.add_event(
            f"Phase {phase} Cleared",
            f"Phase {phase} Clear",
            location_type=Phase10Location,
            item_type=items.Phase10Item,
        )

    world.get_region("Victory").add_event(
        "Goal", "Victory", location_type=Phase10Location, item_type=items.Phase10Item
    )
