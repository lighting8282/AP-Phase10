"""The bridge between engine state and Archipelago.

Everything here is pure: no sockets, no async, no CommonClient. That is what
makes the interesting parts -- how received items become a GameConfig, and which
location IDs a finished hand is worth -- testable without standing up a server.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..data import (
    OPPONENT_PHASE_MATCH,
    OPPONENT_PHASE_OWN,
    OPPONENT_PHASES,
    DEFAULT_SCORE_THRESHOLD,
    MAX_SCORE_THRESHOLD,
    MIN_SCORE_THRESHOLD,
    AP_POINT,
    BASE_HAND_SIZE,
    BUFF_PRICES,
    BUFF_WILD,
    EXTRA_DRAW,
    HAND_SIZE_UPGRADE,
    HANDS_WON_MILESTONES,
    LEAN_DEAL,
    LOCATION_NAME_TO_ID,
    MAX_SKIPS,
    MAX_STORE_SLOTS,
    MULLIGAN,
    PHASE_COUNT,
    PHASE_LOCK,
    PHASE_UNLOCK,
    SCORE_REDUCTION,
    SCORE_REDUCTION_VALUE,
    SKIP_CARD,
    TIERS,
    WILD_CARD,
    WILD_THEFT,
    buff_price,
    milestone_location_name,
    phase_location_name,
    PRICE_PROGRESSION,
    STORE_ALL_AT_ONCE,
    STORE_ALWAYS_OPEN,
    STORE_GATINGS,
    STORE_LADDER,
    store_gate,
    store_location_name,
    store_prices,
)
from ..game.cards import SKIP, STOCK_WILDS, WILD, Card
from ..game.engine import GameConfig, HandState, PhaseHand, Table
from ..game.opponents import MID, NAMES as OPPONENT_NAMES, build_opponents
from ..game.game import SAVE_VERSION, Phase10Game, RoundResult

#: Traps are one-shot. Received counts only ever grow, so pending effects are
#: tracked as (received - consumed) rather than by mutating the counts.
TRAP_NAMES = (PHASE_LOCK, LEAN_DEAL, WILD_THEFT)

LEAN_DEAL_PENALTY = 2

#: The traps a score threshold sets off, in turn. Both hit the next hand, so the
#: cost lands where the points were earned. Phase Lock is left out: it waits for
#: a later lost hand, which reads as unrelated to the score that caused it.
SCORE_TRAP_CYCLE = (LEAN_DEAL, WILD_THEFT)


def read_score_threshold(slot_data) -> int:
    """The DeathLink threshold, held to the option's range; absent is the default."""
    value = slot_data.get("score_threshold", DEFAULT_SCORE_THRESHOLD)
    if not isinstance(value, int) or isinstance(value, bool):
        return DEFAULT_SCORE_THRESHOLD
    return min(MAX_SCORE_THRESHOLD, max(MIN_SCORE_THRESHOLD, value))


def score_key(team: int, slot: int) -> str:
    """Data Storage key for a slot's public score, which every AP_10 client in
    the room writes and the others read. Separate from the save, which is
    private and large."""
    return f"phase10_score_{team}_{slot}"


def read_score_record(value) -> dict | None:
    """Another player's published score, or None if it is not one.

    Arrives over the network from a client this one does not control, so every
    field is checked rather than trusted.
    """
    if not isinstance(value, dict):
        return None
    fields = ("score", "won", "cleared")
    if not all(isinstance(value.get(f), int) and not isinstance(value.get(f), bool)
               and value.get(f) >= 0 for f in fields):
        return None
    return {f: value[f] for f in fields}


def read_slot_prices(slot_data) -> list[int] | None:
    """The always-open prices from slot data, or None if absent or malformed."""
    prices = slot_data.get("store_prices")
    if not isinstance(prices, list):
        return None
    if not all(isinstance(p, int) and not isinstance(p, bool) and 1 <= p <= PRICE_PROGRESSION
               for p in prices):
        return None
    return list(prices)


