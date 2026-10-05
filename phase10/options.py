from dataclasses import dataclass

from Options import Choice, DeathLink, OptionGroup, PerGameCommonOptions, Range, Toggle

from .data import (
    DEFAULT_BUFF_POINTS, DEFAULT_SCORE_THRESHOLD, MAX_SCORE_THRESHOLD, MAX_STORE_SLOTS,
    MIN_SCORE_THRESHOLD, PHASE_COUNT,
)


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

    dig:  look at the top three cards of the draw pile and keep one, free. The
          phase difficulty is balanced around this.
    deny: the printed rule. Discard the Skip and choose who sits out a turn.

    `deny` makes a seed noticeably harder: a lost turn matters little when you
    are racing your own draw budget, so Skips become much weaker.
    """
    display_name = "Skip Mode"
    option_dig = 0
    option_deny = 1
    default = option_dig


class OpponentPhase(Choice):
    """
    Which phase the computer players play.

    match:  the same phase as you, every round. How hard a round is then
            depends only on the phase you picked and your items.
    own:    each starts on Phase 1 and climbs as it clears its own. Since you
            play phases out of order, their phase drifts away from yours, and
            how fast they go out -- which can end your round -- drifts with it.
    """
    display_name = "Opponent Phase"
    option_match = 0
    option_own = 1
    default = option_match


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
    default = 6


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

    Draws stop helping past about eight per hand, so at the default
    `starting_draws` of 6 only the first two or so matter. Lower
    `starting_draws` if you want every one to count.
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

    More checks mostly means more filler, not more useful items. Two is what
    the item pool was built for.
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

    You send one every `score_threshold` points of round score -- the points
    left in your hand when rounds end. Score Reduction items push the next one
    further away. When someone else dies, your current hand is lost; between
    rounds there is nothing to lose, so it passes harmlessly.
    """


class ScoreThreshold(Range):
    """
    How many points of round score set off `death_link` and `score_traps`.

    Each time your running score passes another multiple of this, you send a
    DeathLink death if `death_link` is on, and one of your own traps hits your
    next hand if `score_traps` is on. Both can be on.

    A round costs about 30 points on average -- a few when you clear it, about
    60 when you don't -- so 500 is roughly once every 16 rounds, 100 every 3,
    and 1000 every 30.
    """
    display_name = "Score Threshold"
    range_start = MIN_SCORE_THRESHOLD
    range_end = MAX_SCORE_THRESHOLD
    default = DEFAULT_SCORE_THRESHOLD


class ScoreTraps(Toggle):
    """
    Each time your score passes `score_threshold`, a trap hits your next hand:
    Lean Deal (two fewer cards) and Wild Theft (one fewer wild), taking turns.

    A cost for a high score that does not need DeathLink.
    """
    display_name = "Score Traps"


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
    How many checks the store sells for AP Points, which arrive as items.

    How the slots open is set by `store_gating`. Connected to a room, each slot
    shows what it holds. With `checks_per_phase: 1` there may be room for fewer
    slots than you ask for.

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
    always_open:  every slot can be bought from the start. Its price is set by
                  what it holds: trap or filler 1 point, useful 2, progression 3.
                  Your own AP Point costs 1, so buying it back is never a loss.

    `always_open` needs more points in the pool, which leaves less room for the
    store in a tight seed: with `checks_per_phase: 1` it does not fit at all.
    Points the slots end up not costing become spending money for the one-use
    cards.
    """
    display_name = "Store Gating"
    option_ladder = 0
    option_always_open = 1
    # 1.5.0's name for this option value, which opened every slot together
    # once the whole store was affordable. Not what was wanted; a YAML that
    # still says it gets the store it was asking for.
    alias_all_at_once = option_always_open
    default = option_ladder


class StoreBuffPoints(Range):
    """
    Extra AP Points for the store's one-use cards: a One-Use Wild for 2 points
    or a One-Use Skip for 1, bought as often as you can afford and gone once
    played. These are on top of what the slots cost, so buying cards never costs
    you a check.

    Past 12, at the default two checks a phase, this starts replacing Wild Card
    items. 0 turns the one-use cards off.
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
    opponent_phase: OpponentPhase
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
    score_threshold: ScoreThreshold
    score_traps: ScoreTraps


option_groups = [
    OptionGroup("Goal", [Goal, PhasesToWin, ChecksPerPhase, StoreSlots,
                         StoreGating, StoreBuffPoints, StartingPhases]),
    OptionGroup("Difficulty", [Opponents, OpponentPhase, StartingDraws, ExtraDrawItems,
                               WildCardItems, HandSizeUpgrades, SkipCardItems,
                               SkipMode]),
    OptionGroup("Deck", [TrapChance, Phase10DeathLink, ScoreThreshold, ScoreTraps]),
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
