"""Emit turn-by-turn engine traces as fixtures for the JavaScript port.

crosscheck.mjs proves the ported solver agrees about which hands can lay down.
That says nothing about the turn loop -- draw ordering, what a Skip dig does to
the stock, when a hand fails for running out of road. This records the Python
engine playing scripted games and requires the port to reach identical state
after every single action.

The deck is captured and replayed rather than a seed, so nothing depends on
reproducing Mersenne Twister in JavaScript. engine.py is not modified: the deck
is read back out of the freshly-built hand, which is exactly the slicing the
constructor did.

    <AP checkout>/.venv/Scripts/python.exe tools/export_engine_traces.py
"""

from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT = PROJECT_ROOT / "docs" / "test" / "engine_traces.json"

AP = os.environ.get("AP_ROOT", "C:/Users/turtl/Archipelago")
sys.path.insert(0, AP)
os.chdir(AP)

import ModuleUpdate  # noqa: E402

ModuleUpdate.update_ran = True

from worlds.phase10.game.engine import GameConfig, HandState, PhaseHand  # noqa: E402
from worlds.phase10.game.phases import PHASE_COUNT  # noqa: E402

MAX_ACTIONS = 120


def snapshot(hand: PhaseHand) -> dict:
    """Everything observable about the hand, for exact comparison."""
    return {
        "hand": [str(c) for c in hand.hand],
        "discard_top": str(hand.discard_top) if hand.discard_top else None,
        "discard_len": len(hand.discard),
        "stock_len": len(hand.stock),
        "draws_used": hand.draws_used,
        "draws_left": hand.draws_left,
        "state": hand.state.value,
        "drew_this_turn": hand.drew_this_turn,
        "dig_options": [str(c) for c in hand.dig_options] if hand.dig_options else None,
        "skips_played": hand.skips_played,
        "skips_in_hand": hand.skips_in_hand,
        "can_lay_down": hand.can_lay_down(),
        "used_wilds_in_layout": hand.used_wilds_in_layout,
        "events": [{"kind": e.kind, "detail": e.detail} for e in hand.events],
    }


def deck_of(hand: PhaseHand, config: GameConfig) -> list[str]:
    """Recover the deal. At construction the hand is deck[:hand_size] (plus
    granted Skips appended), discard is [rest[0]] and stock is rest[1:]."""
    dealt = hand.hand[: config.hand_size]
    return [str(c) for c in dealt] + [str(c) for c in hand.discard] + [str(c) for c in hand.stock]


def play(hand: PhaseHand, rng: random.Random) -> list[dict]:
    """Drive the hand with legal-but-varied actions, recording each step."""
    steps = []
    for _ in range(MAX_ACTIONS):
        if hand.state is not HandState.IN_PROGRESS:
            break

        if hand.dig_pending:
            index = rng.randrange(len(hand.dig_options))
            hand.take_dug(index)
            steps.append({"action": "take_dug", "index": index, "after": snapshot(hand)})
            continue

        if hand.drew_this_turn:
            index = rng.randrange(len(hand.hand))
            card = hand.hand[index]
            hand.discard_card(card)
            steps.append({"action": "discard", "card": str(card), "after": snapshot(hand)})
            continue

        choices = ["draw"]
        if hand.discard_top is not None and hand.config.allow_discard_draw:
            choices.append("draw_discard")
        if hand.skips_in_hand and hand.stock:
            choices += ["skip", "skip"]        # weight digs so they get exercised
        if hand.can_lay_down():
            choices += ["lay", "lay", "lay"]   # and finish reasonably often

        action = rng.choice(choices)
        if action == "lay":
            hand.lay_down()
            steps.append({"action": "lay_down", "after": snapshot(hand)})
        elif action == "skip":
            hand.play_skip()
            steps.append({"action": "play_skip", "after": snapshot(hand)})
        elif action == "draw_discard":
            hand.draw(from_discard=True)
            steps.append({"action": "draw", "from_discard": True, "after": snapshot(hand)})
        else:
            if not hand.stock:
                hand.mark_failed("stock_empty")
                steps.append({"action": "mark_failed", "reason": "stock_empty",
                              "after": snapshot(hand)})
                break
            hand.draw()
            steps.append({"action": "draw", "from_discard": False, "after": snapshot(hand)})
    return steps


def main() -> int:
    rng = random.Random(20260914)
    traces = []

    configs = [
        GameConfig(),
        GameConfig(hand_size=12, wilds_in_deck=4, max_draws=12, starting_skips=2),
        GameConfig(hand_size=10, wilds_in_deck=0, max_draws=8, starting_skips=0),
        GameConfig(hand_size=13, wilds_in_deck=8, max_draws=30, starting_skips=3),
        GameConfig(hand_size=10, wilds_in_deck=2, max_draws=6, min_naturals_per_group=0),
        GameConfig(hand_size=11, wilds_in_deck=5, max_draws=20, allow_discard_draw=False),
    ]

    for config in configs:
        for phase in range(1, PHASE_COUNT + 1):
            for _ in range(4):
                hand = PhaseHand(phase, config, random.Random(rng.randrange(1 << 30)))
                deck = deck_of(hand, config)
                initial = snapshot(hand)
                steps = play(hand, rng)
                traces.append({
                    "phase": phase,
                    "config": {
                        "handSize": config.hand_size,
                        "wildsInDeck": config.wilds_in_deck,
                        "maxDraws": config.max_draws,
                        "startingSkips": config.starting_skips,
                        "skipsInDeck": config.skips_in_deck,
                        "minNaturalsPerGroup": config.min_naturals_per_group,
                        "allowDiscardDraw": config.allow_discard_draw,
                    },
                    "deck": deck,
                    "initial": initial,
                    "steps": steps,
                })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "note": "Emitted by tools/export_engine_traces.py from the Python engine.",
        "traces": traces,
    }, indent=1), encoding="utf-8")

    total_steps = sum(len(t["steps"]) for t in traces)
    outcomes: dict[str, int] = {}
    for t in traces:
        final = t["steps"][-1]["after"]["state"] if t["steps"] else t["initial"]["state"]
        outcomes[final] = outcomes.get(final, 0) + 1

    print(f"wrote {OUT}")
    print(f"  {len(traces)} traces, {total_steps} actions")
    print(f"  final states: {outcomes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
