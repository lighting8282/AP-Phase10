"""Computer players sharing the table with you.

They exist to put a clock on the round that is not your draw budget. A round
now ends on whichever comes first: your draws running out, or somebody going
out.

Measured, those two clocks do not layer the way I expected. The guess was that
the budget would bind early and the opponents would take over once Extra Draw
items piled up. The opposite happens. Going out takes a seat about eight turns
on its own, but three seats race and the round ends on the *fastest* of them,
which lands near turn five and barely moves with phase or skill:

    fastest of N goes out at turn    1 seat   2 seats   3 seats
      opponents on phase 1             7.8      5.6       4.9
      opponents on phase 7            14.6      9.0       8.0

So the race resolves before a large budget can matter. Past roughly eight
draws the budget buys nothing (phase 6 clears 35% at 4 draws, 43% at 8, and
45% at 12, 16 and 24 alike). That is a minimum-of-N effect, not a tuning
miss -- more opponents make it worse, and weakening them barely moves it.

Live with it by sizing the draw pool to the range that still pays, or drop the
budget for a pure race. Either way it is a decision about the item economy,
not about this file.

Skill is a pair of probabilities rather than a different algorithm. Both sit at
1.0 for a perfect greedy player, and lowering them degrades the same policy in
the two ways a human actually plays worse: not watching the discard pile, and
throwing the wrong card. That keeps easy/hard levels a matter of numbers later
rather than three policies to keep in step.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .cards import Card, hand_score
from .engine import GameConfig, Table, cards_short
from .phases import PHASES, PhaseSpec, solve_phase


@dataclass(frozen=True)
class OpponentSkill:
    """How well a seat plays. 1.0 / 0.0 is the greedy autoplayer exactly."""

    name: str
    #: Chance it looks at the discard pile at all before drawing blind.
    discard_awareness: float
    #: Chance it throws the second-best card instead of the best one.
    discard_error: float


#: Beats a careless human, loses to a careful one. Measured against the greedy
#: autoplayer it costs the player 1 to 13 points of clear rate across the ten
#: phases at eight draws -- present, not punishing.
MID = OpponentSkill("mid", discard_awareness=0.7, discard_error=0.25)


class Opponent:
    """One computer seat: its own hand, its own phase, its own progress."""

    def __init__(self, name: str, phase: int, config: GameConfig,
                 rng: random.Random, skill: OpponentSkill = MID) -> None:
        self.name = name
        self.phase = phase
        self.config = config
        self.rng = rng
        self.skill = skill

        self.hand: list[Card] = []
        self.laid_down = False
        self.went_out = False

    @property
    def spec(self) -> PhaseSpec:
        return PHASES[self.phase]

    @property
    def score(self) -> int:
        """What it is caught holding when the round ends."""
        return hand_score(self.hand)

    def _short(self, hand: list[Card]) -> int:
        return cards_short(hand, self.spec, self.config.min_naturals_per_group)

    def _solution(self):
        return solve_phase(self.hand, self.spec,
                           min_naturals_per_group=self.config.min_naturals_per_group)

    # -- policy -------------------------------------------------------------
    def _wants_discard_top(self, top: Card | None) -> bool:
        if top is None or not self.config.allow_discard_draw:
            return False
        if self.rng.random() > self.skill.discard_awareness:
            return False  # not paying attention this turn
        return self._short(self.hand + [top]) < self._short(self.hand)

    def _choose_discard(self) -> Card:
        # Exclude by position, not by identity. build_deck repeats a card with
        # `[number_card(...)] * COPIES_PER_RANK`, so both copies of a rank are
        # the *same object*: `c is not card` drops both, and the seat then
        # rates every duplicate as twice the loss it really is and refuses to
        # throw it. In a RUN phase duplicates are exactly what it should throw.
        def key(item):
            index, card = item
            rest = self.hand[:index] + self.hand[index + 1:]
            return (self._short(rest), -card.points)

        ranked = [card for _, card in sorted(enumerate(self.hand), key=key)]
        # A mistake is the second-best card, not a random one: a player who
        # misreads their hand still throws something plausible.
        if len(ranked) > 1 and self.rng.random() < self.skill.discard_error:
            return ranked[1]
        return ranked[0]

    def _try_lay_down(self) -> None:
        if self.laid_down:
            return
        layout = self._solution()
        if layout is None:
            return
        for group in layout:
            for card in group:
                self.hand.remove(card)
        self.laid_down = True

    # -- turn ---------------------------------------------------------------
    def take_turn(self, table: Table) -> bool:
        """Play one turn. Returns True if this seat went out."""
        if self.went_out:
            return False
        if not table.stock:
            return False

        self._try_lay_down()
        if self._finished():
            return True

        if self.laid_down:
            # Already down: shed, do not draw. Drawing one and discarding one
            # leaves the hand the same size forever, so a seat that has laid
            # down could never go out -- which is exactly what the first
            # version of this did. Real Phase 10 sheds by hitting onto groups
            # already on the table; until that exists, one card a turn and no
            # draw is the conservative stand-in, slower than the real thing.
            table.discard.append(self._shed())
            return self._finished()

        if self._wants_discard_top(table.discard_top):
            self.hand.append(table.discard.pop())
        else:
            self.hand.append(table.stock.pop(0))

        self._try_lay_down()
        if self._finished():
            return True

        table.discard.append(self._choose_discard_card())
        return self._finished()

    def _shed(self) -> Card:
        """Throw the most expensive card; nothing left is worth building on."""
        card = max(self.hand, key=lambda c: c.points)
        self.hand.remove(card)
        return card

    def _choose_discard_card(self) -> Card:
        card = self._choose_discard()
        self.hand.remove(card)
        return card

    def _finished(self) -> bool:
        """Going out is an empty hand -- by laying down, or by shedding after.

        Shedding is one card a turn because hitting (laying onto groups already
        on the table) is not built yet. That makes going out slower than the
        real game, not faster, so opponents are if anything gentle here.
        """
        if self.laid_down and not self.hand:
            self.went_out = True
        return self.went_out

    def __repr__(self) -> str:
        state = "out" if self.went_out else ("laid" if self.laid_down else "building")
        return f"<Opponent {self.name} p{self.phase} {state} hand={len(self.hand)}>"


def build_opponents(count: int, phases: list[int] | None, config: GameConfig,
                    rng: random.Random, skill: OpponentSkill = MID) -> list[Opponent]:
    """Seat `count` opponents, each on its own phase."""
    names = ["Ada", "Bo", "Cy", "Del", "Eve", "Fen"]
    if phases is None:
        phases = [1] * count
    return [
        Opponent(names[i % len(names)], phases[i], config, rng, skill)
        for i in range(count)
    ]
