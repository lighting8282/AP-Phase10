"""Phase definitions and the phase-satisfaction solver.

A phase is a tuple of groups. A group is one of:
    SET(n)    n cards of the same rank, colors irrelevant
    RUN(n)    n cards of consecutive ranks, colors irrelevant, no wraparound
    COLOR(n)  n cards of the same color, ranks irrelevant

SET and COLOR can be *anchored* to a particular rank or color:
    SET(3, rank=7)            three 7s specifically
    COLOR(5, color=Color.GREEN)  five green cards specifically

Anchoring is much harder than it looks, and in the opposite direction to the
intuition that a named target is "simpler". A free group lets you pivot to
whichever rank or color the deal was kind about; an anchored one does not.
Measured, five cards of a *named* color clears 49% where five of any one color
clears 79%, on the same budget. Each rank has only eight copies in the deck, so
an anchored SET is scarcer still.

Wilds substitute for any card. Skips can never be part of a phase.

`solve_phase` answers "can this hand lay down this phase, and with which
cards?" It is an exhaustive search with pruning. Hands are ~10-13 cards and
phases have at most two groups, so the search space is tiny -- correctness and
legibility matter far more than cleverness here.

The search deliberately enumerates wild placements even where a natural card is
available, because spending a wild in one group can free a scarce natural for
another. Example: RUN(4) of 3-4-5-6 alongside SET(3) of 5s when the hand holds
exactly three 5s -- the run must take a wild for its 5 or the set cannot form.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from itertools import combinations

from .cards import MAX_RANK, MIN_RANK, Card, Color

# Official rules forbid completing a phase using only wild cards. The exact
# reading varies by printing and by table, so it is a knob: the number of
# natural (non-wild) cards each group must contain.
DEFAULT_MIN_NATURALS_PER_GROUP = 1


class GroupKind(Enum):
    SET = "set"
    RUN = "run"
    COLOR = "color"


@dataclass(frozen=True)
class GroupSpec:
    kind: GroupKind
    size: int
    #: Anchors. None means "any", which is the free group the stock ten use.
    rank: int | None = None
    color: Color | None = None

    def __str__(self) -> str:
        if self.kind is GroupKind.COLOR:
            if self.color is not None:
                return f"{self.size} {self.color.value} cards"
            return f"{self.size} cards of one color"
        if self.kind is GroupKind.SET and self.rank is not None:
            return f"{self.size} {self.rank}s"
        noun = "set" if self.kind is GroupKind.SET else "run"
        return f"{noun} of {self.size}"


def SET(n: int, rank: int | None = None) -> GroupSpec:
    return GroupSpec(GroupKind.SET, n, rank=rank)


def RUN(n: int) -> GroupSpec:
    return GroupSpec(GroupKind.RUN, n)


def COLOR(n: int, color: Color | None = None) -> GroupSpec:
    return GroupSpec(GroupKind.COLOR, n, color=color)


PhaseSpec = tuple[GroupSpec, ...]

#: The ten stock phases, in printed order.
PHASES: dict[int, PhaseSpec] = {
    1: (SET(3), SET(3)),
    2: (SET(3), RUN(4)),
    3: (SET(4), RUN(4)),
    4: (RUN(7),),
    5: (RUN(8),),
    6: (RUN(9),),
    7: (SET(4), SET(4)),
    8: (COLOR(7),),
    9: (SET(5), SET(2)),
    10: (SET(5), SET(3)),

    # 11-20. Measured at the same baseline as the stock ten (0 wilds, 8 draws,
    # greedy autoplayer) and ordered by that measurement, because the printed
    # order of the original ten is famously not a difficulty ramp. Rates in
    # comments are what the sweep gave at 600 trials.
    11: (COLOR(5),),                    # 94%
    12: (SET(3), SET(2)),               # 91%
    13: (RUN(5), SET(2)),               # 79%
    14: (COLOR(6),),                    # 72%
    15: (RUN(4), RUN(4)),               # 62%
    16: (RUN(4), RUN(4), SET(2)),       # 57%
    17: (RUN(5), SET(3)),               # 49%
    18: (RUN(6), SET(3)),               # 29%
    19: (RUN(5), RUN(5)),               # 22%
    20: (SET(3), SET(3), SET(3)),       # 11%
}

#: How many phases exist. A phase can never ask for more cards than a hand can
#: hold, so this is bounded by hand size (10, or 12 with both upgrades) rather
#: than by imagination: three sets of four needs twelve cards and is
#: unclearable at any budget, which a sweep showed as a flat 0%.
PHASE_COUNT = len(PHASES)
MAX_PHASE_CARDS = 10


def phase_description(phase: int) -> str:
    return " + ".join(str(g) for g in PHASES[phase])


def phase_card_count(spec: PhaseSpec) -> int:
    return sum(g.size for g in spec)


Group = list[Card]
Layout = list[Group]


# --------------------------------------------------------------------------
# Solver
# --------------------------------------------------------------------------
# Internally the search works on rank counts plus a wild count, not on Card
# objects. Colors are irrelevant to SET and RUN, so collapsing to ranks removes
# a large amount of redundant branching. COLOR groups need color information,
# so they are solved on their own path -- see the guard in solve_phase.

#: (natural ranks used, wilds used, meaning). The meaning is what makes
#: hitting possible later: a SET remembers its rank and a RUN its starting
#: rank, so `3R W 5B` still knows the wild is standing in for a 4. Deriving
#: that after the fact is ambiguous -- a lone 5 with two wilds could be
#: 3-4-5, 4-5-6 or 5-6-7 -- so it is recorded when the group is built.
_Meaning = tuple[str, object]
_RankPlan = tuple[Counter, int, _Meaning]


def _set_candidates(spec: GroupSpec, pool: Counter, wilds: int, min_nat: int):
    n = spec.size
    # A group built purely from wilds has no rank to anchor on, so the per-rank
    # loop below (which starts at k >= 1) can never emit it. Emit it once here.
    if min_nat <= 0 and wilds >= n:
        yield Counter(), n, ("set", None)
    # An anchored SET may only be built from its own rank, so the pool it may
    # draw on is that one entry -- including when the hand holds none of it,
    # which is what makes anchoring hard.
    ranks = ({spec.rank: pool[spec.rank]} if spec.rank is not None else pool).items()
    for rank, avail in ranks:
        lo = max(min_nat, 1, n - wilds)
        hi = min(avail, n)
        for k in range(lo, hi + 1):
            yield Counter({rank: k}), n - k, ("set", rank)


def _run_candidates(spec: GroupSpec, pool: Counter, wilds: int, min_nat: int):
    n = spec.size
    if n > MAX_RANK:
        return
    for start in range(MIN_RANK, MAX_RANK - n + 2):
        ranks = list(range(start, start + n))
        forced = [i for i, r in enumerate(ranks) if pool[r] == 0]
        if len(forced) > wilds:
            continue
        optional = [i for i, r in enumerate(ranks) if pool[r] > 0]
        for extra_n in range(0, len(optional) + 1):
            if len(forced) + extra_n > wilds:
                break
            if n - (len(forced) + extra_n) < min_nat:
                continue
            for extra in combinations(optional, extra_n):
                wild_at = set(forced) | set(extra)
                used = Counter(r for i, r in enumerate(ranks) if i not in wild_at)
                yield used, len(wild_at), ("run", start)


def _candidates(spec: GroupSpec, pool: Counter, wilds: int, min_nat: int):
    if spec.kind is GroupKind.SET:
        yield from _set_candidates(spec, pool, wilds, min_nat)
    elif spec.kind is GroupKind.RUN:
        yield from _run_candidates(spec, pool, wilds, min_nat)
    else:
        raise AssertionError(f"{spec.kind} is solved separately")


def _search(specs: tuple[GroupSpec, ...], pool: Counter, wilds: int, min_nat: int) -> list[_RankPlan] | None:
    if not specs:
        return []
    head, tail = specs[0], specs[1:]
    for used, used_wilds, meaning in _candidates(head, pool, wilds, min_nat):
        sub = _search(tail, pool - used, wilds - used_wilds, min_nat)
        if sub is not None:
            return [(used, used_wilds, meaning)] + sub
    return None


def _materialize(hand: list[Card], plans: list[_RankPlan]) -> Layout:
    """Turn a rank-level plan back into concrete cards taken from the hand."""
    by_rank: dict[int, list[Card]] = {}
    wild_stack: list[Card] = []
    for card in hand:
        if card.is_wild:
            wild_stack.append(card)
        elif card.is_number:
            by_rank.setdefault(card.rank, []).append(card)

    layout: Layout = []
    for used, used_wilds, _meaning in plans:
        group: Group = []
        for rank, count in used.items():
            for _ in range(count):
                group.append(by_rank[rank].pop())
        for _ in range(used_wilds):
            group.append(wild_stack.pop())
        layout.append(group)
    return layout


def solve_phase(
    hand: list[Card],
    spec: PhaseSpec,
    *,
    min_naturals_per_group: int = DEFAULT_MIN_NATURALS_PER_GROUP,
) -> Layout | None:
    """Return a concrete lay-down for `spec` from `hand`, or None if impossible.

    Skips are ignored entirely -- they can never be part of a phase.
    """
    kinds = {g.kind for g in spec}
    if GroupKind.COLOR in kinds:
        if kinds != {GroupKind.COLOR} or len(spec) != 1:
            raise NotImplementedError(
                "COLOR groups are only supported as a phase's sole group. "
                "Mixing COLOR with SET/RUN needs joint rank+color search."
            )
        return _solve_color(hand, spec[0], min_naturals_per_group)

    wilds = sum(1 for c in hand if c.is_wild)
    pool = Counter(c.rank for c in hand if c.is_number)

    plans = _search(spec, pool, wilds, min_naturals_per_group)
    if plans is None:
        return None
    return _materialize(hand, plans)


def _solve_color(hand: list[Card], spec: GroupSpec, min_nat: int) -> Layout | None:
    n = spec.size
    wilds = [c for c in hand if c.is_wild]
    # Anchored: one color to try, not the best of four.
    palette = (spec.color,) if spec.color is not None else tuple(Color)
    for color in palette:
        naturals = [c for c in hand if c.is_number and c.color is color]
        k = min(len(naturals), n)
        need_wild = n - k
        if k < min_nat or need_wild > len(wilds):
            continue
        return [naturals[:k] + wilds[:need_wild]]
    return None


@dataclass
class Meld:
    """A group on the table, and what it means.

    `cards` is what you can see. `kind` plus `rank`/`color`/`lo`/`hi` is what a
    hit has to satisfy: a SET takes its own rank, a COLOR its own color, and a
    RUN extends at either end of the span it actually occupies.
    """

    spec: GroupSpec
    cards: list[Card]
    kind: GroupKind
    rank: int | None = None
    color: Color | None = None
    lo: int | None = None
    hi: int | None = None

    def __iter__(self):
        return iter(self.cards)

    def __len__(self) -> int:
        return len(self.cards)

    def __str__(self) -> str:
        return " ".join(str(c) for c in self.cards)

    def accepts(self, card: Card) -> bool:
        """Can this card be laid onto this group?"""
        if card.is_skip:
            return False  # a Skip is never part of a phase, laid or hit
        if card.is_wild:
            # A wild fits anywhere except a run already pinned to both ends of
            # the deck, where there is no rank left for it to stand in for.
            return self.kind is not GroupKind.RUN or bool(self._open_ends())
        if self.kind is GroupKind.SET:
            return self.rank is None or card.rank == self.rank
        if self.kind is GroupKind.COLOR:
            return self.color is None or card.color is self.color
        return card.rank in self._open_ends()

    def _open_ends(self) -> set[int]:
        ends = set()
        if self.lo is not None and self.lo > MIN_RANK:
            ends.add(self.lo - 1)
        if self.hi is not None and self.hi < MAX_RANK:
            ends.add(self.hi + 1)
        return ends

    def add(self, card: Card) -> None:
        """Lay `card` onto this group, widening a run's span.

        Callers check `accepts` first; this trusts them.
        """
        if self.kind is GroupKind.RUN:
            if card.is_wild:
                # Spend the wild on whichever end is still open, low first --
                # arbitrary, but it has to pick one or the span is a lie.
                ends = sorted(self._open_ends())
                target = ends[0] if ends else None
            else:
                target = card.rank
            if target is not None:
                if self.lo is None or target < self.lo:
                    self.lo = target
                if self.hi is None or target > self.hi:
                    self.hi = target
        self.cards.append(card)


def solve_melds(
    hand: list[Card],
    spec: PhaseSpec,
    *,
    min_naturals_per_group: int = DEFAULT_MIN_NATURALS_PER_GROUP,
) -> list[Meld] | None:
    """Like `solve_phase`, but the groups remember what they are.

    Kept beside `solve_phase` rather than replacing it: everything that only
    needs "which cards leave my hand" still gets a plain list of lists, and the
    two cannot drift, because the layout is built out of these melds.
    """
    kinds = {g.kind for g in spec}
    if GroupKind.COLOR in kinds:
        if kinds != {GroupKind.COLOR} or len(spec) != 1:
            raise NotImplementedError(
                "COLOR groups are only supported as a phase's sole group. "
                "Mixing COLOR with SET/RUN needs joint rank+color search."
            )
        groups = _solve_color(hand, spec[0], min_naturals_per_group)
        if groups is None:
            return None
        natural = next((c for c in groups[0] if c.is_number), None)
        color = spec[0].color or (natural.color if natural else None)
        return [Meld(spec[0], list(groups[0]), GroupKind.COLOR, color=color)]

    wilds = sum(1 for c in hand if c.is_wild)
    pool = Counter(c.rank for c in hand if c.is_number)
    plans = _search(spec, pool, wilds, min_naturals_per_group)
    if plans is None:
        return None

    groups = _materialize(hand, plans)
    melds: list[Meld] = []
    for group_spec, cards, plan in zip(spec, groups, plans):
        kind, value = plan[2]
        if kind == "set":
            melds.append(Meld(group_spec, list(cards), GroupKind.SET, rank=value))
        else:
            melds.append(Meld(group_spec, list(cards), GroupKind.RUN,
                              lo=value, hi=value + group_spec.size - 1))
    return melds


def can_complete(hand: list[Card], phase: int, **kw) -> bool:
    return solve_phase(hand, PHASES[phase], **kw) is not None
