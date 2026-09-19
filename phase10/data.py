"""Names and IDs shared by the world and the client.

Deliberately free of Archipelago imports so the client's pure logic can be
tested without a checkout -- and, more importantly, so the two sides cannot
drift apart. Duplicating these tables would desync the client's reported
location IDs from the world's definitions in a way nothing would catch until a
seed was half played.
"""

from __future__ import annotations

#: The Archipelago game identifier. Everything that must agree on it --
#: world, items, locations, client, launcher, UI tab -- reads it from here.
#: archipelago.json and the docs filename carry their own copies because
#: they are not Python; the generation test catches it if those drift.
GAME_NAME = "AP_10"

#: How many phases the world ships. Kept as a literal rather than imported
#: from game.phases so this module stays dependency-free; test_data asserts the
#: two agree.
PHASE_COUNT = 20

PHASE_UNLOCK = "Phase {} Unlocked"
PHASE_CLEAR_EVENT = "Phase {} Clear"

WILD_CARD = "Wild Card"
EXTRA_DRAW = "Extra Draw"
HAND_SIZE_UPGRADE = "Hand Size Upgrade"
SKIP_CARD = "Skip Card"

PHASE_LOCK = "Phase Lock"
LEAN_DEAL = "Lean Deal"
WILD_THEFT = "Wild Theft"

MULLIGAN = "Mulligan"
SCORE_REDUCTION = "Score Reduction"

TRAPS = [PHASE_LOCK, LEAN_DEAL, WILD_THEFT]
FILLERS = [MULLIGAN, SCORE_REDUCTION]

#: Points a single Score Reduction takes off the running total. Twenty-five is
#: the deck's own largest penalty -- what a Wild left in hand costs you -- so
#: one of these is worth exactly the worst card you can be caught holding.
SCORE_REDUCTION_VALUE = 25

# Phase unlocks own 1..PHASE_COUNT, so everything else starts above any phase
# count this world will plausibly reach. At ten phases the power items sat at
# 20-23 and were fine; at twenty, "Phase 20 Unlocked" and "Wild Card" both
# wanted ID 20. test_data caught it, which is exactly what it is for.
ITEM_NAME_TO_ID = {
    **{PHASE_UNLOCK.format(p): p for p in range(1, PHASE_COUNT + 1)},
    WILD_CARD: 50,
    EXTRA_DRAW: 51,
    HAND_SIZE_UPGRADE: 52,
    SKIP_CARD: 53,
    PHASE_LOCK: 60,
    LEAN_DEAL: 61,
    WILD_THEFT: 62,
    MULLIGAN: 70,
    SCORE_REDUCTION: 71,
}

#: The lowest non-unlock item ID. Phase unlocks must stay clear of it.
FIRST_FIXED_ITEM_ID = 50

#: Check tiers in unlock order; `checks_per_phase` takes a prefix of this list.
TIERS = ["Cleared", "Went Out", "No Wilds", "Under Par"]

#: Cumulative "just keep playing" checks. They gate on nothing, which is what
#: gives a seed a workable opening.
HANDS_WON_MILESTONES = [1, 2, 3, 5, 8, 12, 16, 20, 25, 30]


def phase_location_name(phase: int, tier: str) -> str:
    return f"Phase {phase} - {tier}"


def milestone_location_name(hands: int) -> str:
    return f"Hands Won: {hands}"


LOCATION_NAME_TO_ID = {
    **{
        phase_location_name(phase, tier): 100 + phase * 10 + index
        for phase in range(1, PHASE_COUNT + 1)
        for index, tier in enumerate(TIERS)
    },
    # Phase checks occupy 110..(100 + PHASE_COUNT * 10 + 3). At ten phases that
    # topped out at 203 and milestones sat safely at 300; at twenty it reaches
    # 303 and collides with them head on. Moved to 400, which clears any phase
    # count up to 29. The first version of this world shipped a duplicate
    # address exactly once, and only a real generation caught it.
    **{
        milestone_location_name(n): 400 + index
        for index, n in enumerate(HANDS_WON_MILESTONES)
    },
}

#: Baseline deck and deal, before any Archipelago item is applied.
BASE_HAND_SIZE = 10

#: Skips are granted into hand, never shuffled in, so this caps the item count
#: rather than describing the deck.
MAX_SKIPS = 4
