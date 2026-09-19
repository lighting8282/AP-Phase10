"""Emit the Python solver's verdicts as fixtures for the JavaScript port.

The JS engine in docs/src is a reimplementation, and a reimplementation can
drift from the rules the measured difficulty tables were produced with. This
writes what the reference engine says for a spread of hands, and
docs/test/crosscheck.mjs requires the port to agree on every one.

Deliberately no shared RNG: the fixture records the concrete hand, so the two
engines are compared as pure functions and nothing depends on reproducing
Mersenne Twister in JavaScript.

    <AP checkout>/.venv/Scripts/python.exe tools/export_fixtures.py
"""

from __future__ import annotations

import json
import os
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT = PROJECT_ROOT / "docs" / "test" / "fixtures.json"

# phases.py uses relative imports, so it needs real package context. Borrow the
# route tests/ui_check.py takes rather than inventing a second one.
AP = os.environ.get("AP_ROOT", "C:/Users/turtl/Archipelago")
sys.path.insert(0, AP)
os.chdir(AP)

import ModuleUpdate  # noqa: E402

ModuleUpdate.update_ran = True

from worlds.phase10.game.cards import (  # noqa: E402
    SKIP,
    WILD,
    Color,
    build_deck,
    number_card,
)
from worlds.phase10.game.phases import PHASE_COUNT, PHASES, solve_phase  # noqa: E402

MIN_NATURAL_VARIANTS = (0, 1)


def card_key(card) -> str:
    return str(card)


def random_hands(rng: random.Random) -> list[list]:
    """A spread of hands: ordinary deals plus the cases that break solvers."""
    hands: list[list] = []

    # Ordinary deals of varying size from a full shuffled deck.
    for size in (10, 11, 12, 13, 14):
        for _ in range(60):
            deck = build_deck()
            rng.shuffle(deck)
            hands.append(deck[:size])

    # Wild-heavy hands, where min_naturals and the pure-wild branch matter.
    for wild_count in range(0, 9):
        for _ in range(25):
            deck = [c for c in build_deck() if not c.is_wild]
            rng.shuffle(deck)
            hands.append([WILD] * wild_count + deck[: max(0, 12 - wild_count)])

    # Degenerate shapes.
    hands.append([])
    hands.append([WILD] * 8)
    hands.append([SKIP] * 4)
    hands.append([SKIP] * 4 + [WILD] * 8)

    # Exactly-a-run and exactly-a-set, plus the scarce-rank case the solver
    # docstring calls out: RUN(4) of 3-4-5-6 beside SET(3) of 5s with only
    # three 5s in hand, so the run must spend a wild on its 5.
    hands.append([number_card(r, Color.RED) for r in range(1, 10)])
    hands.append([number_card(7, c) for c in Color] + [number_card(7, Color.RED)])
    hands.append(
        [number_card(3, Color.RED), number_card(4, Color.BLUE),
         number_card(5, Color.RED), number_card(5, Color.BLUE),
         number_card(5, Color.GREEN), number_card(6, Color.YELLOW), WILD]
    )

    # Runs that need a wild in the middle, and ones that would need wraparound.
    hands.append([number_card(r, Color.BLUE) for r in (1, 2, 3, 5, 6, 7, 8)] + [WILD])
    hands.append([number_card(r, Color.GREEN) for r in (10, 11, 12)]
                 + [number_card(r, Color.GREEN) for r in (1, 2, 3, 4)])

    # Colour phases: exactly seven of one colour, and six plus a wild.
    hands.append([number_card(r, Color.YELLOW) for r in range(1, 8)])
    hands.append([number_card(r, Color.YELLOW) for r in range(1, 7)] + [WILD])
    return hands


def main() -> int:
    rng = random.Random(20260914)
    hands = random_hands(rng)

    cases = []
    for hand in hands:
        verdicts = {}
        for min_nat in MIN_NATURAL_VARIANTS:
            verdicts[str(min_nat)] = [
                solve_phase(hand, PHASES[p], min_naturals_per_group=min_nat) is not None
                for p in range(1, PHASE_COUNT + 1)
            ]
        cases.append({"hand": [card_key(c) for c in hand], "verdicts": verdicts})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "note": "Emitted by tools/export_fixtures.py from the Python engine. "
                        "Regenerate whenever the solver changes.",
                "min_naturals_variants": list(MIN_NATURAL_VARIANTS),
                "phases": list(range(1, PHASE_COUNT + 1)),
                "cases": cases,
            },
            indent=1,
        ),
        encoding="utf-8",
    )

    total = len(cases) * len(MIN_NATURAL_VARIANTS) * 10
    yes = sum(
        sum(v) for c in cases for v in c["verdicts"].values()
    )
    print(f"wrote {OUT}")
    print(f"  {len(cases)} hands x {len(MIN_NATURAL_VARIANTS)} settings x 10 phases "
          f"= {total} verdicts")
    print(f"  {yes} solvable, {total - yes} not "
          f"({100 * yes / total:.1f}% / {100 * (total - yes) / total:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
