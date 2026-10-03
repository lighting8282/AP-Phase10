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

from .cards import (
    COLOR_ORDER, SKIP, WILD, Card, Color, hand_score, number_card, shuffled_deck,
)
from .phases import (
    PHASES, GroupKind, GroupSpec, Layout, Meld, PhaseSpec, phase_card_count,
    solve_lay_options, solve_melds, solve_phase,
)


#: How deep into the stock a played Skip lets you look.
SKIP_DIG_DEPTH = 3

#: The orders `PhaseHand.sort_hand` understands. Named rather than boolean
#: because a third ("by what the phase wants") is an obvious thing to want
#: later, and a flag would have to be unpicked to add it.
SORT_BY_RANK = "rank"
SORT_BY_COLOR = "color"
SORT_ORDERS = (SORT_BY_RANK, SORT_BY_COLOR)

#: Where the specials sit in a sorted hand. Last, as a block: a Wild or a Skip
#: belongs to no run and no set, so leaving them in rank position breaks up the
#: sequence the sort exists to make readable.
_NUMBERS, _WILDS, _SKIPS = 0, 1, 2


def sort_key(card: Card, order: str = SORT_BY_RANK):
    """Where one card sits in a sorted hand.

    Both orders are total: ties inside the leading key fall through to the
    other attribute, so sorting the same hand twice gives the same arrangement
    whichever order it was in before. Without that, a sort would shuffle equal
    cards around and the hand would look like it had changed when it had not.
    """
    if card.is_skip:
        return (_SKIPS, 0, 0)
    if card.is_wild:
        return (_WILDS, 0, 0)
    colour = COLOR_ORDER[card.color]
    if order == SORT_BY_COLOR:
        return (_NUMBERS, colour, card.rank)
    return (_NUMBERS, card.rank, colour)


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

    #: What playing a Skip does.
    #:
    #: "dig" reveals the top three of the stock and keeps one. "deny" is the
    #: printed rule: the next seat loses its turn. Archipelago uses the dig,
    #: because every measured clear rate its access rules are built on was
    #: measured with it. "deny" is the free-play game, where nothing is gated
    #: on a difficulty number.
    skip_mode: str = "dig"

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
        #: What the seats did, oldest first, as (seat name, sentence). The
        #: clients drain it: opponents played in silence before this, so a
        #: seat denied its turn looked exactly like one that took it.
        self.log: list[tuple[str, str]] = []
        #: The seat that went out, once one has. Sticky: the round is over,
        #: and a player who keeps acting must keep losing it rather than
        #: slipping through because the transition already happened.
        self.winner = None
        #: The hand being played at this table, so a seat aiming a Skip can
        #: see the player as a target like any other. Without it the seats
        #: could only ever deny each other, which is a rule that runs one way.
        self.player = None

    def reset(self, stock: list[Card], discard: list[Card]) -> None:
        self.stock = stock
        self.discard = discard
        self.winner = None
        self.log.clear()

    def say(self, seat: str, sentence: str) -> None:
        self.log.append((seat, sentence))

    def drain_log(self) -> list[tuple[str, str]]:
        """Take everything said since the last time anybody looked."""
        said, self.log = self.log, []
        return said

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
            # Also the melds, which the JS port cleared here and this did not.
            # Unreachable through a session, which builds fresh seats every
            # round, but a reused seat kept last round's groups on the table
            # for anybody to hit onto -- and the two ports disagreeing about
            # that is exactly what the crosscheck exists to stop.
            seat.melds = []
            seat.laid_down = False
            seat.went_out = False
            seat.skipped = False
            # Per round, like everything else here: last round's tally would
            # make this round's table impossible to reconcile.
            seat.drew = 0
            seat.threw = 0
            seat.placed = 0

    @property
    def discard_top(self) -> Card | None:
        return self.discard[-1] if self.discard else None

    def next_actor(self):
        """The seat that would play next, or None if nobody would.

        Seats act in order after the player, so the next one is the first that
        is still in the round. A seat already denied a turn is skipped over:
        stacking two Skips on one seat would cost the second one nothing.
        """
        for seat in self.seats:
            if not seat.went_out and not seat.skipped:
                return seat
        return None

    def deny_targets(self, exclude=None) -> list:
        """Everybody still in the round who could lose a turn, player included.

        One place, so the player throwing a Skip and a seat throwing one are
        choosing from the same list by the same rule. `exclude` is whoever is
        throwing it -- you cannot deny yourself -- and anyone already denied is
        left out, since a second Skip on them would cost nothing.
        """
        targets = []
        player = self.player
        if (player is not None and player is not exclude and not player.skipped
                and player.state is HandState.IN_PROGRESS):
            targets.append(player)
        for seat in self.seats:
            if seat is not exclude and not seat.went_out and not seat.skipped:
                targets.append(seat)
        return targets

    def all_melds(self) -> list:
        """Every group face up on the table, in seat order.

        Phase 10 lets a hit land on anybody's group, not just your own, so
        targeting has to see the whole table rather than one seat.
        """
        melds = []
        for seat in self.seats:
            melds.extend(seat.melds)
        return melds

    def play_seat(self, seat) -> object | None:
        """Play one seat's turn. Returns the winner once there is one.

        Split out of end_of_turn to match the JS port, where a driver that
        shows the turns happening one at a time takes them one at a time.
        Everything a turn means lives here rather than in the loop below --
        including consuming a Skip -- because a seat played through here has to
        be played exactly as it is played there.

        The browser's paced walk itself is not ported: it is presentation for a
        driver the Kivy client does not have, and it changes no rule. This
        method is, so that the two ports keep a turn in the same place.
        """
        if self.winner is not None:
            return self.winner
        if seat.skipped:
            # Consumed where the turn would have happened rather than where
            # the Skip was played, so it costs exactly one turn however long
            # it waits for that seat to come round.
            seat.skipped = False
            self.say(seat.name, "misses a turn")
            return self.winner
        if seat.take_turn(self):
            self.winner = seat
        return self.winner

    def end_of_turn(self) -> object | None:
        """Run every opponent's turn. Returns the seat that went out, if any.

        Once somebody is out nobody plays on: the round ended, and further
        turns would let a player who drew again quietly survive a race they
        had already lost.
        """
        if self.winner is not None:
            return self.winner
        for seat in self.seats:
            if self.play_seat(seat) is not None:
                return self.winner
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
        # So the seats can aim at you. A back-reference rather than a copy of
        # what they need to know, because what a good target looks like is the
        # seats' business and it would otherwise be spelled out twice.
        self.table.player = self
        #: Set by a seat that threw a Skip at you; consumed after the seats
        #: have played, where your turn would have been.
        self.skipped = False
        #: How many turns Skips have cost you this hand. The flag is consumed
        #: the instant the turn is lost, so a driver that only looks between
        #: moves would never see it -- this is what it reads instead.
        self.turns_missed = 0
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
        #: Cards bought from the store into this hand. Counted so the card
        #: accounting still balances: dealt + drawn + bought = down + held +
        #: thrown.
        self.bought_cards = 0
        self.dig_options: list[Card] | None = None
        #: A discarded Skip waiting to be aimed, as the seats it could be
        #: aimed at. None when there is nothing to aim. Deny mode only.
        self.pending_deny: list | None = None

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

    def sort_hand(self, order: str = SORT_BY_RANK) -> list[Card]:
        """Put the hand in reading order. Free, and not a move.

        It costs no draw, does not end the turn and is legal at any point,
        because it changes nothing a rule can see -- only the order the cards
        sit in. Every move takes a card rather than an index, so nothing the
        engine does cares where in the list a card was.

        Two orders, because the phases come in two shapes. Seventeen of the
        twenty are sets and runs, which are read by rank; three (8, 11 and 14)
        are colour groups, and in those a rank sort scatters the one thing you
        are counting.
        """
        if order not in SORT_ORDERS:
            raise ValueError(f"sort order {order!r} is not one of {SORT_ORDERS}")
        self.hand.sort(key=lambda card: sort_key(card, order))
        return self.hand

    def solution(self) -> Layout | None:
        return solve_phase(self.hand, self.spec,
                           min_naturals_per_group=self.config.min_naturals_per_group)

    def can_lay_down(self) -> bool:
        return self.solution() is not None

    # -- actions -----------------------------------------------------------
    def take_bought_card(self, card: Card) -> Card:
        """Put a card the player bought into their hand.

        Not a draw. It costs no draw from the budget, it comes from nowhere
        rather than off the stock, and it can be taken at any point in a turn
        -- the deck is not short of Wilds, the player is. What it does cost is
        the ordinary thing: the turn still ends on a discard, so a bought card
        is one more card to shed, and one more to be caught holding. A Wild is
        twenty-five points if the round ends on you.

        Refused once the hand is over, and refused mid-move: a card arriving
        while a Skip is waiting to be aimed or a dig is waiting to be picked
        from would change the hand underneath a decision already in flight.
        """
        if self.state is not HandState.IN_PROGRESS:
            raise RuntimeError(f"hand is {self.state.value}")
        if self.dig_pending:
            raise RuntimeError("finish the dig first")
        if self.deny_pending:
            raise RuntimeError("say who misses their turn first")
        self.hand.append(card)
        self.bought_cards += 1
        self._emit("bought_card", card=str(card))
        return card

    def draw(self, from_discard: bool = False) -> Card:
        if self.state is not HandState.IN_PROGRESS:
            raise RuntimeError(f"hand is {self.state.value}")
        if self.drew_this_turn:
            raise RuntimeError("already drew this turn; discard first")
        if self.deny_pending:
            raise RuntimeError("say who misses their turn first")
        if from_discard:
            if not self.config.allow_discard_draw or not self.discard:
                raise RuntimeError("cannot draw from discard")
            # The printed rule, and the one this engine was missing: a Skip on
            # the pile is spent. Taking it back up makes one card deny a turn
            # every time round the table, and in a seed -- where a dig costs no
            # draw -- an endless free choice of three. Both clients let the
            # player do exactly that until this line existed.
            if self.discard[-1].is_skip:
                raise RuntimeError("a played Skip cannot be taken from the discard")
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
        # Before the draw check: once a Skip is waiting to be aimed the draw
        # is already spent, so "must draw before discarding" would name the
        # wrong problem and send the player looking for a draw they cannot
        # make.
        if self.deny_pending:
            raise RuntimeError("say who misses their turn first")
        if not self.drew_this_turn:
            raise RuntimeError("must draw before discarding")
        self.hand.remove(card)
        self.discard.append(card)
        self.drew_this_turn = False
        if self.laid and not self.hand:
            # Shedding the last card onto the discard pile is going out, the
            # ordinary way it happens: you hit what you can and throw the rest.
            # Going out ends the round, so a Skip thrown to go out denies
            # nobody -- there is no next turn left for anyone to miss.
            self.state = HandState.WENT_OUT
            self._emit("went_out", draws_used=self.draws_used)
            return
        # The printed rule: a Skip is discarded, and whoever discarded it says
        # who loses a turn. The turn does not end until they have said, which
        # is what `deny_seat` is for. With nobody eligible it is an ordinary
        # discard -- the card is spent either way, and refusing the throw would
        # strand a player holding a Skip they cannot legally get rid of.
        if self.config.skip_mode == "deny" and card.is_skip:
            targets = self.deny_targets()
            if targets:
                self.pending_deny = targets
                return
        self._end_turn()

    def deny_targets(self) -> list:
        """The seats a Skip could be thrown at right now.

        One already denied is left out: stacking two Skips on a seat would
        cost the second one nothing, which is the same reason `next_actor`
        passes it over.
        """
        # Excluding yourself, which is the only difference between your list
        # and a seat's -- the rule is otherwise the same for everybody.
        return self.table.deny_targets(self)

    @property
    def deny_pending(self) -> bool:
        """Whether a discarded Skip is waiting to be pointed at somebody."""
        return self.pending_deny is not None

    def deny_seat(self, index: int):
        """Say who misses their turn, and end the turn."""
        if self.pending_deny is None:
            raise RuntimeError("no Skip to aim")
        if not 0 <= index < len(self.pending_deny):
            raise IndexError(f"pick 0..{len(self.pending_deny) - 1}")
        target = self.pending_deny[index]
        self.pending_deny = None
        target.skipped = True
        self.skips_played += 1
        self._emit("skip_denied", seat=target.name)
        self._end_turn()
        return target

    def play_skip(self) -> list[Card]:
        """Dig with a Skip: look at the top of the stock.

        Only "dig" reaches this, which is the default and what every measured
        clear rate was measured against. In "deny" -- the printed rule, and
        what the game without Archipelago uses -- a Skip is played by being
        discarded, so `discard_card` and `deny_seat` are the way in and this
        refuses.

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

        # Denying is done by discarding the Skip, the way the box has it, so
        # there is no pre-draw move to make. There used to be, and it was a
        # trap: the move stopped being legal the moment you drew, and the only
        # thing left to do with the Skip was throw it away for nothing.
        if self.config.skip_mode == "deny":
            raise RuntimeError("discard the Skip to make somebody miss a turn")

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
        self._settle_table_turn(self.table.end_of_turn())
        # Then, if a seat threw a Skip at you while it played, the turn it
        # costs you is *this* one -- the one that would have come next. A
        # while loop because two seats can deny you in the same round.
        while self.skipped and self.state is HandState.IN_PROGRESS:
            self._lose_turn()
            self._settle_table_turn(self.table.end_of_turn())

    def _lose_turn(self) -> None:
        """Spend a turn that has been taken off you.

        Read *after* the table has played, never before. The flag is set by a
        seat during the table's turn, so a check at the top of `_end_turn` is
        reading the previous round's news: it let you play the turn you had
        been denied and then charged the miss to the turn after, which is
        neither the rule nor anything a player could make sense of.
        """
        self.skipped = False
        self.turns_missed += 1
        self.table.say("You", "miss a turn")
        self._emit("turn_missed")

    def _settle_table_turn(self, winner) -> None:
        """Apply what the table's turn did to the hand."""
        if winner is None:
            return
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

    def lay_down_options(self) -> list:
        """Every distinct way this hand could lay the phase down.

        More than one only when a wild could stand for more than one thing --
        and then the choice is worth making, because it decides what can be hit
        onto the group afterwards. A run of 4 from `W 4 5 6` is 3-4-5-6 or
        4-5-6-7, which take a 2 or a 7 and a 3 or an 8 respectively.
        """
        if self.laid or self.state is not HandState.IN_PROGRESS:
            return []
        return solve_lay_options(
            self.hand, self.spec,
            min_naturals_per_group=self.config.min_naturals_per_group,
        )

    def lay_down(self, option=None) -> Layout:
        """Lay the phase down, optionally choosing what the wilds stand for.

        With no option this keeps taking the solver's first answer, which is
        what every caller that does not care about wilds already relied on.
        """
        if self.laid:
            raise RuntimeError("phase is already down")
        if option is not None:
            melds = list(option.melds)
            held = list(self.hand)
            for card in (c for m in melds for c in m.cards):
                if card not in held:
                    raise RuntimeError("that lay-down is not from this hand")
                held.remove(card)
        else:
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
        if self.deny_pending:
            raise RuntimeError("say who misses their turn first")
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
