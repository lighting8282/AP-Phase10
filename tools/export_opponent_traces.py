"""Record Python opponent turns so the JS port can be replayed against them.

The two opponent modules have to agree turn for turn or the browser client and
the desktop client disagree about who won a round off the same seed. Recording
the concrete deck rather than a seed keeps `opponents.py` free of test hooks --
the JS side deals the identical deck and must produce the identical turns.

    <AP checkout>/.venv/Scripts/python.exe tools/export_opponent_traces.py
"""

from __future__ import annotations

import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "phase10"))

from game.cards import shuffled_deck  # noqa: E402
from game.engine import GameConfig, Table  # noqa: E402
from game.opponents import OpponentSkill, build_opponents  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "test" / "opponent_traces.json"


def card_json(card):
    if card.is_wild:
        return {"kind": "wild"}
    if card.is_skip:
        return {"kind": "skip"}
    return {"kind": "number", "rank": card.rank, "color": card.color.value}


def trace(seed: int, phases: list[int], hand_size: int, awareness: float,
          error: float) -> dict:
    rng = random.Random(seed)
    cfg = GameConfig(hand_size=hand_size, max_draws=99)
    deck = shuffled_deck(rng, cfg.wilds_in_deck, cfg.skips_in_deck)

    table = Table()
    # A fixed RNG stream for the policy's coin flips, separate from the deal,
    # so the JS side can reproduce it from the same recorded numbers.
    rolls = [random.Random(seed + 1000).random() for _ in range(4000)]
    it = iter(rolls)

    class Fixed:
        def random(self):
            return next(it)

    skill = OpponentSkill("t", awareness, error)
    table.seats = build_opponents(len(phases), list(phases), cfg, Fixed(), skill)
    table.reset(stock=list(deck[1:]), discard=[deck[0]])
    table.deal_seats(hand_size)

    turns = []
    for _ in range(60):
        winner = table.end_of_turn()
        turns.append({
            "seats": [
                {"hand": len(s.hand), "laid": s.laid_down, "out": s.went_out,
                 "score": s.score}
                for s in table.seats
            ],
            "discard_top": card_json(table.discard[-1]) if table.discard else None,
            "stock": len(table.stock),
            "winner": winner.name if winner else None,
        })
        if winner is not None:
            break

    return {
        "seed": seed, "phases": phases, "hand_size": hand_size,
        "awareness": awareness, "error": error,
        "deck": [card_json(c) for c in deck],
        "rolls": rolls,
        "turns": turns,
    }


def main() -> None:
    cases = []
    for seed in range(12):
        cases.append(trace(seed, [1, 1, 1], 10, 0.7, 0.25))
    for seed in range(12, 18):
        cases.append(trace(seed, [3, 5, 7], 10, 1.0, 0.0))
    for seed in range(18, 22):
        cases.append(trace(seed, [2], 11, 0.4, 0.5))

    OUT.write_text(json.dumps(cases), encoding="utf-8")
    turns = sum(len(c["turns"]) for c in cases)
    print(f"{OUT.relative_to(OUT.parents[2])}  {len(cases)} traces  {turns} turns")


if __name__ == "__main__":
    main()
