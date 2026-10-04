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

#: Spent in the store, which is the one place a check can be bought rather
#: than played for. Progression, not filler: it opens locations.
AP_POINT = "AP Point"

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
    AP_POINT: 72,
}

#: The lowest non-unlock item ID. Phase unlocks must stay clear of it.
FIRST_FIXED_ITEM_ID = 50

#: Check tiers in unlock order; `checks_per_phase` takes a prefix of this list.
#: Ordered most earnable to least, because `checks_per_phase` takes a prefix:
#: lowering it has to drop the hardest tiers, not the easiest. Measured per
#: attempt across all twenty phases, with three opponents and solo:
#:
#:     mean rate      Cleared  Under Par  No Wilds  Went Out
#:       3 opponents      57%        47%       23%       23%
#:       solo             66%        39%       25%       17%
#:     phases under 2%      0          0        0/1       0/8
#:
#: Went Out was second, and solo it is 0% on eight of twenty phases -- the
#: small ones, which leave more cards in hand and fewer groups to hit onto. At
#: the default of two checks that made a fifth of a solo world unreachable.
#: It is also bimodal rather than merely low: 40-79% on phases 15-19. Last is
#: where it belongs.
TIERS = ["Cleared", "Under Par", "No Wilds", "Went Out"]

#: Cumulative "just keep playing" checks. They gate on nothing, which is what
#: gives a seed a workable opening.
HANDS_WON_MILESTONES = [1, 2, 3, 5, 8, 12, 16, 20, 25, 30]

#: What each store slot costs, cheapest first. Ascending on purpose: the gate
#: on slot i is the sum of the i cheapest prices, so whichever order the player
#: buys in, the logic the seed was generated under still holds.
STORE_PRICES = [1, 1, 1, 1, 2, 2, 3, 3]

#: The most slots `store_slots` will offer, and so the length of the ladder.
MAX_STORE_SLOTS = len(STORE_PRICES)

#: Points beyond the ladder's total. Without slack the last slot needs every
#: single point in the seed, which makes it hostage to wherever the last one
#: landed; two is enough to unstick that without making the store free.
STORE_SLACK = 2


#: How the store's slots open, from `store_gating`. Sent to the clients as the
#: word, like `skip_mode`, and a seed that predates the option sends nothing
#: and is a ladder -- which is what it was generated as.
#:
#:   ladder       prices ascend and each slot opens in turn, the first at 1 point
#:   always_open  every slot can be bought from the start, priced by what it
#:                holds: trap or filler 1, useful 2, progression 3
#:   all_at_once  1.5.0 only, and kept so its seeds still play: every slot costs
#:                1 and all open together at the store's total. The option now
#:                maps that word to always_open, so no new seed is generated
#:                with it.
STORE_LADDER = "ladder"
STORE_ALWAYS_OPEN = "always_open"
STORE_ALL_AT_ONCE = "all_at_once"
STORE_GATINGS = (STORE_LADDER, STORE_ALWAYS_OPEN, STORE_ALL_AT_ONCE)
#: The shapes a new seed can be generated with.
STORE_GENERATED_GATINGS = (STORE_LADDER, STORE_ALWAYS_OPEN)

#: What an always-open slot costs, by the classification of the item in it.
#: Highest flag wins: a progression item that is also useful is progression.
PRICE_TRAP_OR_FILLER = 1
PRICE_USEFUL = 2
PRICE_PROGRESSION = 3


def store_prices(slots: int, gating: str = STORE_LADDER) -> list[int]:
    """What the slots cost, as far as generation can know.

    Always open, that is the worst case -- every slot holding progression --
    because the real price depends on what fill puts there, and the pool and
    the logic are both sized before fill runs. The real prices go to the
    clients in slot data once fill has decided them.
    """
    if gating == STORE_ALWAYS_OPEN:
        return [PRICE_PROGRESSION] * slots
    if gating == STORE_ALL_AT_ONCE:
        return [1] * slots
    return STORE_PRICES[:slots]


def price_for(advancement: bool, useful: bool) -> int:
    """An always-open slot's price, from its item's classification."""
    if advancement:
        return PRICE_PROGRESSION
    if useful:
        return PRICE_USEFUL
    return PRICE_TRAP_OR_FILLER


