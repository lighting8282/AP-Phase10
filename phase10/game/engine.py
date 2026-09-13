"""Headless solo Phase 10 engine.

Solo play replaces the multiplayer race-to-go-out with pressure from the draw
pile: you get a bounded number of draws to lay your phase down. That removes
the need for opponent AI entirely, and makes every AP item that adds wilds or
draws directly, measurably valuable.

The engine is pure -- no I/O, no UI, no Archipelago imports. A client drives it
turn by turn and reads `events` to decide which locations to check.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from functools import lru_cache
from enum import Enum

from .cards import WILD, Card, Color, hand_score, number_card, shuffled_deck
from .phases import (
    PHASES, GroupKind, GroupSpec, Layout, PhaseSpec, phase_card_count, solve_phase,
)


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
    skips_in_deck: int = 4        # "Skip Card" items
    max_draws: int = 20           # "Extra Draw" items
    min_naturals_per_group: int = 1
    allow_discard_draw: bool = True


@dataclass
class HandEvent:
    kind: str
    phase: int
    detail: dict = field(default_factory=dict)


class PhaseHand:
    """One round: a single attempt at a single phase."""

    def __init__(self, phase: int, config: GameConfig, rng: random.Random, spec: PhaseSpec | None = None):
        self.phase = phase
        self.spec = spec if spec is not None else PHASES[phase]
        self.config = config
        self.rng = rng

        deck = shuffled_deck(rng, config.wilds_in_deck, config.skips_in_deck)
        self.hand: list[Card] = deck[: config.hand_size]
        rest = deck[config.hand_size:]
        self.discard: list[Card] = [rest[0]]
        self.stock: list[Card] = rest[1:]

        self.draws_used = 0
        self.state = HandState.IN_PROGRESS
        self.layout: Layout | None = None
        self.events: list[HandEvent] = []
        self.drew_this_turn = False
        self.used_wilds_in_layout = 0

    # -- queries -----------------------------------------------------------
    @property
    def draws_left(self) -> int:
        return max(0, self.config.max_draws - self.draws_used)

    @property
    def discard_top(self) -> Card | None:
        return self.discard[-1] if self.discard else None

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
                self.mark_failed("stock_empty")
                raise RuntimeError("stock is empty")
            card = self.stock.pop(0)
        self.hand.append(card)
        self.draws_used += 1
        self.drew_this_turn = True
        return card

    def discard_card(self, card: Card) -> None:
        if self.state is not HandState.IN_PROGRESS:
            raise RuntimeError(f"hand is {self.state.value}")
        if not self.drew_this_turn:
            raise RuntimeError("must draw before discarding")
        self.hand.remove(card)
        self.discard.append(card)
        self.drew_this_turn = False
        if self.draws_left == 0 and self.state is HandState.IN_PROGRESS:
            self.mark_failed("out_of_draws")

    def lay_down(self) -> Layout:
        layout = self.solution()
        if layout is None:
            raise RuntimeError(f"phase {self.phase} not satisfiable from hand")
        self.layout = layout
        self.used_wilds_in_layout = sum(1 for g in layout for c in g if c.is_wild)
        for group in layout:
            for card in group:
                self.hand.remove(card)
        self.state = HandState.PHASE_LAID
        self._emit("phase_completed", draws_used=self.draws_used,
                   wilds_used=self.used_wilds_in_layout)
        if not self.hand:
            self.state = HandState.WENT_OUT
            self._emit("went_out", draws_used=self.draws_used)
        return layout

    # -- bookkeeping -------------------------------------------------------
    def mark_failed(self, reason: str) -> None:
        """End the hand as a loss. Public because a driver that runs the turn
        loop itself (the client, the autoplayer) has to be able to call it."""
        self.state = HandState.FAILED
        self._emit("hand_failed", reason=reason, score=hand_score(self.hand))

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
