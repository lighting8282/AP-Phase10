from dataclasses import dataclass

from Options import Choice, OptionGroup, PerGameCommonOptions, Range, Toggle


class Goal(Choice):
    """
    What finishes the multiworld.

    all_phases: clear every one of the ten phases.
    phase_ten:  clear Phase 10 only. Much shorter, and since the phases are
                unlocked out of order this is not necessarily the last one you
                will be able to attempt.
    """
    display_name = "Goal"
    option_all_phases = 0
    option_phase_ten = 1
    default = option_all_phases


class StartingDraws(Range):
    """
    How many draws you get per hand before Extra Draw items are counted.

    The draw budget replaces the multiplayer race to go out, and it is by far
    the strongest difficulty knob. At 8 total draws the ten phases spread from
    roughly 66% down to 1% success. Low values here make Extra Draw items the
    spine of the run.
    """
    display_name = "Starting Draws"
    range_start = 2
    range_end = 12
    default = 4


class ExtraDrawItems(Range):
    """
    How many Extra Draw items go in the pool. Each adds one draw per hand.
    """
    display_name = "Extra Draw Items"
    range_start = 3
    range_end = 16
    default = 12


class WildCardItems(Range):
    """
    How many Wild Card items go in the pool. You start with a deck containing
    no wilds at all; each item puts one of the stock eight back.
    """
    display_name = "Wild Card Items"
    range_start = 4
    range_end = 8
    default = 8


class HandSizeUpgrades(Range):
    """
    How many Hand Size Upgrade items go in the pool. Each deals you one extra
    card at the start of every hand.
    """
    display_name = "Hand Size Upgrades"
    range_start = 0
    range_end = 2
    default = 2


class StartingPhases(Range):
    """
    How many phases you begin with already unlocked.

    At least one is needed or a seed opens with nothing you can play. Easy
    phases are handed out first, so the opening phases are actually clearable
    before any Wild Card or Extra Draw has arrived.
    """
    display_name = "Starting Phases"
    range_start = 1
    range_end = 4
    default = 2


class ChecksPerPhase(Range):
    """
    How many checks each phase is worth.

    1: clear the phase.
    2: also clear it and go out in the same hand.
    3: also clear it without using a single wild.
    4: also clear it inside half your draw budget.
    """
    display_name = "Checks Per Phase"
    range_start = 2
    range_end = 4
    default = 4


class SkipCardItems(Range):
    """
    How many Skip Card items go in the pool.

    Each one puts a Skip in your hand at the start of every hand, dealt on top
    of your hand size so it costs no room. Play it to look at the top three of
    the draw pile and keep one, free -- the Skip becomes that turn's discard.

    Skips are granted, never shuffled into the deck. Measured in the deck they
    turn up about a third of a hand and are a straight loss; held, the first one
    is worth roughly twelve points of success rate on the hardest phases.
    """
    display_name = "Skip Card Items"
    range_start = 0
    range_end = 4
    default = 4


class TrapChance(Range):
    """
    Percentage chance that any given filler item is replaced by a trap.
    """
    display_name = "Trap Chance"
    range_start = 0
    range_end = 100
    default = 0


@dataclass
class Phase10Options(PerGameCommonOptions):
    goal: Goal
    starting_phases: StartingPhases
    starting_draws: StartingDraws
    extra_draw_items: ExtraDrawItems
    wild_card_items: WildCardItems
    hand_size_upgrades: HandSizeUpgrades
    checks_per_phase: ChecksPerPhase
    skip_card_items: SkipCardItems
    trap_chance: TrapChance


option_groups = [
    OptionGroup("Goal", [Goal, ChecksPerPhase, StartingPhases]),
    OptionGroup("Difficulty", [StartingDraws, ExtraDrawItems, WildCardItems,
                               HandSizeUpgrades, SkipCardItems]),
    OptionGroup("Deck", [TrapChance]),
]

option_presets = {
    "tight": {
        "goal": Goal.option_all_phases,
        "starting_phases": 1,
        "starting_draws": 2,
        "extra_draw_items": 16,
        "wild_card_items": 8,
        "hand_size_upgrades": 0,
        "checks_per_phase": 4,
        "skip_card_items": 0,
        "trap_chance": 20,
    },
    "short": {
        "goal": Goal.option_phase_ten,
        "starting_phases": 3,
        "starting_draws": 6,
        "extra_draw_items": 6,
        "wild_card_items": 8,
        "hand_size_upgrades": 2,
        "checks_per_phase": 2,
        "skip_card_items": 4,
        "trap_chance": 0,
    },
}
