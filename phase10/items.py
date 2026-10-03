from __future__ import annotations

from typing import TYPE_CHECKING

from BaseClasses import Item, ItemClassification

from .data import (
    AP_POINT, FILLERS, GAME_NAME, ITEM_NAME_TO_ID, MULLIGAN, PHASE_COUNT,
    PHASE_UNLOCK, SCORE_REDUCTION, SKIP_CARD, STORE_ALWAYS_OPEN, STORE_LADDER, STORE_SLACK,
    TRAPS, store_prices,
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
    # Progression rather than filler: a point opens a store slot, so fill has
    # to reason about where they land.
    AP_POINT: ItemClassification.progression,
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


def plan_store(base_locations: int, slots: int, floor: int,
               buff_points: int = 0,
               gating: str = STORE_LADDER) -> tuple[int, int]:
    """The largest store that still fits, as (slots, points).

    A store of S slots brings S locations with it, so it pays for itself up to
    one point per slot; only the ladder's steeper end and whatever spare points
    ride along cost the pool anything. When it does not fit, the spare points
    go first -- they are comfort, and the buff budget is the most optional
    comfort there is -- and only then does a slot come off.

    Slack and buff budget are one number here on purpose. Both are simply
    points the ladder does not need, and at the table they are the same thing:
    the store reserves what the unbought slots cost and lets you spend the
    rest, so a point held back for the last slot and a point earmarked for a
    One-Use Wild are indistinguishable until you spend one.

    Measured: at one check a phase there are thirty locations and a floor of
    twenty-nine, so this lands on five slots with nothing spare -- exactly
    where it landed before the buffs existed. At two checks and up the ladder,
    the slack and the buff budget all survive.
    """
    # All at once, every slot costs one point, so the store always pays for
    # itself and only the spare points can ever be trimmed. Same loop: it is
    # the ladder's cost that changes, not the rule for what fits.
    for count in range(slots, 0, -1):
        ladder = sum(store_prices(count, gating))
        for spare in range(STORE_SLACK + buff_points, -1, -1):
            points = ladder + spare
            if floor + points <= base_locations + count:
                return count, points
    return 0, 0


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

    # Points come off the top. They are required items, and the power items
    # above their floors are not, so sizing power first would spend the
    # store's own locations on Wild Cards and leave the points homeless.
    points = world.store_points
    # Always open, the store's worst case -- three a slot -- is progression,
    # so fill puts every point the slots could cost somewhere reachable; that
    # is what the store's softlock-freedom stands on. The rest is slack and
    # spending money, and leaving it progression too packed a solo seed tight
    # enough to fail fill. The ladder keeps every point progression, as it
    # always has.
    needed = points
    if world.store_gating == STORE_ALWAYS_OPEN and points:
        needed = sum(store_prices(int(world.options.store_slots), STORE_ALWAYS_OPEN))
    itempool += [world.create_item(AP_POINT) for _ in range(needed)]
    itempool += [create_surplus(world, AP_POINT) for _ in range(points - needed)]

    floors = {"Wild Card": MIN_WILD_CARDS, "Extra Draw": MIN_EXTRA_DRAWS,
              "Hand Size Upgrade": 0, SKIP_CARD: 0}
    for name, count in build_power_item_counts(world, capacity - points).items():
        required = min(count, floors[name])
        itempool += [world.create_item(name) for _ in range(required)]
        itempool += [create_surplus(world, name) for _ in range(count - required)]

    itempool += [world.create_filler() for _ in range(capacity - len(itempool))]
    world.multiworld.itempool += itempool
