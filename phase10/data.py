"""Names and IDs shared by the world and the client.

Deliberately free of Archipelago imports so the client's pure logic can be
tested without a checkout -- and, more importantly, so the two sides cannot
drift apart. Duplicating these tables would desync the client's reported
location IDs from the world's definitions in a way nothing would catch until a
seed was half played.
"""

from __future__ import annotations

PHASE_UNLOCK = "Phase {} Unlocked"
PHASE_CLEAR_EVENT = "Phase {} Clear"

WILD_CARD = "Wild Card"
EXTRA_DRAW = "Extra Draw"
HAND_SIZE_UPGRADE = "Hand Size Upgrade"

PHASE_LOCK = "Phase Lock"
LEAN_DEAL = "Lean Deal"
WILD_THEFT = "Wild Theft"

TRAPS = [PHASE_LOCK, LEAN_DEAL, WILD_THEFT]
FILLERS = ["Mulligan", "Score Reduction"]

ITEM_NAME_TO_ID = {
    **{PHASE_UNLOCK.format(p): p for p in range(1, 11)},
    WILD_CARD: 20,
    EXTRA_DRAW: 21,
    HAND_SIZE_UPGRADE: 22,
    PHASE_LOCK: 30,
    LEAN_DEAL: 31,
    WILD_THEFT: 32,
    "Mulligan": 40,
    "Score Reduction": 41,
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
    **{
        milestone_location_name(n): 200 + index
        for index, n in enumerate(HANDS_WON_MILESTONES)
    },
}

#: Baseline deck and deal, before any Archipelago item is applied.
BASE_HAND_SIZE = 10
STOCK_SKIPS = 4
