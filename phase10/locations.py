from __future__ import annotations

from typing import TYPE_CHECKING

from BaseClasses import Location

from . import items

if TYPE_CHECKING:
    from .world import Phase10World

#: Check tiers in unlock order; `checks_per_phase` takes a prefix of this list.
TIERS = ["Cleared", "Went Out", "No Wilds", "Under Par"]

#: Cumulative "just keep playing" checks. They gate on nothing, which is what
#: gives the seed a workable opening -- without them the only sphere-0 spots are
#: the handful of easy phases you happen to start with, and fill has nowhere to
#: seed the first Wild Cards and Extra Draws.
HANDS_WON_MILESTONES = [1, 2, 3, 5, 8, 12, 16, 20, 25, 30]

LOCATION_NAME_TO_ID = {
    **{
        f"Phase {phase} - {tier}": 100 + phase * 10 + index
        for phase in range(1, 11)
        for index, tier in enumerate(TIERS)
    },
    **{
        f"Hands Won: {n}": 200 + index
        for index, n in enumerate(HANDS_WON_MILESTONES)
    },
}


class Phase10Location(Location):
    game = "Phase 10"


def create_all_locations(world: Phase10World) -> None:
    tiers = TIERS[: int(world.options.checks_per_phase)]

    table = world.get_region("Table")
    milestone_names = [f"Hands Won: {n}" for n in HANDS_WON_MILESTONES]
    table.add_locations(
        {name: LOCATION_NAME_TO_ID[name] for name in milestone_names}, Phase10Location
    )

    for phase in range(1, 11):
        region = world.get_region(f"Phase {phase}")
        names = [f"Phase {phase} - {tier}" for tier in tiers]
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