def store_gate(slot: int, slots: int = MAX_STORE_SLOTS,
               gating: str = STORE_LADDER) -> int:
    """Points received before the *logic* counts slot `slot` (1-based) as
    reachable. The access rule, not necessarily when a client lets you buy.

    One invariant behind every shape: a player who has met a slot's gate could
    have paid for every slot they might have bought on the way to it, in any
    order. That is what lets the logic reason about points *received* while
    the player is spending them.

    On the ladder that is the sum of the cheapest `slot` prices rather than
    this slot's own price. All at once, every slot shares one gate, so it has
    to cover the whole store.

    Always open is the exception, and knowingly: three points, enough to buy
    any one slot. A slot's price depends on what fill puts in it, and the rule
    is written before fill, so an exact rule would have to wait for every
    slot's worst case -- and that version failed to generate in 2 of 150 seeds
    at six slots and 90 of 150 at eight. This is the rule Archipelago shops
    use. It does not model spending; what keeps it safe is that the pool
    carries the whole worst case and more, and a player buying in random order
    never got stuck in 750 simulated playthroughs (DEVELOPMENT.md).
    `slots` only matters for the shared gate.
    """
    if gating == STORE_ALWAYS_OPEN:
        return PRICE_PROGRESSION
    if gating == STORE_ALL_AT_ONCE:
        return sum(store_prices(slots, gating))
    return sum(STORE_PRICES[:slot])


#: What the store sells that is not a check: a card, once, now. Bought any
#: number of times while the points last, and gone the moment it is played or
#: discarded -- the point of them is the run where you are three rounds into
#: phase 17 and the deck will not give you a fourth nine.
#:
#: Priced against what the card is worth to be caught holding, which is also
#: what it is worth to hold: a Wild is 25 points of penalty and the most useful
#: card in the deck, a Skip is 15 and buys a turn off whoever is closest to
#: going out.
BUFF_WILD = "One-Use Wild"
BUFF_SKIP = "One-Use Skip"
BUFF_PRICES = {BUFF_WILD: 2, BUFF_SKIP: 1}
BUFFS = [BUFF_WILD, BUFF_SKIP]

#: Points the pool carries beyond the ladder so there is something to spend on
#: them. Trimmed before the slack and before any slot when the pool is tight,
#: so a seed that could only just fit its store still gets the store it got
#: before these existed.
#:
#: Eight rather than four because four was a run's worth of three Wilds, which
#: is not relief -- it is a thing to hoard and agonise over, which is the
#: opposite of the point. Eight buys ten cards at the default store and costs
#: one Skip Card item and three filler; see DEVELOPMENT.md for where the curve
#: turns and why it does not go higher by default.
DEFAULT_BUFF_POINTS = 8


#: DeathLink by round score: every this many points sends one death. Measured
#: at about 32 points a round (a cleared round leaves ~6, a lost one ~60), so
#: 500 is a death every sixteen rounds or so, 100 every three, 1000 every
#: thirty-two.
MIN_SCORE_THRESHOLD = 100
MAX_SCORE_THRESHOLD = 1000
DEFAULT_SCORE_THRESHOLD = 500


def buff_price(buff: str) -> int:
    return BUFF_PRICES[buff]


def store_points(slots: int, buff_points: int = 0,
                 gating: str = STORE_LADDER) -> int:
    """How many points the pool carries for a store of this size."""
    if not slots:
        return 0
    return sum(store_prices(slots, gating)) + STORE_SLACK + buff_points


def store_location_name(slot: int) -> str:
    return f"Store Slot {slot}"


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
    # Milestones occupy 400..409. The store gets its own block rather than
    # extending that one, so growing either list cannot reach the other.
    **{
        store_location_name(slot): 500 + slot
        for slot in range(1, MAX_STORE_SLOTS + 1)
    },
}

#: Baseline deck and deal, before any Archipelago item is applied.
BASE_HAND_SIZE = 10

#: Skips are granted into hand, never shuffled in, so this caps the item count
#: rather than describing the deck.
MAX_SKIPS = 4
