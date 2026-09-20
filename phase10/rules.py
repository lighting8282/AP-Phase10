"""Access rules, derived from measured difficulty rather than intuition.

Autoplayed simulation (see the project README) shows the printed phase order is
not a difficulty ramp, and that big sets are far harder than long runs: with no
wilds and an 8-draw budget, Phase 7 (two sets of 4) clears 1% of the time while
Phase 6 (a run of 9) clears 14%. Each rank has only eight copies in the deck, so
a set of five competes for a scarce rank, whereas any of eight copies can fill a
run slot. The tiers below follow those measurements.

Unlocking a phase only seats you at the table -- the entrance rule is the unlock
alone. What the measured difficulty gates is *clearing* it, so the requirements
live on the locations. That keeps every unlock immediately worth something,
which matters because otherwise a seed can open with nothing reachable at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rule_builder.rules import Has, HasAll, Rule

from .data import PHASE_COUNT
from .options import Goal

if TYPE_CHECKING:
    from .world import Phase10World

# Measured clear rates at 0 wilds / 8 draws:
#   1: 40%   2: 66%   3: 20%   4: 42%   5: 19%
#   6: 14%   7:  1%   8: 38%   9:  7%  10:  4%
# Phases 11-20 measured the same way, at 600 trials:
#   11: 94%  12: 91%  13: 79%  14: 72%  15: 62%
#   16: 57%  17: 49%  18: 29%  19: 22%  20: 11%
# They fill a hole the stock ten left: nothing above 66%, so every phase was a
# fight. The boundaries are the same ones the original ten implied -- easy at
# roughly 40% and up, hard below 15%.
EASY_PHASES = frozenset({1, 2, 4, 11, 12, 13, 14, 15, 16, 17})
MEDIUM_PHASES = frozenset({3, 5, 6, 8, 18, 19})
HARD_PHASES = frozenset({7, 9, 10, 20})

#: How many of each power item logic can actually demand. Items beyond these
#: counts are comfort, not progression -- see items.py, which classifies the
#: surplus as `useful` so fill is not swamped with required items.
MIN_WILD_CARDS = 4
MIN_EXTRA_DRAWS = 5


def difficulty_requirement(phase: int) -> Rule | None:
    """What clearing a phase costs, beyond having unlocked it."""
    if phase in EASY_PHASES:
        return None
    if phase in MEDIUM_PHASES:
        return Has("Wild Card", count=2) | Has("Extra Draw", count=2)
    return Has("Wild Card", count=4) | Has("Extra Draw", count=4)


#: Extra demands per check tier, on top of clearing the phase at all.
TIER_REQUIREMENTS: dict[str, Rule | None] = {
    "Cleared": None,
    # Speed comes from wilds collapsing a hand early, not from more draws.
    # Two rather than four: this is the second tier now, so at the default of
    # `checks_per_phase: 2` it gates every phase's other check -- and four is
    # also the hard-phase gate, which would funnel most of the world through a
    # single item threshold.
    "Under Par": Has("Wild Card", count=2),
    # Without wilds to paper over gaps, only a deeper draw budget gets there.
    "No Wilds": Has("Extra Draw", count=5),
    # Shedding every remaining card after laying down takes more turns.
    "Went Out": Has("Extra Draw", count=3),
}


def set_all_rules(world: Phase10World) -> None:
    set_phase_entrance_rules(world)
    set_location_rules(world)
    set_completion_condition(world)


def set_phase_entrance_rules(world: Phase10World) -> None:
    for phase in range(1, PHASE_COUNT + 1):
        world.set_rule(
            world.get_entrance(f"Menu to Phase {phase}"), Has(f"Phase {phase} Unlocked")
        )


def set_location_rules(world: Phase10World) -> None:
    for phase in range(1, PHASE_COUNT + 1):
        difficulty = difficulty_requirement(phase)

        for location in world.get_region(f"Phase {phase}").locations:
            tier = location.name.rsplit(" - ", 1)[-1]
            if tier == location.name:
                # An event ("Phase N Cleared"), which mirrors the base check.
                combined = difficulty
            else:
                combined = _combine(difficulty, TIER_REQUIREMENTS[tier])
            if combined is not None:
                world.set_rule(location, combined)


def _combine(a: Rule | None, b: Rule | None) -> Rule | None:
    if a is None:
        return b
    if b is None:
        return a
    return a & b


def set_completion_condition(world: Phase10World) -> None:
    if world.options.goal == Goal.option_phase_ten:
        goal_rule: Rule = Has("Phase 10 Clear")
    else:
        goal_rule = HasAll(*(f"Phase {p} Clear" for p in range(1, PHASE_COUNT + 1)))
    world.set_rule(world.get_entrance("Menu to Victory"), goal_rule)
    world.set_completion_rule(Has("Victory"))
