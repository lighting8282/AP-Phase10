"""Headless solo Phase 10 engine.

Solo play replaces the multiplayer race-to-go-out with pressure from the draw
pile: you get a bounded number of draws to lay your phase down. That removes
the need for opponent AI entirely, and makes every AP item that adds wilds or
draws directly, measurably valuable.

Skips have no opponent to skip, so they dig instead: play one to see the top
of the stock and keep a card of your choice. That trades the game's only dead
weight for selection, which is the resource a solo player actually lacks --
Extra Draw already sells volume.

The engine is pure -- no I/O, no UI, no Archipelago imports. A client drives it
turn by turn and reads `events` to decide which locations to check.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from functools import lru_cache
from enum import Enum

from .cards import SKIP, WILD, Card, Color, hand_score, number_card, shuffled_deck
from .phases import (
    PHASES, GroupKind, GroupSpec, Layout, Meld, PhaseSpec, phase_card_count,
    solve_melds, solve_phase,
)


#: How deep into the stock a played Skip lets you look.
SKIP_DIG_DEPTH = 3


class HandState(Enum):
    IN_PROGRESS = "in_progress"
    PHASE_LAID = "phase_laid"
    WENT_OUT = "went_out"
    FAILED = "failed"


@dataclass(frozen=True)
class GameConfig:
    """Everything Archipelago items are allowed to move."""

    hand_size: int = 10           # "Hand Size +1" items
    wilds_in_deck: int = 8        # "Wild Card" items
    #: Draws allowed per hand. Zero or less means no budget at all, which
    #: is how the printed game plays: the round ends when somebody goes
    #: out, not when a clock runs down. Archipelago never sets it there --
    #: `starting_draws` starts at 2 -- so this is the free-play path.
    max_draws: int = 20           # "Extra Draw" items
    starting_skips: int = 0       # "Skip Card" items

    #: Skips shuffled into the draw pile, for fidelity to the physical deck.
    #: Measured as a straight loss -- they turn up 0.34 times per hand, too
    #: rarely to repay the density they cost every other draw -- so Archipelago
    #: grants Skips via `starting_skips` instead and leaves this at zero.
    skips_in_deck: int = 0
    min_naturals_per_group: int = 1
    allow_discard_draw: bool = True


@dataclass
class HandEvent:
    kind: str
    phase: int
    detail: dict = field(default_factory=dict)


class Table:
    """The stock and the discard pile: what every seat shares.

    Split out of PhaseHand so opponents can draw from the same deck the player
    is drawing from. With no opponents a hand builds its own private Table and
    behaves exactly as it did when it owned these two lists outright -- which
    is what lets the solo measurements stand as a regression guard.
    """

    def __init__(self) -> None:
        self.stock: list[Card] = []
        self.discard: list[Card] = []
        self.seats: list = []
        #: The seat that went out, once one has. Sticky: the round is over,
        #: and a player who keeps acting must keep losing it rather than
        #: slipping through because the transition already happened.
        self.winner = None

    def reset(self, stock: list[Card], discard: list[Card]) -> None:
        self.stock = stock
        self.discard = discard
        self.winner = None

    def deal(self, count: int) -> list[Card]:
        """Take `count` cards off the stock for a seat."""
        dealt = self.stock[:count]
        del self.stock[:count]
        return dealt

    def deal_seats(self, count: int) -> None:
        """Deal every opponent an opening hand off the same deck."""
        for seat in self.seats:
            seat.hand = self.deal(count)
            seat.layout = []
            seat.laid_down = False
            seat.went_out = False

    @property
    def discard_top(self) -> Card | None:
        return self.discard[-1] if self.discard else None

    def all_melds(self) -> list:
        """Every group face up on the table, in seat order.

        Phase 10 lets a hit land on anybody's group, not just your own, so
        targeting has to see the whole table rather than one seat.
        """
        melds = []
        for seat in self.seats:
            melds.extend(seat.melds)
        return melds

    def end_of_turn(self) -> object | None:
        """Run every opponent's turn. Returns the seat that went out, if any.

        Once somebody is out nobody plays on: the round ended, and further
        turns would let a player who drew again quietly survive a race they
        had already lost.
        """
        if self.winner is not None:
            return self.winner
        for seat in self.seats:
            if seat.take_turn(self):
                self.winner = seat
                return seat
        return None


class PhaseHand:
    """One round: a single attempt at a single phase."""

    def __init__(self, phase: int, config: GameConfig, rng: random.Random,
                 spec: PhaseSpec | None = None, table: Table | None = None):
        self.phase = phase
        self.spec = spec if spec is not None else PHASES[phase]
        self.config = config
        self.rng = rng

        self.hand: list[Card] = []
        #: Shared with the opponents when there are any; private otherwise.
        self.table = table if table is not None else Table()
        self._deal()

        self.draws_used = 0
        self.state = HandState.IN_PROGRESS
        self.layout: Layout | None = None
        #: The player's own groups on the table, with what each one means, so
        #: cards can be hit onto them as well as onto the opponents'.
        self.melds: list[Meld] = []
        #: Phase is on the table. Separate from `state`, which stays
        #: IN_PROGRESS so the round can continue into shedding.
        self.laid = False
        self.hits = 0
        #: Draws spent at the moment the phase went down. "Under Par" asks how
        #: fast you cleared, not how long the round then ran -- and the round
        #: now runs on past the lay-down, burning the rest of the budget to
        #: shed, which would leave that tier unearnable on an easy phase.
        self.draws_at_lay_down: int | None = None
        self.events: list[HandEvent] = []
        self.drew_this_turn = False
        self.used_wilds_in_layout = 0
        self.skips_played = 0
        self.dig_options: list[Card] | None = None

    def _deal(self) -> None:
        """Shuffle and deal. Shared by the opening deal and a Mulligan, so the
        two cannot drift into dealing subtly different tables."""
        deck = shuffled_deck(self.rng, self.config.wilds_in_deck,
                             self.config.skips_in_deck)
        self.hand = deck[: self.config.hand_size]
        # Granted Skips are dealt on top of the hand rather than out of it, so
        # holding them costs no room to build the phase in.
        self.hand += [SKIP] * self.config.starting_skips
        rest = deck[self.config.hand_size:]
        self.table.reset(stock=rest[1:], discard=[rest[0]])
        # Opponents are dealt from the same deck, so a Mulligan before anyone
        # has acted redeals the whole table -- which is what a reshuffle means.
        self.table.deal_seats(self.config.hand_size)

    def redeal(self) -> None:
        """Throw the opening hand back and deal a fresh one -- a Mulligan.

        Deliberately restricted to before the first draw. A reroll available at
        any point is a far stronger item than a bad-opening insurance policy,
        and it would invalidate the measured clear rates the access rules are
        built on. Costs no draw: the point is to undo a dead deal, not to pay
        for it out of the same budget that the deal already ruined.
        """
        if self.state is not HandState.IN_PROGRESS:
            raise RuntimeError(f"hand is {self.state.value}")
        if self.draws_used or self.drew_this_turn:
            raise RuntimeError("a Mulligan only works before your first draw")
        if self.dig_pending:
            raise RuntimeError("finish the dig first")
        if self.skips_played:
            raise RuntimeError("a Mulligan only works before you play a Skip")
        self._deal()
        self._emit("redeal", hand=len(self.hand))

    # -- queries -----------------------------------------------------------
    @property
    def stock(self) -> list[Card]:
        return self.table.stock

    @property
    def discard(self) -> list[Card]:
        return self.table.discard

    @property
    def draws_left(self) -> int | None:
        """Draws remaining, or None when there is no budget.

        None rather than a large number, so a caller that forgets to handle
        the unlimited case fails loudly instead of quietly comparing against
        something arbitrary.
        """
        if self.unlimited_draws:
            return None
        return max(0, self.config.max_draws - self.draws_used)

    @property
    def unlimited_draws(self) -> bool:
        return self.config.max_draws <= 0

    @property
    def discard_top(self) -> Card | None:
        return self.discard[-1] if self.discard else None

    @property
    def dig_pending(self) -> bool:
        return self.dig_options is not None

    @property
    def skips_in_hand(self) -> int:
        return sum(1 for c in self.hand if c.is_skip)

    def solution(self) -> Layout | None:
        return solve_phase(self.hand, self.spec,
                           min_naturals_per_group=self.config.min_naturals_per_group)

    def can_lay_down(self) -> bool:
        return self.solution() is not None

    # -- actions -----------------------------------------------------------
    def draw(self, from_discard: bool = False) -> Card:
        if self.state is not HandState.IN_PROGRESS:
            raise RuntimeError(f"hand is {self.state.value}")
        if self.drew_this_turn:
            raise RuntimeError("already drew this turn; discard first")
        if from_discard:
            if not self.config.allow_discard_draw or not self.discard:
                raise RuntimeError("cannot draw from discard")
            card = self.discard.pop()
        else:
            if not self.stock:
                self._refill_stock()
            if not self.stock:
                self.mark_failed("stock_empty")
                raise RuntimeError("stock is empty")
            card = self.stock.pop(0)
        self.hand.append(card)
        self.draws_used += 1
        self.drew_this_turn = True
        return card

    def _refill_stock(self) -> None:
        """Turn the discard pile back into a stock, the way the box says.

        Without a draw budget a long round drains the stock, and the engine
        treated that as a lost hand -- a way to lose that is in no version of
        the rules. The top card stays face up; the rest is shuffled back.

        With a budget this is unreachable in practice (four players at eight
        draws take 32 of about 60 cards), so it changes no measured rate.
        """
        if len(self.discard) <= 1:
            return
        top = self.discard.pop()
        self.table.stock.extend(self.discard)
        self.discard.clear()
        self.discard.append(top)
        self.rng.shuffle(self.table.stock)
        self._emit("stock_refilled", cards=len(self.table.stock))

    def discard_card(self, card: Card) -> None:
        if self.state is not HandState.IN_PROGRESS:
            raise RuntimeError(f"hand is {self.state.value}")
        if not self.drew_this_turn:
            raise RuntimeError("must draw before discarding")
        self.hand.remove(card)
        self.discard.append(card)
        self.drew_this_turn = False
        if self.laid and not self.hand:
            # Shedding the last card onto the discard pile is going out, the
            # ordinary way it happens: you hit what you can and throw the rest.
            self.state = HandState.WENT_OUT
            self._emit("went_out", draws_used=self.draws_used)
            return
        self._end_turn()

    def play_skip(self) -> list[Card]:
        """Spend a Skip to look at the top of the stock.

        The Skip becomes this turn's discard, so no separate discard follows --
        that is what keeps hand size stable and lets the Skip shed itself. The
        dig costs no draw: a Skip denies a turn in the real game, so here it
        grants one that does not count. Resolve the reveal with `take_dug`.
        """
        if self.state is not HandState.IN_PROGRESS:
            raise RuntimeError(f"hand is {self.state.value}")
        if self.dig_options is not None:
            raise RuntimeError("finish the current dig first")
        if self.drew_this_turn:
            raise RuntimeError("already drew this turn; discard first")
        skip = next((c for c in self.hand if c.is_skip), None)
        if skip is None:
            raise RuntimeError("no Skip in hand")
        if not self.stock:
            raise RuntimeError("stock is empty")

        self.hand.remove(skip)
        self.discard.append(skip)
        depth = min(SKIP_DIG_DEPTH, len(self.stock))
        self.dig_options = self.stock[:depth]
        del self.stock[:depth]
        return list(self.dig_options)

    def take_dug(self, index: int) -> Card:
        """Keep one revealed card; the rest go to the bottom of the stock."""
        if self.dig_options is None:
            raise RuntimeError("no dig in progress")
        if not 0 <= index < len(self.dig_options):
            raise IndexError(f"pick 0..{len(self.dig_options) - 1}")

        chosen = self.dig_options.pop(index)
        self.hand.append(chosen)
        self.stock.extend(self.dig_options)
        self.dig_options = None

        # A dig deliberately does NOT spend a draw. Charging for it made Skips
        # a net loss in simulation (-1% to -7% across every phase): you burn a
        # draw finding the Skip and another using it, and a choice of three
        # does not pay for two turns. Free, the cycle costs only the draw that
        # turned up the Skip, which a choice of three clearly beats.
        self.skips_played += 1
        self.drew_this_turn = False
        self._emit("skip_dug", card=str(chosen))
        self._end_turn()
        return chosen

    def _end_turn(self) -> None:
        """Close out the player's turn, then let the table play.

        Order matters: a budget that just ran out ends the hand before the
        opponents move, so a loss is attributed to the thing that actually
        caused it rather than to whoever happened to go out next.
        """
        self._fail_if_out_of_road()
        if self.state is not HandState.IN_PROGRESS:
            return
        winner = self.table.end_of_turn()
        if winner is not None:
            if self.laid:
                # The phase is down, so it is cleared. Somebody else going out
                # only stops the shedding; it cannot take the clear back.
                self.state = HandState.PHASE_LAID
                self._emit("raced_after_laying", opponent=winner.name,
                           held=len(self.hand))
            else:
                self.mark_failed("opponent_out", opponent=winner.name)

    def _fail_if_out_of_road(self) -> None:
        """Settle the hand if the draw budget has run out.

        Once the phase is down this is not a loss at all -- it was cleared,
        and the budget expiring only stops you shedding the rest. Before it is
        down, a budget that just ran out is still only a loss if the phase is
        not already satisfiable, since the player is entitled to lay it.
        """
        if self.state is not HandState.IN_PROGRESS or self.draws_left != 0:
            return
        if self.laid:
            self.state = HandState.PHASE_LAID
            self._emit("out_of_draws_after_laying", held=len(self.hand))
        elif not self.can_lay_down():
            self.mark_failed("out_of_draws")

    def lay_down(self) -> Layout:
        if self.laid:
            raise RuntimeError("phase is already down")
        melds = solve_melds(self.hand, self.spec,
                            min_naturals_per_group=self.config.min_naturals_per_group)
        if melds is None:
            raise RuntimeError(f"phase {self.phase} not satisfiable from hand")
        # The layout is built out of the melds, so what you can see and what
        # the group means cannot drift apart.
        self.melds = melds
        layout = [m.cards for m in melds]
        self.layout = layout
        self.used_wilds_in_layout = sum(1 for g in layout for c in g if c.is_wild)
        for group in layout:
            for card in group:
                self.hand.remove(card)
        # Deliberately NOT terminal. Laying down clears the phase, and the
        # round then carries on so the cards still in hand can be hit onto
        # whatever is on the table -- which is the whole point of hitting.
        # The hand settles as PHASE_LAID when a clock actually runs out.
        self.laid = True
        self.draws_at_lay_down = self.draws_used
        self._emit("phase_completed", draws_used=self.draws_used,
                   wilds_used=self.used_wilds_in_layout)
        if not self.hand:
            self.state = HandState.WENT_OUT
            self._emit("went_out", draws_used=self.draws_used)
        return layout

    def hit(self, card: Card, meld) -> None:
        """Lay one card from hand onto a group already on the table.

        Only after your own phase is down -- that is the rule the whole
        mechanic hangs on, and it is what stops hitting being a way to dump
        cards you could not otherwise place.
        """
        if self.state is not HandState.IN_PROGRESS:
            raise RuntimeError(f"hand is {self.state.value}")
        if not self.laid:
            raise RuntimeError("lay your own phase down before hitting")
        if self.dig_pending:
            raise RuntimeError("finish the dig first")
        if card not in self.hand:
            raise RuntimeError(f"{card} is not in hand")
        if not meld.accepts(card):
            raise RuntimeError(f"{card} does not fit that group")

        self.hand.remove(card)
        meld.add(card)
        self.hits += 1
        self._emit("hit", card=str(card))
        if not self.hand:
            # Shedding the last card is going out, with no discard needed.
            self.state = HandState.WENT_OUT
            self._emit("went_out", draws_used=self.draws_used)

    def hittable(self) -> list:
        """Every group on the table you could legally play onto right now."""
        if self.state is not HandState.IN_PROGRESS or not self.laid:
            return []
        targets = self.melds + self.table.all_melds()
        return [m for m in targets if any(m.accepts(c) for c in self.hand)]

    # -- bookkeeping -------------------------------------------------------
    def mark_failed(self, reason: str, **detail) -> None:
        """End the hand as a loss. Public because a driver that runs the turn
        loop itself (the client, the autoplayer) has to be able to call it."""
        self.state = HandState.FAILED
        self._emit("hand_failed", reason=reason, score=hand_score(self.hand),
                   **detail)

    def _emit(self, kind: str, **detail) -> None:
        self.events.append(HandEvent(kind, self.phase, detail))

    def __repr__(self) -> str:
        return (f"<PhaseHand p{self.phase} {self.state.value} "
                f"hand={len(self.hand)} draws={self.draws_used}/{self.config.max_draws}>")


#: Deficits past this are indistinguishable for heuristic purposes, so the
#: search stops there rather than proving exactly how bad a hopeless hand is.
SHORT_CAP = 5


def _canonical(hand: list[Card], spec: PhaseSpec):
    """Collapse a hand to only what `spec` can actually discriminate on.

    SET and RUN ignore color; COLOR ignores rank. Projecting the hand onto the
    relevant axis makes the cache hit constantly across discard candidates,
    which is where nearly all the solver time goes.
    """
    wilds = sum(1 for c in hand if c.is_wild)
    if any(g.kind is GroupKind.COLOR for g in spec):
        return ("c", tuple(sorted(c.color.value for c in hand if c.is_number)), wilds)
    return ("r", tuple(sorted(c.rank for c in hand if c.is_number)), wilds)


def _rebuild(key) -> list[Card]:
    tag, values, wilds = key
    if tag == "r":
        cards = [number_card(r, Color.RED) for r in values]
    else:
        cards = [number_card(1, Color(v)) for v in values]
    return cards + [WILD] * wilds


@lru_cache(maxsize=300_000)
def _cards_short_cached(key, spec: PhaseSpec, min_nat: int, cap: int) -> int:
    hand = _rebuild(key)
    limit = min(cap, phase_card_count(spec))
    for deficit in range(0, limit + 1):
        for reduction in _reductions(spec, deficit):
            shrunk = tuple(GroupSpec(g.kind, g.size - d)
                           for g, d in zip(spec, reduction) if g.size - d > 0)
            if not shrunk:
                return deficit
            if solve_phase(hand, shrunk, min_naturals_per_group=min_nat) is not None:
                return deficit
    return limit + 1


def cards_short(hand: list[Card], spec: PhaseSpec, min_nat: int = 1,
                cap: int = SHORT_CAP) -> int:
    """How many more useful cards this hand needs to satisfy `spec`.

    Computed by shrinking the phase until it becomes solvable. This is a
    relaxation used as the autoplayer's heuristic and as a difficulty probe --
    not an exact edit distance. Values above `cap` are reported as cap + 1.
    """
    return _cards_short_cached(_canonical(hand, spec), spec, min_nat, cap)


def _reductions(spec: PhaseSpec, deficit: int):
    """All ways to remove `deficit` cards across the groups of `spec`."""
    if len(spec) == 1:
        if deficit <= spec[0].size:
            yield (deficit,)
        return
    for first in range(0, min(deficit, spec[0].size) + 1):
        for rest in _reductions(spec[1:], deficit - first):
            yield (first,) + rest
