from dataclasses import dataclass

from Options import Choice, DeathLink, OptionGroup, PerGameCommonOptions, Range, Toggle


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


class Opponents(Range):
    """
    How many computer players share the table with you.

    They draw from the same deck, build toward their own phases, and when one
    of them goes out your round ends wherever it stands. Set to 0 for the solo
    game, where only your draw budget can end a round.

    Three opponents end a round around turn five. That is a minimum-of-N
    effect -- one seat alone takes about eight turns -- so more opponents make
    rounds shorter, not just busier.
    """
    display_name = "Opponents"
    range_start = 0
    range_end = 3
    default = 3


class ExtraDrawItems(Range):
    """
    How many Extra Draw items go in the pool. Each adds one draw per hand.

    The floor of 5 is the most logic can demand: the No Wilds check on every
    phase asks for Extra Draw x5, so a smaller pool leaves those checks
    unreachable and the seed will not generate.

    The ceiling is low on purpose. With opponents at the table the round ends
    when somebody goes out, and past roughly eight *total* draws the budget
    stops buying anything. Measured across the ten phases, going from 4 draws
    to 8 is worth real clear rate; from 8 to 14 is worth nothing at all.
    Anything past that range is a dead item in the pool.

    At the default starting_draws of 4 the floor of 5 already puts you at 9
    total, so the fifth copy is carrying a logic requirement rather than any
    real difficulty. Lower starting_draws if you want every copy to bite.
    """
    display_name = "Extra Draw Items"
    range_start = 5
    range_end = 8
    default = 5


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

    Twenty phases at four checks each is ninety locations, and the item pool
    cannot fill that with anything meaningful: wilds are capped by the deck's
    eight, extra draws by the point past which they buy nothing, and skips and
    hand size by their own limits. The remainder is filler, and at four checks
    it measured 59% of the pool -- thirty-five Mulligans, which is an infinite
    supply. Two checks a phase keeps the world at fifty locations, the size the
    item pool was actually built for. Raise it if you would rather have more
    checks than more meaningful items.

    1: clear the phase.
    2: also clear it inside half your draw budget.
    3: also clear it without using a single wild.
    4: also shed your whole hand and go out.

    In that order because it is a prefix, so a lower number drops the hardest
    tiers rather than the easiest. Going out is last because solo it is
    unreachable on eight of the twenty phases.
    """
    display_name = "Checks Per Phase"
    range_start = 1
    range_end = 4
    default = 2


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


class Phase10DeathLink(DeathLink):
    """
    Share deaths with the rest of the multiworld.

    There is nothing to kill in a card game, so a death is a lost hand: when
    someone else dies your current hand fails on the spot, and when a hand of
    yours runs out of draws everyone linked loses theirs. Between rounds you
    have nothing to lose, so an incoming death passes harmlessly.
    """


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
    opponents: Opponents
    starting_draws: StartingDraws
    extra_draw_items: ExtraDrawItems
    wild_card_items: WildCardItems
    hand_size_upgrades: HandSizeUpgrades
    checks_per_phase: ChecksPerPhase
    skip_card_items: SkipCardItems
    trap_chance: TrapChance
    death_link: Phase10DeathLink


option_groups = [
    OptionGroup("Goal", [Goal, ChecksPerPhase, StartingPhases]),
    OptionGroup("Difficulty", [Opponents, StartingDraws, ExtraDrawItems,
                               WildCardItems, HandSizeUpgrades, SkipCardItems]),
    OptionGroup("Deck", [TrapChance, Phase10DeathLink]),
]

option_presets = {
    "tight": {
        "goal": Goal.option_all_phases,
        "starting_phases": 1,
        "opponents": 3,
        "starting_draws": 2,
        "extra_draw_items": 8,
        "wild_card_items": 8,
        "hand_size_upgrades": 0,
        "checks_per_phase": 4,
        "skip_card_items": 0,
        "trap_chance": 20,
    },
    "short": {
        "goal": Goal.option_phase_ten,
        "starting_phases": 3,
        "opponents": 0,
        "starting_draws": 6,
        "extra_draw_items": 6,
        "wild_card_items": 8,
        "hand_size_upgrades": 2,
        "checks_per_phase": 2,
        "skip_card_items": 4,
        "trap_chance": 0,
    },
}
