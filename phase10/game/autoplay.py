"""A greedy autoplayer.

Not meant to be a strong player -- meant to be a *consistent* one, so that
simulated success rates are a usable proxy for phase difficulty when tuning
Archipelago logic rules.

Policy: if holding a Skip, dig with it -- a choice of three beats a blind draw,
and the Skip is dead weight otherwise. Failing that, draw the discard top only
when it strictly reduces `cards_short`, else draw stock. Discard whichever card
leaves `cards_short` lowest, breaking ties by dumping the highest point value.
"""

from __future__ import annotations

import random

from .cards import Card
from .engine import GameConfig, HandState, PhaseHand, cards_short
from .phases import PHASES, PhaseSpec


def _short(hand: list[Card], spec: PhaseSpec, cfg: GameConfig) -> int:
    return cards_short(hand, spec, cfg.min_naturals_per_group)


def choose_discard(hand: list[Card], spec: PhaseSpec, cfg: GameConfig) -> Card:
    best, best_key = None, None
    for card in hand:
        remaining = list(hand)
        remaining.remove(card)
        key = (_short(remaining, spec, cfg), -card.points)
        if best_key is None or key < best_key:
            best, best_key = card, key
    return best


def choose_dig(options: list[Card], hand: list[Card], spec: PhaseSpec, cfg: GameConfig) -> int:
    """Pick the revealed card that leaves the hand closest to the phase."""
    return min(
        range(len(options)),
        key=lambda i: (_short(hand + [options[i]], spec, cfg), -options[i].points),
    )


def play_out(h: PhaseHand) -> PhaseHand:
    """Play an already-dealt hand to its conclusion.

    Split out from `play_hand` so the client's /auto and /grind drive the same
    policy the difficulty measurements were taken with -- two copies of this
    loop drifted apart once already.
    """
    cfg, spec = h.config, h.spec

    while h.state is HandState.IN_PROGRESS:
        if h.can_lay_down():
            h.lay_down()
            break
        if not h.stock:
            h.mark_failed("stock_empty")
            break

        # A Skip in hand is strictly better spent than held: it buys a choice
        # of three for no draw at all, and sheds itself as the discard.
        if h.skips_in_hand:
            options = h.play_skip()
            h.take_dug(choose_dig(options, h.hand, spec, cfg))
            if h.can_lay_down():
                h.lay_down()
            continue

        base = _short(h.hand, spec, cfg)
        top = h.discard_top
        take_discard = False
        if top is not None and cfg.allow_discard_draw:
            take_discard = _short(h.hand + [top], spec, cfg) < base

        h.draw(from_discard=take_discard)

        if h.can_lay_down():
            h.lay_down()
            break
        h.discard_card(choose_discard(h.hand, spec, cfg))

    return h


def play_hand(phase: int, cfg: GameConfig, rng: random.Random) -> PhaseHand:
    return play_out(PhaseHand(phase, cfg, rng))


def success_rate(phase: int, cfg: GameConfig, trials: int, seed: int = 0) -> float:
    rng = random.Random(seed)
    wins = sum(
        1 for _ in range(trials)
        if play_hand(phase, cfg, rng).state in (HandState.PHASE_LAID, HandState.WENT_OUT)
    )
    return wins / trials
