"""Headless runner: play a hand verbosely, or sweep difficulty.

    python -m phase10.play_in_console            # one narrated hand
    python -m phase10.play_in_console --sweep    # phase x wilds success table
    python -m phase10.play_in_console --draws    # phase x draw-budget table
"""

from __future__ import annotations

import argparse
import random
import sys

from .autoplay import play_hand, success_rate
from .engine import GameConfig, HandState
from .phases import PHASES, phase_description


def narrate(phase: int, cfg: GameConfig, seed: int) -> None:
    rng = random.Random(seed)
    h = play_hand(phase, cfg, rng)
    print(f"Phase {phase}: {phase_description(phase)}")
    print(f"  result     {h.state.value}")
    print(f"  draws used {h.draws_used}/{cfg.max_draws}")
    if h.layout:
        for i, g in enumerate(h.layout, 1):
            print(f"  group {i}    {' '.join(str(c) for c in g)}")
    if h.hand:
        print(f"  left over  {' '.join(str(c) for c in h.hand)}")
    for e in h.events:
        print(f"  event      {e.kind} {e.detail}")


def sweep_wilds(trials: int, cfg: GameConfig) -> None:
    wild_counts = [0, 1, 2, 4, 6, 8]
    print(f"Success rate by phase x wilds in deck  "
          f"(hand {cfg.hand_size}, max_draws {cfg.max_draws}, {trials} hands each)\n")
    print("phase  " + "".join(f"{w:>7}W" for w in wild_counts) + "   requirement")
    for p in range(1, 11):
        row = []
        for w in wild_counts:
            c = GameConfig(hand_size=cfg.hand_size, wilds_in_deck=w,
                           skips_in_deck=cfg.skips_in_deck, max_draws=cfg.max_draws)
            row.append(success_rate(p, c, trials, seed=1000 + p))
        cells = "".join(f"{r:>7.0%} " for r in row)
        print(f"{p:>5}  {cells}  {phase_description(p)}")


def sweep_draws(trials: int, cfg: GameConfig) -> None:
    budgets = [1, 2, 3, 5, 8, 12, 20]
    print(f"Success rate by phase x draw budget  "
          f"(hand {cfg.hand_size}, wilds {cfg.wilds_in_deck}, {trials} hands each)\n")
    print("phase  " + "".join(f"{b:>7}d" for b in budgets))
    for p in range(1, 11):
        row = []
        for b in budgets:
            c = GameConfig(hand_size=cfg.hand_size, wilds_in_deck=cfg.wilds_in_deck,
                           skips_in_deck=cfg.skips_in_deck, max_draws=b)
            row.append(success_rate(p, c, trials, seed=2000 + p))
        print(f"{p:>5}  " + "".join(f"{r:>7.0%} " for r in row))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--draws", action="store_true")
    ap.add_argument("--phase", type=int, default=1)
    ap.add_argument("--trials", type=int, default=300)
    ap.add_argument("--hand-size", type=int, default=10)
    ap.add_argument("--wilds", type=int, default=8)
    ap.add_argument("--max-draws", type=int, default=20)
    ap.add_argument("--skips", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)

    cfg = GameConfig(hand_size=a.hand_size, wilds_in_deck=a.wilds,
                     skips_in_deck=a.skips, max_draws=a.max_draws)
    if a.sweep:
        sweep_wilds(a.trials, cfg)
    elif a.draws:
        sweep_draws(a.trials, cfg)
    else:
        narrate(a.phase, cfg, a.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
