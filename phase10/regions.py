from __future__ import annotations

from typing import TYPE_CHECKING

from BaseClasses import Region

from .data import PHASE_COUNT

if TYPE_CHECKING:
    from .world import Phase10World


def create_and_connect_regions(world: Phase10World) -> None:
    menu = Region("Menu", world.player, world.multiworld)
    phases = [Region(f"Phase {p}", world.player, world.multiworld)
              for p in range(1, PHASE_COUNT + 1)]
    table = Region("Table", world.player, world.multiworld)
    victory = Region("Victory", world.player, world.multiworld)
    world.multiworld.regions += [menu, table, *phases, victory]

    # Phases are unlocked individually and out of order, so every one hangs
    # directly off Menu rather than chaining 1 -> 2 -> 3.
    # The Table needs nothing: you can always sit down and grind hands with
    # whatever phase you started with. These are the seed's opening checks.
    menu.connect(table, "Menu to Table")

    for phase, region in zip(range(1, PHASE_COUNT + 1), phases):
        menu.connect(region, f"Menu to Phase {phase}")
    menu.connect(victory, "Menu to Victory")
