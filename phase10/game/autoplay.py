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

    def settle_phase() -> None:
        """Lay down if we can, then shed whatever the table will take."""
        if not h.laid and h.can_lay_down():
            h.lay_down()
        if h.laid:
            hit_everything(h)

    while h.state is HandState.IN_PROGRESS:
        settle_phase()
        if h.state is not HandState.IN_PROGRESS:
            break
        if not h.stock:
            h.mark_failed("stock_empty")
            break

        # A Skip in hand is better spent than held either way -- it is fifteen
        # points to be caught with and never part of a phase -- but the two
        # modes spend it differently, and the autoplayer has to know which it
        # is in or it plays a move the engine refuses.
        if h.skips_in_hand and cfg.skip_mode == "dig":
            # The dig buys a choice of three for no draw at all, and the Skip
            # sheds itself as the discard.
            options = h.play_skip()
            h.take_dug(choose_dig(options, h.hand, spec, cfg))
            continue

        base = _short(h.hand, spec, cfg)
        top = h.discard_top
        take_discard = False
        if top is not None and cfg.allow_discard_draw and not top.is_skip:
            # A spent Skip is not available: the engine refuses it, and this
            # is a sweep of thousands of hands, so a refusal here is a crashed
            # measurement rather than a wasted turn.
            take_discard = _short(h.hand + [top], spec, cfg) < base

        h.draw(from_discard=take_discard)
        settle_phase()
        if h.state is not HandState.IN_PROGRESS:
            break
        if h.hand:
            # In deny mode the Skip *is* the discard: throwing it is how it is
            # played, so it goes the moment there is nothing better to throw,
            # and it is aimed at whoever is closest to going out.
            held_skip = next((c for c in h.hand if c.is_skip), None) \
                if cfg.skip_mode == "deny" else None
            h.discard_card(held_skip or choose_discard(h.hand, spec, cfg))
            if h.deny_pending:
                h.deny_seat(_best_deny(h))

    return h


def _best_deny(h: PhaseHand) -> int:
    """Which seat a thrown Skip should cost a turn, as an index into the
    targets the engine offers.

    The same reading the seats use on each other: down first, then whoever is
    holding least. Everything here is face up, so this is not the autoplayer
    seeing hands it should not.
    """
    targets = h.deny_targets()
    best, choice = None, 0
    for index, seat in enumerate(targets):
        rank = (0 if getattr(seat, "laid_down", False) else 1, len(seat.hand))
        if best is None or rank < best:
            best, choice = rank, index
    return choice


def hit_everything(h: PhaseHand) -> int:
    """Play every card that legally extends a group already on the table.

    Repeated rather than a single pass: hitting a run at one end opens the
    next rank along, so one sweep would leave behind cards the very next check
    would accept. Once the phase is down `cards_short` is zero for every
    subset, so there is nothing to weigh -- shedding is pure gain.
    """
    played = 0
    moved = True
    while moved and h.hand and h.state is HandState.IN_PROGRESS:
        moved = False
        for card in list(h.hand):
            for meld in h.hittable():
                if meld.accepts(card):
                    h.hit(card, meld)
                    played += 1
                    moved = True
                    break
            if moved:
                break
    return played


def play_hand(phase: int, cfg: GameConfig, rng: random.Random) -> PhaseHand:
    return play_out(PhaseHand(phase, cfg, rng))


def success_rate(phase: int, cfg: GameConfig, trials: int, seed: int = 0) -> float:
    rng = random.Random(seed)
    wins = sum(
        1 for _ in range(trials)
        if play_hand(phase, cfg, rng).state in (HandState.PHASE_LAID, HandState.WENT_OUT)
    )
    return wins / trials
