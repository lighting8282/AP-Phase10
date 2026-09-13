"""Phase definitions and the phase-satisfaction solver.

A phase is a tuple of groups. A group is one of:
    SET(n)    n cards of the same rank, colors irrelevant
    RUN(n)    n cards of consecutive ranks, colors irrelevant, no wraparound
    COLOR(n)  n cards of the same color, ranks irrelevant

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

    def __str__(self) -> str:
        noun = {GroupKind.SET: "set", GroupKind.RUN: "run", GroupKind.COLOR: "cards"}[self.kind]
        if self.kind is GroupKind.COLOR:
            return f"{self.size} cards of one color"
        return f"{noun} of {self.size}"


def SET(n: int) -> GroupSpec:
    return GroupSpec(GroupKind.SET, n)


def RUN(n: int) -> GroupSpec:
    return GroupSpec(GroupKind.RUN, n)


def COLOR(n: int) -> GroupSpec:
    return GroupSpec(GroupKind.COLOR, n)


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
}


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

_RankPlan = tuple[Counter, int]  # (natural ranks used, wilds used)


def _set_candidates(spec: GroupSpec, pool: Counter, wilds: int, min_nat: int):
    n = spec.size
    # A group built purely from wilds has no rank to anchor on, so the per-rank
    # loop below (which starts at k >= 1) can never emit it. Emit it once here.
    if min_nat <= 0 and wilds >= n:
        yield Counter(), n
    for rank, avail in pool.items():
        lo = max(min_nat, 1, n - wilds)
        hi = min(avail, n)
        for k in range(lo, hi + 1):
            yield Counter({rank: k}), n - k


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
                yield used, len(wild_at)


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
    for used, used_wilds in _candidates(head, pool, wilds, min_nat):
        sub = _search(tail, pool - used, wilds - used_wilds, min_nat)
        if sub is not None:
            return [(used, used_wilds)] + sub
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
    for used, used_wilds in plans:
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
    for color in Color:
        naturals = [c for c in hand if c.is_number and c.color is color]
        k = min(len(naturals), n)
        need_wild = n - k
        if k < min_nat or need_wild > len(wilds):
            continue
        return [naturals[:k] + wilds[:need_wild]]
    return None


def can_complete(hand: list[Card], phase: int, **kw) -> bool:
    return solve_phase(hand, PHASES[phase], **kw) is not None
