from __future__ import annotations

from typing import TYPE_CHECKING

from BaseClasses import Item, ItemClassification

from .data import (
    FILLERS, GAME_NAME, ITEM_NAME_TO_ID, MULLIGAN, PHASE_COUNT, PHASE_UNLOCK,
    SCORE_REDUCTION, SKIP_CARD, TRAPS,
)
from .rules import MIN_EXTRA_DRAWS, MIN_WILD_CARDS

if TYPE_CHECKING:
    from .world import Phase10World

DEFAULT_ITEM_CLASSIFICATIONS = {
    **{PHASE_UNLOCK.format(p): ItemClassification.progression
       for p in range(1, PHASE_COUNT + 1)},
    "Wild Card": ItemClassification.progression,
    "Extra Draw": ItemClassification.progression,
    "Hand Size Upgrade": ItemClassification.useful,
    SKIP_CARD: ItemClassification.useful,
    "Phase Lock": ItemClassification.trap,
    "Lean Deal": ItemClassification.trap,
    "Wild Theft": ItemClassification.trap,
    MULLIGAN: ItemClassification.filler,
    SCORE_REDUCTION: ItemClassification.filler,
}



class Phase10Item(Item):
    game = GAME_NAME


def get_random_filler_item_name(world: Phase10World) -> str:
    if world.random.randint(0, 99) < world.options.trap_chance:
        return world.random.choice(TRAPS)
    return world.random.choice(FILLERS)


def create_item_with_correct_classification(world: Phase10World, name: str) -> Phase10Item:
    classification = DEFAULT_ITEM_CLASSIFICATIONS[name]

    return Phase10Item(name, classification, ITEM_NAME_TO_ID[name], world.player)


def create_surplus(world: Phase10World, name: str) -> Phase10Item:
    """A copy beyond what logic can demand: helpful, but not required.

    Marking the surplus `useful` rather than `progression` keeps the pool from
    being almost entirely progression, which fill cannot place into a location
    set this small.
    """
    return Phase10Item(name, ItemClassification.useful, ITEM_NAME_TO_ID[name], world.player)


def build_power_item_counts(world: Phase10World, capacity: int) -> dict[str, int]:
    """Decide how many of each power item fit in the available locations.

    The ten phase unlocks are mandatory, and logic requires floors of Wild Card
    and Extra Draw to reach the harder phases at all. Anything above those
    floors is trimmed -- comfort first, then draws, then wilds -- so that a
    small location pool cannot produce an unfillable seed.
    """
    unlocks = PHASE_COUNT
    floor = unlocks + MIN_WILD_CARDS + MIN_EXTRA_DRAWS
    if capacity < floor:
        from Options import OptionError
        raise OptionError(
            f"Phase 10: {capacity} locations is not enough for the {floor} items logic "
            f"requires. Raise checks_per_phase."
        )

    counts = {
        "Wild Card": int(world.options.wild_card_items),
        "Extra Draw": int(world.options.extra_draw_items),
        "Hand Size Upgrade": int(world.options.hand_size_upgrades),
        SKIP_CARD: int(world.options.skip_card_items),
    }
    floors = {"Wild Card": MIN_WILD_CARDS, "Extra Draw": MIN_EXTRA_DRAWS,
              "Hand Size Upgrade": 0, SKIP_CARD: 0}

    # Trim in this order until the pool fits, never below the logic floors.
    for name in (SKIP_CARD, "Hand Size Upgrade", "Extra Draw", "Wild Card"):
        while unlocks + sum(counts.values()) > capacity and counts[name] > floors[name]:
            counts[name] -= 1
    return counts


def choose_starting_phases(world: Phase10World) -> list[int]:
    """Pick which phases the player opens with, easy ones first.

    Handing out a hard phase as the only starter would leave the player unable
    to clear anything until wilds or draws show up, which is exactly the dead
    opening this is meant to avoid.
    """
    from .rules import EASY_PHASES

    easy = sorted(EASY_PHASES)
    rest = [p for p in range(1, PHASE_COUNT + 1) if p not in EASY_PHASES]
    world.random.shuffle(easy)
    world.random.shuffle(rest)
    return (easy + rest)[: int(world.options.starting_phases)]


def create_all_items(world: Phase10World) -> None:
    capacity = len(world.multiworld.get_unfilled_locations(world.player))

    starting = set(choose_starting_phases(world))
    for phase in sorted(starting):
        world.push_precollected(world.create_item(PHASE_UNLOCK.format(phase)))

    itempool: list[Item] = [
        world.create_item(PHASE_UNLOCK.format(p))
        for p in range(1, PHASE_COUNT + 1)
        if p not in starting
    ]

    floors = {"Wild Card": MIN_WILD_CARDS, "Extra Draw": MIN_EXTRA_DRAWS,
              "Hand Size Upgrade": 0, SKIP_CARD: 0}
    for name, count in build_power_item_counts(world, capacity).items():
        required = min(count, floors[name])
        itempool += [world.create_item(name) for _ in range(required)]
        itempool += [create_surplus(world, name) for _ in range(count - required)]

    itempool += [world.create_filler() for _ in range(capacity - len(itempool))]
    world.multiworld.itempool += itempool
