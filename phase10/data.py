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
GAME_NAME = "AP_Phase10"

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

ITEM_NAME_TO_ID = {
    **{PHASE_UNLOCK.format(p): p for p in range(1, 11)},
    WILD_CARD: 20,
    EXTRA_DRAW: 21,
    HAND_SIZE_UPGRADE: 22,
    SKIP_CARD: 23,
    PHASE_LOCK: 30,
    LEAN_DEAL: 31,
    WILD_THEFT: 32,
    MULLIGAN: 40,
    SCORE_REDUCTION: 41,
}

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
        for phase in range(1, 11)
        for index, tier in enumerate(TIERS)
    },
    # Phase checks occupy 110..203 (100 + phase * 10 + tier), so milestones
    # start well clear of Phase 10 rather than colliding with it at 200.
    **{
        milestone_location_name(n): 300 + index
        for index, n in enumerate(HANDS_WON_MILESTONES)
    },
}

#: Baseline deck and deal, before any Archipelago item is applied.
BASE_HAND_SIZE = 10

#: Skips are granted into hand, never shuffled in, so this caps the item count
#: rather than describing the deck.
MAX_SKIPS = 4
