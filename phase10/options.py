from dataclasses import dataclass

from Options import Choice, DeathLink, OptionGroup, PerGameCommonOptions, Range, Toggle

from .data import DEFAULT_BUFF_POINTS, MAX_STORE_SLOTS, PHASE_COUNT


class Goal(Choice):
    """
    What finishes the multiworld.

    all_phases: clear phases 1 up to `phases_to_win`. At the default of 20
                that is every phase; at 10 it is the ten the box ships with.
    phase_ten:  clear Phase 10 only. Much shorter, and since the phases are
                unlocked out of order this is not necessarily the last one you
                will be able to attempt.
    """
    display_name = "Goal"
    option_all_phases = 0
    option_phase_ten = 1
    default = option_all_phases


class PhasesToWin(Range):
    """
    How many phases `all_phases` actually asks for: clear 1 up to this one.

    20 is every phase. 10 is the game the box ships, and a complete one.

    `random-range-10-20` picks a length per seed; `random` picks from the whole
    range. Whatever it picks, every phase up to it is required and reachable.

    Ignored when the goal is `phase_ten`.
    """
    display_name = "Phases To Win"
    range_start = 1
    range_end = PHASE_COUNT
    default = PHASE_COUNT


class SkipMode(Choice):
    """
    What playing a Skip does.

    dig:  look at the top three of the draw pile and keep one, free. Not the
          printed rule, and the one the phase difficulty is balanced around.
    deny: the printed rule. Discard the Skip and choose who sits out a turn.

    **`deny` makes a seed harder.** A denied turn is worth little when the
    round is a race against your draw budget rather than against the table,
    so the Skip goes from the strongest item in the pool to nearly nothing --
    worth about a twentieth of what the dig is worth. Pick it if you want the
    printed rule and a tougher seed, not if you want Skips to feel useful.

    `skip_card_items` still wants leaving alone either way: more Skips helps a
    little under `deny` and never hurts.
    """
    display_name = "Skip Mode"
    option_dig = 0
    option_deny = 1
    default = option_dig


class StartingDraws(Range):
    """
    How many draws you get per hand before Extra Draw items are counted.

    This is the strongest difficulty setting in the file by a distance, and
    lower is much harder. It also decides how much Extra Draw items matter:
    start low and they become the spine of the run.
    """
    display_name = "Starting Draws"
    range_start = 2
    range_end = 12
    default = 4


class Opponents(Range):
    """
    How many computer players share the table with you.

    They draw from the same deck, build toward their own phases, and when one
    of them goes out your round ends wherever it stands. More opponents means
    shorter rounds, not merely busier ones. Set to 0 for the solo game, where
    only your draw budget can end a round.
    """
    display_name = "Opponents"
    range_start = 0
    range_end = 3
    default = 3


class ExtraDrawItems(Range):
    """
    How many Extra Draw items go in the pool. Each adds one draw per hand.

    The floor of 5 is what logic requires -- the No Wilds check asks for five
    of them -- so a smaller pool would leave those checks unreachable.

    The ceiling is low because draws stop buying anything past about eight in
    total. At the default `starting_draws` of 4 you are already there, so
    lower that if you want every copy to matter.
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

    Easy phases are handed out first, so your opening phases are clearable
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
    2: also clear it inside half your draw budget.
    3: also clear it without using a single wild.
    4: also shed your whole hand and go out.

    It is a prefix, so a lower number drops the hardest tiers rather than the
    easiest.

    More checks means more filler in the pool, not more meaningful items --
    there are only so many wilds and draws worth having, and the rest is
    Mulligans. Two is the size the item pool was built for. Raise it if you
    would rather have more checks than better ones.

    Going out is the last tier because playing solo it is unreachable on eight
    of the twenty phases.
    """
    display_name = "Checks Per Phase"
    range_start = 1
    range_end = 4
    default = 2


class SkipCardItems(Range):
    """
    How many Skip Card items go in the pool.

    Each one puts a Skip in your hand at the start of every hand, dealt on top
    of your hand size so it costs no room. They are granted rather than
    shuffled into the deck, so you always get them.

    What a Skip does is set by `skip_mode`, and that decides how much these are
    worth: a lot under `dig`, very little under `deny`.
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


class StoreSlots(Range):
    """
    How many checks the store sells for AP Points.

    The store is a second track beside the phases: AP Points arrive as items,
    and a slot can be bought once you hold enough of them. Prices ascend
    (1, 1, 1, 1, 2, 2, 3, 3), and a slot opens once you could have afforded
    every cheaper one -- so you can buy them in any order. Connected, each slot
    says what it is holding.

    The store brings its own locations, so it is close to free. At
    `checks_per_phase: 1` there is little room and it trims itself to fit.

    0 turns the store off.
    """

    display_name = "Store Slots"
    range_start = 0
    range_end = MAX_STORE_SLOTS
    default = 6


class StoreGating(Choice):
    """
    How the store's slots open.

    ladder:       prices ascend (1, 1, 1, 1, 2, 2, 3, 3) and the slots open one
                  at a time, the first at 1 point.
    all_at_once:  every slot costs 1 point, and they all open together once you
                  hold enough to buy every one -- 6 points at 6 slots. Then you
                  pick the order, with each slot showing what it holds.

    `all_at_once` is quieter early -- no store check until the whole store
    opens -- but reaches every slot sooner, and fits a full store into seeds
    the ladder has to trim. Spending money for the one-use cards is the same
    either way; `store_buff_points` sets that.
    """
    display_name = "Store Gating"
    option_ladder = 0
    option_all_at_once = 1
    default = option_ladder


class StoreBuffPoints(Range):
    """
    Extra AP Points the seed carries for the store's one-use cards.

    The store also sells a card rather than a check: a One-Use Wild for two
    points or a One-Use Skip for one, as often as you can afford them, gone
    the moment you play them. They are there for the run where you are three
    rounds into phase 17 and the deck will not give you a fourth nine.

    This is the spending money for them, on top of what the slots cost, so
    buying cards can never cost you a check.

    **Past 12 this starts costing you Wild Card items** at the default two
    checks a phase -- trading wilds that are in the deck every round for wilds
    you get once. At three or four checks a phase there is room for the lot.

    0 turns the one-use cards off and leaves the store selling checks alone.
    """

    display_name = "Store Buff Points"
    range_start = 0
    range_end = 20
    default = DEFAULT_BUFF_POINTS


@dataclass
class Phase10Options(PerGameCommonOptions):
    goal: Goal
    phases_to_win: PhasesToWin
    skip_mode: SkipMode
    starting_phases: StartingPhases
    opponents: Opponents
    starting_draws: StartingDraws
    extra_draw_items: ExtraDrawItems
    wild_card_items: WildCardItems
    hand_size_upgrades: HandSizeUpgrades
    checks_per_phase: ChecksPerPhase
    store_slots: StoreSlots
    store_gating: StoreGating
    store_buff_points: StoreBuffPoints
    skip_card_items: SkipCardItems
    trap_chance: TrapChance
    death_link: Phase10DeathLink


option_groups = [
    OptionGroup("Goal", [Goal, PhasesToWin, ChecksPerPhase, StoreSlots,
                         StoreGating, StoreBuffPoints, StartingPhases]),
    OptionGroup("Difficulty", [Opponents, StartingDraws, ExtraDrawItems,
                               WildCardItems, HandSizeUpgrades, SkipCardItems,
                               SkipMode]),
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
