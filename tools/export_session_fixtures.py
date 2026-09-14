"""Record the Python session's behaviour for the JS port to replay.

The session decides which location IDs a finished hand is worth. Getting that
wrong reports the wrong check, which nothing notices until a seed is half
played -- so the port is compared against Python rather than merely tested
against my own expectations of it.

Outcomes are forced rather than played out: tiers and IDs are a pure function
of (state, wilds used, draws used, budget, options), so no deck is involved and
the two engines' RNGs never have to agree.

    python tools/export_session_fixtures.py
"""

from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT = PROJECT_ROOT / "docs" / "test" / "session_fixtures.json"

# session.py uses relative imports, so it needs real package context. Borrow
# the route the other exporters take rather than inventing a second one.
AP = os.environ.get("AP_ROOT", "C:/Users/turtl/Archipelago")
sys.path.insert(0, AP)
os.chdir(AP)

import ModuleUpdate  # noqa: E402

ModuleUpdate.update_ran = True

from worlds.phase10.client.session import Phase10Session  # noqa: E402
from worlds.phase10.data import (  # noqa: E402
    EXTRA_DRAW,
    HAND_SIZE_UPGRADE,
    LEAN_DEAL,
    PHASE_LOCK,
    PHASE_UNLOCK,
    SKIP_CARD,
    WILD_CARD,
    WILD_THEFT,
)
from worlds.phase10.game.engine import HandState  # noqa: E402

STATES = ["phase_laid", "went_out", "failed"]


def make(slot, items):
    s = Phase10Session.from_slot_data(slot, random.Random(0))
    s.set_items(items)
    return s


def config_cases():
    item_sets = [
        [],
        [WILD_CARD] * 3,
        [WILD_CARD] * 20,
        [EXTRA_DRAW] * 5,
        [HAND_SIZE_UPGRADE] * 2,
        [SKIP_CARD] * 9,
        [LEAN_DEAL],
        [WILD_THEFT, WILD_CARD, WILD_CARD],
        [LEAN_DEAL, WILD_THEFT] + [WILD_CARD] * 4 + [EXTRA_DRAW] * 2 + [SKIP_CARD],
    ]
    out = []
    for starting_draws in (2, 4, 9):
        for items in item_sets:
            s = make({"goal": 0, "starting_draws": starting_draws, "checks_per_phase": 4}, items)
            c = s.config
            out.append({
                "starting_draws": starting_draws,
                "items": items,
                "config": {
                    "handSize": c.hand_size,
                    "wildsInDeck": c.wilds_in_deck,
                    "maxDraws": c.max_draws,
                    "startingSkips": c.starting_skips,
                },
            })
    return out


def tier_cases():
    out = []
    for checks in (2, 3, 4):
        for state in STATES:
            for wilds in (0, 2):
                for draws, budget in ((0, 8), (4, 8), (8, 8), (1, 1)):
                    s = make(
                        {"goal": 0, "starting_draws": budget, "checks_per_phase": checks},
                        [PHASE_UNLOCK.format(3)],
                    )
                    hand = s.start_hand(3)
                    hand.state = HandState(state)
                    hand.used_wilds_in_layout = wilds
                    hand.draws_used = draws
                    out.append({
                        "checks_per_phase": checks, "state": state, "wilds": wilds,
                        "draws": draws, "budget": budget,
                        "tiers": s.earned_tiers(hand),
                    })
    return out


def sequence_cases():
    """Full settle sequences: which IDs come back, and when the goal trips."""
    scripts = [
        {"goal": 0, "steps": [(p, "phase_laid") for p in range(1, 11)]},
        {"goal": 1, "steps": [(1, "phase_laid"), (10, "went_out")]},
        {"goal": 0, "steps": [(2, "phase_laid")] * 6},
        {"goal": 0, "steps": [(4, "failed"), (4, "phase_laid"), (4, "went_out")]},
    ]
    out = []
    for script in scripts:
        s = make(
            {"goal": script["goal"], "starting_draws": 8, "checks_per_phase": 4},
            [PHASE_UNLOCK.format(p) for p in range(1, 11)] + [PHASE_LOCK],
        )
        steps = []
        for phase, state in script["steps"]:
            hand = s.start_hand(phase)
            hand.state = HandState(state)
            hand.used_wilds_in_layout = 1
            hand.draws_used = 5
            hand.hand = []
            ids = s.finish_hand(hand)
            steps.append({
                "phase": phase, "state": state, "ids": sorted(ids),
                "handsWon": s.hands_won, "lockedPhase": s.locked_phase,
                "goalMet": s.goal_met,
            })
        out.append({"goal": script["goal"], "steps": steps})
    return out


def main() -> int:
    payload = {
        "config": config_cases(),
        "tiers": tier_cases(),
        "sequences": sequence_cases(),
    }
    OUT.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"wrote {OUT.relative_to(PROJECT_ROOT)}: "
          f"{len(payload['config'])} config, {len(payload['tiers'])} tier, "
          f"{sum(len(s['steps']) for s in payload['sequences'])} settle cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
