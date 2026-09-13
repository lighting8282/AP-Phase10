"""Card model and deck construction.

Stock deck is 108 cards: numbers 1-12 in four colors, two copies each (96),
plus 8 Wilds and 4 Skips. Deck composition is configurable because the AP
items "Wild Card" and "Skip Card" literally add cards to the draw pile.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

MIN_RANK = 1
MAX_RANK = 12
COPIES_PER_RANK = 2

STOCK_WILDS = 8
STOCK_SKIPS = 4


class Color(Enum):
    RED = "red"
    BLUE = "blue"
    GREEN = "green"
    YELLOW = "yellow"


class Kind(Enum):
    NUMBER = "number"
    WILD = "wild"
    SKIP = "skip"


@dataclass(frozen=True, order=True)
class Card:
    kind: Kind
    rank: int | None = None
    color: Color | None = None

    @property
    def is_number(self) -> bool:
        return self.kind is Kind.NUMBER

    @property
    def is_wild(self) -> bool:
        return self.kind is Kind.WILD

    @property
    def is_skip(self) -> bool:
        return self.kind is Kind.SKIP

    @property
    def points(self) -> int:
        """Official scoring: 1-9 = 5, 10-12 = 10, Skip = 15, Wild = 25."""
        if self.kind is Kind.WILD:
            return 25
        if self.kind is Kind.SKIP:
            return 15
        return 5 if self.rank <= 9 else 10

    def __str__(self) -> str:
        if self.kind is Kind.WILD:
            return "W"
        if self.kind is Kind.SKIP:
            return "S"
        return f"{self.rank}{self.color.value[0].upper()}"


WILD = Card(Kind.WILD)
SKIP = Card(Kind.SKIP)


def number_card(rank: int, color: Color) -> Card:
    if not MIN_RANK <= rank <= MAX_RANK:
        raise ValueError(f"rank {rank} out of range")
    return Card(Kind.NUMBER, rank, color)


def build_deck(wilds: int = STOCK_WILDS, skips: int = STOCK_SKIPS) -> list[Card]:
    """Build a deck. `wilds` and `skips` are driven by AP item counts."""
    if not 0 <= wilds <= STOCK_WILDS:
        raise ValueError(f"wilds must be 0..{STOCK_WILDS}, got {wilds}")
    if not 0 <= skips <= STOCK_SKIPS:
        raise ValueError(f"skips must be 0..{STOCK_SKIPS}, got {skips}")

    deck: list[Card] = []
    for rank in range(MIN_RANK, MAX_RANK + 1):
        for color in Color:
            deck.extend([number_card(rank, color)] * COPIES_PER_RANK)
    deck.extend([WILD] * wilds)
    deck.extend([SKIP] * skips)
    return deck


def shuffled_deck(rng: random.Random, wilds: int = STOCK_WILDS, skips: int = STOCK_SKIPS) -> list[Card]:
    deck = build_deck(wilds, skips)
    rng.shuffle(deck)
    return deck


def hand_score(cards: list[Card]) -> int:
    return sum(c.points for c in cards)
