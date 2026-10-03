"""Generate across the store's whole option grid and check the pool balances.

The store's sizing is arithmetic that depends on three separate things -- the
location count, the power-item floors, and the price ladder -- and none of them
lives next to the others. Change any one and the store either stops fitting or
quietly stops costing anything. This runs the real fill over every combination
and reports what came out, so the drift shows up here rather than in a seed.

    python tools/check_store_balance.py

Needs an Archipelago source checkout (AP_ROOT, default C:/Users/turtl/Archipelago)
with this world available to it.
"""

from __future__ import annotations

import collections
import os
import sys

AP = os.environ.get("AP_ROOT", "C:/Users/turtl/Archipelago")
sys.path.insert(0, AP)
os.chdir(AP)

import ModuleUpdate  # noqa: E402

ModuleUpdate.update_ran = True

from Fill import distribute_items_restrictive  # noqa: E402
from test.general import setup_multiworld  # noqa: E402

from worlds.phase10 import Phase10World  # noqa: E402
from worlds.phase10.data import (  # noqa: E402
    AP_POINT, DEFAULT_BUFF_POINTS, FILLERS, MAX_STORE_SLOTS, STORE_GATINGS, TRAPS,
    store_points, store_prices,
)

CHECKS = (1, 2, 3, 4)
SLOTS = (0, 4, 6, MAX_STORE_SLOTS)


def run(checks_per_phase: int, slots: int, gating: str,
        seed: int) -> tuple[str, dict]:
    multiworld = setup_multiworld(
        Phase10World,
        options={"checks_per_phase": checks_per_phase, "store_slots": slots,
                 "store_gating": gating},
        seed=seed,
    )
    world = multiworld.worlds[1]
    pool = collections.Counter(item.name for item in multiworld.itempool)
    locations = [l for l in multiworld.get_locations(1) if l.address is not None]
    facts = {
        "slots": int(world.options.store_slots),
        "points": pool[AP_POINT],
        "filler": sum(c for n, c in pool.items() if n in FILLERS or n in TRAPS),
        "locations": len(locations),
    }
    if len(multiworld.itempool) != len(multiworld.get_unfilled_locations(1)):
        return "POOL MISMATCH", facts
    # What the slots cost is the floor -- below it some slot could never be
    # bought -- and store_points is the ceiling: the slots, the slack and the
    # card budget. A trimmed store gives up the spare points first, so anything
    # between the two is right. The ceiling left out the card budget from the
    # day the budget was added, so this reported every untrimmed store as
    # wrong; it needs a checkout to run, and nothing that could run it did.
    if facts["slots"]:
        floor = sum(store_prices(facts["slots"], gating))
        ceiling = store_points(facts["slots"], DEFAULT_BUFF_POINTS, gating)
        if not floor <= facts["points"] <= ceiling:
            return f"points {facts['points']} outside {floor}..{ceiling}", facts

    distribute_items_restrictive(multiworld)
    if not multiworld.can_beat_game():
        return "UNBEATABLE", facts
    state = multiworld.get_all_state(False)
    unreachable = [l.name for l in locations if not l.can_reach(state)]
    if unreachable:
        return f"UNREACHABLE {unreachable[0]}", facts
    return "ok", facts


def main() -> int:
    failures = []
    print(f"{'gating':>11} {'checks':>6} {'asked':>5} {'slots':>5} {'points':>6} "
          f"{'filler':>6} {'locations':>9}  result")
    for gating in STORE_GATINGS:
        for checks in CHECKS:
            for slots in SLOTS:
                verdict, facts = run(checks, slots, gating, seed=1)
                if verdict != "ok":
                    failures.append(f"{gating} checks={checks} slots={slots}: {verdict}")
                print(f"{gating:>11} {checks:>6} {slots:>5} {facts['slots']:>5} "
                      f"{facts['points']:>6} {facts['filler']:>6} "
                      f"{facts['locations']:>9}  {verdict}")

    print()
    if failures:
        for line in failures:
            print(f"FAIL  {line}")
        return 1
    print("every store size, in both shapes, fills, is beatable, and leaves "
          "nothing unreachable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