@dataclass
class Phase10Session:
    goal: int = 0
    starting_draws: int = 4
    checks_per_phase: int = 4
    death_link: bool = False
    #: Every this many points of round score sends one DeathLink death.
    score_threshold: int = DEFAULT_SCORE_THRESHOLD
    #: How many of those thresholds are already accounted for -- sent, or
    #: absorbed by a hand an incoming death took. A high-water mark, saved,
    #: so a reconnect or a switch of client never sends one twice.
    score_marks: int = 0
    #: Whether passing a threshold also sets off one of your own traps.
    score_traps: bool = False
    #: How many score traps have gone off. Saved; which trap each was is
    #: the cycle below, so the count is all either client needs.
    score_traps_fired: int = 0
    #: The trap the last threshold set off, for the clients to announce.
    last_score_trap: str | None = None
    opponents: int = 3
    #: "match": the seats play your phase every round. "own": each climbs its
    #: own from Phase 1. Absent from slot data reads as own, which is what a
    #: seed from before the option was played as, and free play is own.
    opponent_phase: str = OPPONENT_PHASE_OWN
    store_slots: int = 0
    #: "ladder" or "all_at_once". A seed from before the option sends
    #: nothing and reads as the ladder, which is what it was generated as --
    #: reading it any other way would gate slots the server does not.
    store_gating: str = STORE_LADDER
    #: Always open only: what each slot costs, decided by the world after fill
    #: from the item in it. None for the other shapes, whose prices are fixed.
    slot_prices: list[int] | None = None
    #: "dig" or "deny". Only the free-play client sends the latter; an
    #: Archipelago seed never does, because its access rules are built on the
    #: dig's measured numbers.
    skip_mode: str = "dig"
    #: Skips shuffled into the draw pile, so everybody at the table is dealt
    #: from the same deck. Free play sends the four the box has; a seed sends
    #: none and grants Skips as items instead, because a shuffled Skip turns
    #: up too rarely to repay the density it costs every other draw -- which
    #: is a statement about an item's worth, not about how the game is dealt.
    skips_in_deck: int = 0
    #: How many phases this run climbs. A free-play run is ten or twenty by
    #: the player's choice; a seed is always the full set, because its
    #: locations exist for every phase.
    phase_cap: int = PHASE_COUNT
    phases_to_win: int = PHASE_COUNT
    #: Whether finishing the last phase ends the run for everybody, which is
    #: the printed game. A seed has its own goal instead and must not be
    #: ended by a seat -- an opponent finishing is not an Archipelago notion.
    race_to_end: bool = False

    items: Counter = field(default_factory=Counter)
    consumed_traps: Counter = field(default_factory=Counter)
    mulligans_used: int = 0
    #: Which store slots have been bought, so what has been spent is derived
    #: rather than stored twice and left to disagree with itself.
    bought_slots: set[int] = field(default_factory=set)
    #: How many of each one-use card have been bought, so what has been spent
    #: on them is derived rather than stored twice and left to disagree.
    buffs_bought: dict[str, int] = field(default_factory=dict)
    _opponent_phases: list[int] = field(default_factory=list)
    _opponent_scores: list[int] = field(default_factory=list)
    checked_locations: set[int] = field(default_factory=set)
    locked_phase: int | None = None
    last_result: RoundResult | None = None
    #: The table the current hand is being played at, opponents included.
    table: Table | None = None
    game: Phase10Game = field(default_factory=Phase10Game)

    @classmethod
    def from_slot_data(cls, slot_data: Mapping[str, Any], rng=None) -> Phase10Session:
        return cls(
            goal=int(slot_data.get("goal", 0)),
            starting_draws=int(slot_data.get("starting_draws", 4)),
            checks_per_phase=int(slot_data.get("checks_per_phase", 4)),
            death_link=bool(slot_data.get("death_link", False)),
            score_threshold=read_score_threshold(slot_data),
            score_traps=bool(slot_data.get("score_traps", False)),
            opponents=int(slot_data.get("opponents", 3)),
            opponent_phase=(slot_data.get("opponent_phase")
                            if slot_data.get("opponent_phase") in OPPONENT_PHASES
                            else OPPONENT_PHASE_OWN),
            store_slots=int(slot_data.get("store_slots", 0)),
            store_gating=(slot_data.get("store_gating")
                          if slot_data.get("store_gating") in STORE_GATINGS
                          else STORE_LADDER),
            slot_prices=read_slot_prices(slot_data),
            # Absent in seeds generated before the option existed, where the
            # world's own rule asked for every phase.
            phases_to_win=int(slot_data.get("phases_to_win", PHASE_COUNT)),
            skip_mode="deny" if slot_data.get("skip_mode") == "deny" else "dig",
            skips_in_deck=int(slot_data.get("skips_in_deck", 0)),
            race_to_end=bool(slot_data.get("race_to_end", False)),
            game=Phase10Game(rng),
        )

    # The game owns the running state; the session keeps one source of truth
    # rather than a second tally that could drift from the scorecard.
    @property
    def hand(self) -> PhaseHand | None:
        return self.game.hand

    @property
    def hands_won(self) -> int:
        return self.game.rounds_won

    @property
    def cleared_phases(self) -> set[int]:
        return self.game.cleared_phases

    @property
    def score_reduction(self) -> int:
        """Points Score Reduction items have taken off the running total."""
        return self.items[SCORE_REDUCTION] * SCORE_REDUCTION_VALUE

    @property
    def total_score(self) -> int:
        """The score as the player is judged on it: raw, less reductions.

        Floored at zero. The scorecard still shows what each round actually
        cost -- a reduction forgives points, it does not rewrite history.
        """
        return max(0, self.game.total_score - self.score_reduction)

    # -- DeathLink by score -------------------------------------------------
    @property
    def next_score_mark(self) -> int:
        """The total score at which the next death goes out."""
        return (self.score_marks + 1) * self.score_threshold

    def score_mark_due(self, *, absorb: bool = False) -> int | None:
        """Whether the score has crossed a new threshold; marks it handled.

        Returns the threshold reached -- 500, 1000 -- when a death should go
        out now, else None. At most one per call, which is one per round: a
        round that jumps two thresholds at a low setting sends one, not a
        burst. `absorb` marks the threshold without sending, for a hand an
        incoming death ended -- otherwise two linked players could bounce
        deaths back and forth for as long as each loss crossed a line.

        The mark is a high-water one. Score Reduction lowers the total, so the
        next death needs those points earned back before it goes out.
        """
        self.last_score_trap = None
        crossed = self.total_score // self.score_threshold
        if crossed <= self.score_marks:
            return None
        self.score_marks = crossed
        if absorb:
            return None
        if self.score_traps:
            self.last_score_trap = SCORE_TRAP_CYCLE[self.score_traps_fired % len(SCORE_TRAP_CYCLE)]
            self.score_traps_fired += 1
        return crossed * self.score_threshold

    # -- the public score ---------------------------------------------------
    def score_record(self) -> dict:
        """What the other AP_10 players see of this run."""
        return {"score": self.total_score, "won": self.hands_won,
                "cleared": len(self.cleared_phases)}

    # -- items -------------------------------------------------------------
    def set_items(self, item_names: list[str]) -> None:
        """Replace the received-item tally. AP resends the full list, so this
        is idempotent rather than incremental."""
        self.items = Counter(item_names)

    def pending(self, trap: str) -> int:
        return max(0, self.trap_count(trap) - self.consumed_traps[trap])

    def trap_count(self, trap: str) -> int:
        """Traps of this kind received, plus those your score set off."""
        if trap not in SCORE_TRAP_CYCLE:
            return self.items[trap]
        turn = SCORE_TRAP_CYCLE.index(trap)
        fired = (self.score_traps_fired - turn + len(SCORE_TRAP_CYCLE) - 1) // len(SCORE_TRAP_CYCLE)
        return self.items[trap] + max(0, fired)

    @property
    def unlocked_phases(self) -> set[int]:
        return {p for p in range(1, PHASE_COUNT + 1) if self.items[PHASE_UNLOCK.format(p)]}

    # -- configuration -----------------------------------------------------
    @property
    def config(self) -> GameConfig:
        """Build the engine's knobs from what Archipelago has handed over."""
        hand_size = BASE_HAND_SIZE + self.items[HAND_SIZE_UPGRADE]
        wilds = min(self.items[WILD_CARD], STOCK_WILDS)
        draws = self.starting_draws + self.items[EXTRA_DRAW]

        if self.pending(LEAN_DEAL):
            hand_size -= LEAN_DEAL_PENALTY
        if self.pending(WILD_THEFT):
            wilds -= 1

        return GameConfig(
            hand_size=max(4, hand_size),
            wilds_in_deck=max(0, min(wilds, STOCK_WILDS)),
            # Zero starting draws means no budget at all, which only free
            # play asks for: the Archipelago option starts at 2.
            max_draws=0 if self.starting_draws <= 0 else max(1, draws),
            starting_skips=min(self.items[SKIP_CARD], MAX_SKIPS),
            skips_in_deck=self.skips_in_deck,
            skip_mode=self.skip_mode,
        )

    # -- playing -----------------------------------------------------------
    def seat_finished(self, index: int) -> bool:
        """Whether a seat has finished the last phase of the run."""
        phases = self.opponent_phases
        return index < len(phases) and phases[index] > self.phase_cap

    @property
    def player_finished(self) -> bool:
        """Whether you have."""
        return self.phase_cap in self.cleared_phases

    @property
    def run_over(self) -> bool:
        """Whether the run is over, which only the printed game decides so.

        Derived rather than stored, like the unlocks and the cleared set: the
        seat phases and the scorecard are both saved already, so a reloaded
        run knows it is finished without a save format to disagree with it.
        """
        if not self.race_to_end:
            return False
        if self.player_finished:
            return True
        return any(self.seat_finished(i) for i in range(len(self.opponent_phases)))

    @property
    def run_winner(self):
        """Who won, and by what.

        Everybody who finished the last phase is a finisher -- more than one
        can, in the round that ends the run -- and the lowest score among them
        wins, which is how the box breaks it. A tie on score goes to you, then
        round the table, because somebody has to be named.
        """
        if not self.run_over:
            return None
        finishers = []
        if self.player_finished:
            finishers.append(("You", self.total_score))
        for i in range(len(self.opponent_phases)):
            if self.seat_finished(i):
                finishers.append((self.seat_name(i), self.opponent_scores[i]))
        if not finishers:
            return None
        return min(finishers, key=lambda who: who[1])

    def seat_name(self, index: int) -> str:
        """What a seat is called, whether or not a table is dealt right now."""
        if index < len(self.seats):
            return self.seats[index].name
        if index < len(OPPONENT_NAMES):
            return OPPONENT_NAMES[index]
        return f"Seat {index + 1}"

    def can_play(self, phase: int) -> str | None:
        """Returns None if the phase is playable, else why not."""
        if self.run_over:
            won = self.run_winner
            if won and won[0] == "You":
                return "You won the run -- start a new one when you like."
            who = won[0] if won else "Somebody"
            return (f"{who} finished the last phase. "
                    "The run is over -- start a new one when you like.")
        if phase not in self.unlocked_phases:
            return f"Phase {phase} is not unlocked yet."
        if self.locked_phase is not None and phase != self.locked_phase:
            return f"A Phase Lock trap is forcing you to replay Phase {self.locked_phase}."
        return None

    # -- the table ---------------------------------------------------------
    @property
    def opponent_phases(self) -> list[int]:
        """Which phase each seat is on. Grows as they clear their own."""
        if not self._opponent_phases:
            self._opponent_phases = [1] * self.opponents
        return self._opponent_phases

    @property
    def opponent_scores(self) -> list[int]:
        """Each seat's running total, the way the pad on the table works.

        Kept on the session rather than on the seat because the seats are
        rebuilt from scratch every round, exactly like `opponent_phases`.
        """
        if not self._opponent_scores:
            self._opponent_scores = [0] * self.opponents
        return self._opponent_scores

    @property
    def seats(self) -> list:
        return self.table.seats if self.table else []

    def seat_phases(self, phase: int) -> list[int]:
        """The phase each seat plays this round: yours when they match it,
        their own otherwise."""
        if self.opponent_phase == OPPONENT_PHASE_MATCH:
            return [phase] * self.opponents
        return list(self.opponent_phases)

    def advance_opponents(self) -> list[str]:
        """Move every seat that cleared its phase on to the next one.

        Not when they match your phase: then they have no phase of their own to
        climb, and moving one would only change a number nobody plays.
        """
        moved = []
        if self.opponent_phase == OPPONENT_PHASE_MATCH:
            return moved
        for index, seat in enumerate(self.seats):
            if seat.laid_down and index < len(self.opponent_phases):
                # One past the cap in a race, and no further. That is not a
                # phase anybody plays: it is how a seat records that it
                # finished the last one, the same way your cleared set records
                # that you did. It used to stop at PHASE_COUNT whatever the
                # run's cap was, so a ten-phase run had seats climbing to 16.
                #
                # Without a race there is nothing to finish, so a seat stops
                # *on* the last phase -- a seed showing "phase 21" would be a
                # marker for an event that mode does not have.
                ceiling = self.phase_cap + (1 if self.race_to_end else 0)
                self._opponent_phases[index] = min(ceiling, seat.phase + 1)
                moved.append(seat.name)
        return moved

    def tally_opponents(self) -> None:
        """Score every seat on what it is caught holding.

        Must run before the round is finished, while the seats still hold the
        hands they ended with. Lower is better here as it is for you: the seat
        that went out scores nothing, and the one still sitting on a Wild pays
        twenty-five for it.
        """
        scores = self.opponent_scores
        for index, seat in enumerate(self.seats):
            if index < len(scores):
                scores[index] += seat.score

    # -- the store ---------------------------------------------------------
    # Points arrive as items and buy a check outright. The seed priced each
    # slot at generation, and the gate on a slot is the sum of the cheapest
    # prices up to it -- so holding enough to reach a slot's gate means you
    # could have bought the cheaper ones instead, and any order is legal.
    @property
    def points(self) -> int:
        """Points received. Never goes down; spending is tracked separately."""
        return self.items[AP_POINT]

    @property
    def points_spent(self) -> int:
        """AP Points spent: slots, and whatever cards the earned points did
        not cover."""
        bought = sum(self.store_price(slot)
                     for slot in self.bought_slots
                     if 1 <= slot <= self.store_slots)
        return bought + max(0, self.buff_points_spent - self.card_points_earned)

    @property
    def card_points_earned(self) -> int:
        """One per round you went out in -- shed your whole hand.

        Spending money for the one-use cards only: they cannot buy a slot, so
        they cannot change what the logic expects. Derived from the scorecard
        rather than saved, so both clients agree by construction. Going out
        rather than a low score, because at or under ten points is nearly
        every other round (45%) and going out is about one in five.
        """
        return sum(1 for r in self.game.rounds if r.state is HandState.WENT_OUT)

    @property
    def buff_points_spent(self) -> int:
        return sum(buff_price(name) * count
                   for name, count in self.buffs_bought.items())

    @property
    def points_reserved(self) -> int:
        """What the slots you have not bought still cost.

        The one thing spending must never do is strand a location the seed was
        generated as reachable. Archipelago's logic cannot model a currency
        being spent -- it reasons about points *received* -- so the client is
        where that has to hold, and it holds by keeping the slots' own prices
        out of what a buff is allowed to touch.
        """
        return sum(self.store_price(slot)
                   for slot in range(1, self.store_slots + 1)
                   if slot not in self.bought_slots)

    @property
    def buff_points_left(self) -> int:
        """Points you may spend on a card rather than a check: earned points
        not yet spent, plus AP Points beyond what the unbought slots owe."""
        earned_left = max(0, self.card_points_earned - self.buff_points_spent)
        return earned_left + max(0, self.points_left - self.points_reserved)

    @property
    def points_left(self) -> int:
        return max(0, self.points - self.points_spent)

    def store_price(self, slot: int) -> int:
        if self.store_gating == STORE_ALWAYS_OPEN:
            # Missing or malformed prices charge the worst case. Overcharging
            # can only cost spending money: the pool carries three a slot.
            prices = self.slot_prices or []
            if len(prices) == self.store_slots:
                return prices[slot - 1]
            return PRICE_PROGRESSION
        return store_prices(self.store_slots, self.store_gating)[slot - 1]

    def store_gate(self, slot: int) -> int:
        """Points received before `slot` may be bought, for this seed's shape.

        Always open, none. The logic waits for the whole store's worst case
        before it counts a slot reachable, but buying sooner is out of logic,
        not out of bounds, and a slot bought costs exactly what it releases
        from the reserve -- so it can never strand another.
        """
        if self.store_gating == STORE_ALWAYS_OPEN:
            return 0
        return store_gate(slot, self.store_slots, self.store_gating)

    def can_buy(self, slot: int) -> str | None:
        """Returns None if the slot is buyable right now, else why not."""
        if not self.store_slots:
            return "This seed has no store."
        if not 1 <= slot <= self.store_slots:
            return f"The store has slots 1 to {self.store_slots}."
        if slot in self.bought_slots:
            return f"Slot {slot} is already bought."
        gate = self.store_gate(slot)
        if self.points < gate:
            # The gate is on points received, not points left: it is what the
            # seed's logic was built on, so checking it here is what keeps the
            # client from reporting a location the server thinks is unreachable.
            return f"Slot {slot} opens at {gate} points received; you have {self.points}."
        price = self.store_price(slot)
        # Unreachable while the prices ascend: any set of slots whose gates you
        # have met costs at most the largest of those gates, which you have.
        # Kept because it is what would catch a ladder that stopped ascending,
        # and the tests pin the invariant rather than this branch.
        if self.points_left < price:
            return f"Slot {slot} costs {price}; you have {self.points_left} unspent."
        return None

    def buy_slot(self, slot: int) -> int:
        """Buy a slot. Returns the location ID to check."""
        refusal = self.can_buy(slot)
        if refusal:
            raise RuntimeError(refusal)
        self.bought_slots.add(slot)
        return LOCATION_NAME_TO_ID[store_location_name(slot)]

    # -- one-use cards -----------------------------------------------------
    # The other half of the store: a card, once, now. Bought any number of
    # times while the points last, and gone the moment it is played or
    # discarded. They are here for the run where you are three rounds into
    # phase 17 and the deck will not give you a fourth nine.

    def can_buy_buff(self, buff: str) -> str | None:
        """Returns None if the buff is buyable right now, else why not."""
        if buff not in BUFF_PRICES:
            return f"The store does not sell {buff!r}."
        if not self.store_slots:
            return "This seed has no store."
        hand = self.hand
        if hand is None or hand.state is not HandState.IN_PROGRESS:
            return "A one-use card is bought into a hand; start a round first."
        if hand.dig_pending or hand.deny_pending:
            return "Finish the move you are in first."
        price = buff_price(buff)
        if self.buff_points_left < price:
            reserved = self.points_reserved
            if reserved and self.points_left >= price:
                # Spelled out rather than refused flatly: the points are there,
                # they are just the ones the remaining checks are owed.
                return (f"{buff} costs {price}; {self.points_left} unspent, "
                        f"but {reserved} of those are held for the "
                        f"{self.slots_left} slot(s) you have not bought.")
            return f"{buff} costs {price}; you have {self.buff_points_left} to spend."
        return None

    @property
    def slots_left(self) -> int:
        return sum(1 for slot in range(1, self.store_slots + 1)
                   if slot not in self.bought_slots)

    def buy_buff(self, buff: str) -> Card:
        """Buy a one-use card. It lands in your hand, and it is yours to lose."""
        refusal = self.can_buy_buff(buff)
        if refusal:
            raise RuntimeError(refusal)
        self.buffs_bought[buff] = self.buffs_bought.get(buff, 0) + 1
        return self.hand.take_bought_card(WILD if buff == BUFF_WILD else SKIP)

    # -- mulligans ---------------------------------------------------------
    @property
    def mulligans_left(self) -> int:
        return max(0, self.items[MULLIGAN] - self.mulligans_used)

    def can_mulligan(self) -> str | None:
        """Returns None if a Mulligan is usable right now, else why not."""
        if not self.mulligans_left:
            return "No Mulligans left."
        hand = self.hand
        if hand is None or hand.state is not HandState.IN_PROGRESS:
            return "No hand in progress."
        if hand.draws_used or hand.drew_this_turn:
            return "A Mulligan only works before your first draw."
        if hand.dig_pending:
            return "Finish the dig first."
        if hand.skips_played:
            return "A Mulligan only works before you play a Skip."
        return None

    def use_mulligan(self) -> PhaseHand:
        """Spend a Mulligan on the current hand and return it, redealt."""
        refusal = self.can_mulligan()
        if refusal:
            raise ValueError(refusal)
        hand = self.hand
        hand.redeal()
        self.mulligans_used += 1
        return hand

    def start_hand(self, phase: int) -> PhaseHand:
        refusal = self.can_play(phase)
        if refusal:
            raise ValueError(refusal)

        config = self.config
        # Consume the one-shot traps that shaped this hand.
        for trap in (LEAN_DEAL, WILD_THEFT):
            if self.pending(trap):
                self.consumed_traps[trap] += 1

        self.table = Table()
        if self.opponents:
            # On your phase when they match it -- the default for a seed, so
            # a round's difficulty is the phase you chose. Otherwise each seat
            # carries its own phase between rounds, which in free play is the
            # race.
            self.table.seats = build_opponents(
                self.opponents, self.seat_phases(phase),
                config, self.game.rng, MID,
            )
        return self.game.start_round(phase, config, table=self.table)

    def kill_hand(self) -> PhaseHand | None:
        """Fail the hand in progress, if there is one.

        A card game has nothing to kill, so a DeathLink death is a lost hand.
        Between rounds there is nothing to lose and an incoming death passes
        harmlessly -- returning None says so, rather than inventing a penalty
        the player cannot see coming.
        """
        hand = self.hand
        if hand is None or hand.state is not HandState.IN_PROGRESS:
            return None
        hand.mark_failed("death_link")
        return hand

    def earned_tiers(self, hand: PhaseHand) -> list[str]:
        """Which check tiers a finished hand is worth."""
        if hand.state not in (HandState.PHASE_LAID, HandState.WENT_OUT):
            return []

        # Measured at the lay-down, not at the end of the round: the round
        # carries on afterwards so the rest of the hand can be shed, and
        # counting those draws would make Under Par unearnable.
        spent = hand.draws_at_lay_down
        if spent is None:
            spent = hand.draws_used

        earned = {"Cleared"}
        if hand.state is HandState.WENT_OUT:
            earned.add("Went Out")
        if hand.used_wilds_in_layout == 0:
            earned.add("No Wilds")
        if spent <= max(1, hand.config.max_draws // 2):
            earned.add("Under Par")

        # Walk TIERS rather than the order they were collected in, so the
        # result follows the table and a reorder reaches here for free.
        # `checks_per_phase` takes a prefix: tiers past it have no location on
        # the server, so reporting one would check an ID that does not exist.
        return [tier for tier in TIERS[: self.checks_per_phase] if tier in earned]

    def finish_hand(self, hand: PhaseHand) -> list[int]:
        """Settle a finished hand. Returns newly checked location IDs."""
        tiers = self.earned_tiers(hand)
        # Both read the seats as they ended the round, so they come before
        # the round is finished and the table is torn down.
        self.tally_opponents()
        self.advance_opponents()
        result = self.game.finish_round(hand)
        self.last_result = result

        names: list[str] = []
        if result.cleared:
            self.locked_phase = None
            names += [phase_location_name(result.phase, tier) for tier in tiers]
            names += [
                milestone_location_name(n)
                for n in HANDS_WON_MILESTONES
                if n <= self.hands_won
            ]
        elif self.pending(PHASE_LOCK):
            # A failed hand under a Phase Lock pins you to this phase.
            self.consumed_traps[PHASE_LOCK] += 1
            self.locked_phase = result.phase

        new = [
            LOCATION_NAME_TO_ID[name]
            for name in names
            if LOCATION_NAME_TO_ID[name] not in self.checked_locations
        ]
        self.checked_locations.update(new)
        return new

    # -- persistence -------------------------------------------------------
    def to_payload(self) -> dict:
        """Everything the server does not already know.

        Checked locations are deliberately left out: the server is the
        authority on those, and writing our own copy back would only create
        something that could disagree with it.
        """
        return {
            "version": SAVE_VERSION,
            "game": self.game.to_payload(),
            "consumed_traps": {k: int(v) for k, v in self.consumed_traps.items() if v},
            "mulligans_used": self.mulligans_used,
            "opponent_phases": list(self._opponent_phases),
            "opponent_scores": list(self._opponent_scores),
            "bought_slots": sorted(self.bought_slots),
            # Saved, or a reconnect would hand the points back and the one-use
            # cards would be free to anybody willing to restart the client.
            "buffs_bought": dict(self.buffs_bought),
            "locked_phase": self.locked_phase,
            "score_marks": self.score_marks,
            "score_traps_fired": self.score_traps_fired,
        }

    def load_payload(self, payload: object) -> bool:
        """Restore from a saved payload. Returns whether it took.

        Treated as untrusted input -- it arrives over the network and a partial
        restore would be worse than none.
        """
        if not isinstance(payload, dict) or payload.get("version") != SAVE_VERSION:
            return False
        if not self.game.load_payload(payload.get("game")):
            return False

        traps = payload.get("consumed_traps")
        if isinstance(traps, dict):
            try:
                self.consumed_traps = Counter(
                    {str(k): int(v) for k, v in traps.items()}
                )
            except (TypeError, ValueError):
                self.consumed_traps = Counter()

        # Absent in saves written before Mulligans did anything, so a missing
        # key restores as zero rather than refusing the whole payload.
        used = payload.get("mulligans_used")
        self.mulligans_used = used if isinstance(used, int) and used >= 0 else 0

        phases = payload.get("opponent_phases")
        if isinstance(phases, list) and all(
            isinstance(v, int) and 1 <= v <= PHASE_COUNT for v in phases
        ):
            self._opponent_phases = list(phases)

        # Absent in saves written before the seats kept score, so a missing
        # key restores as zero rather than refusing the whole payload.
        scores = payload.get("opponent_scores")
        if isinstance(scores, list) and all(
            isinstance(v, int) and v >= 0 for v in scores
        ):
            self._opponent_scores = list(scores)

        # Absent in saves written before the store existed, so a missing key
        # restores as nothing bought rather than refusing the whole payload.
        bought = payload.get("bought_slots")
        if isinstance(bought, list) and all(
            isinstance(v, int) and 1 <= v <= MAX_STORE_SLOTS for v in bought
        ):
            self.bought_slots = set(bought)

        # Same, one version later. A name the store does not sell is dropped
        # rather than trusted: this arrives over the network like the rest.
        buffs = payload.get("buffs_bought")
        if isinstance(buffs, dict):
            self.buffs_bought = {
                name: count for name, count in buffs.items()
                if name in BUFF_PRICES and isinstance(count, int) and count >= 0
            }

        # Absent in saves written before deaths were sent by score. Caught up
        # rather than zeroed: a run already at 1200 points should not send a
        # surprise death the first round after the update.
        sent = payload.get("score_marks")
        if isinstance(sent, int) and not isinstance(sent, bool) and sent >= 0:
            self.score_marks = sent
        else:
            self.score_marks = self.total_score // self.score_threshold

        fired = payload.get("score_traps_fired")
        self.score_traps_fired = (fired if isinstance(fired, int) and not isinstance(fired, bool)
                                  and fired >= 0 else 0)

        locked = payload.get("locked_phase")
        self.locked_phase = (
            locked if isinstance(locked, int) and 1 <= locked <= PHASE_COUNT else None
        )
        return True

    # -- goal --------------------------------------------------------------
    @property
    def goal_met(self) -> bool:
        """Whether this slot is finished, by the seed's own reckoning.

        Counted against `phases_to_win` and against the *named* phases, not
        against a total. Two bugs lived here. The count was ten while the
        world's completion rule asked for every one of twenty, so a client
        declared victory at half the seed and the server believed it -- the
        number was written when there were ten phases and never moved when the
        other ten arrived. And a total would let any ten phases stand in for
        the first ten, which is not what `HasAll(Phase 1..N Clear)` says.
        """
        if self.goal == 1:  # phase_ten
            return 10 in self.cleared_phases
        return all(phase in self.cleared_phases
                   for phase in range(1, self.phases_to_win + 1))
