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

import argparse
import collections
import os
import random
import sys

AP = os.environ.get("AP_ROOT", "C:/Users/turtl/Archipelago")
sys.path.insert(0, AP)
os.chdir(AP)

import ModuleUpdate  # noqa: E402

ModuleUpdate.update_ran = True

from BaseClasses import CollectionState  # noqa: E402
from Fill import distribute_items_restrictive  # noqa: E402
from test.general import setup_multiworld  # noqa: E402

from worlds.phase10 import Phase10World  # noqa: E402
from worlds.phase10.data import (  # noqa: E402
    AP_POINT, DEFAULT_BUFF_POINTS, FILLERS, MAX_STORE_SLOTS, STORE_GENERATED_GATINGS, TRAPS,
    STORE_ALWAYS_OPEN, store_location_name, store_points, store_prices,
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
    if gating == STORE_ALWAYS_OPEN and facts["slots"]:
        for player in range(CARELESS_PLAYERS):
            if not careless_playthrough(multiworld, random.Random(seed * 100 + player)):
                return f"SOFTLOCK (careless player {player})", facts
    return "ok", facts


#: How many random-order buyers play each always-open seed.
CARELESS_PLAYERS = 5


def careless_playthrough(multiworld, rng) -> bool:
    """Play the seed the way an always-open store allows: take every check you
    can reach, and when stuck, buy any slot you can afford, chosen at random.

    The always-open rule counts a slot reachable at three points, enough for
    any one slot, and Archipelago's own beatability check does not model
    spending. So this is what proves the store cannot strand a player who buys
    in the wrong order -- the one way that rule could go wrong.
    """
    world = multiworld.worlds[1]
    slots = int(world.options.store_slots)
    prices = world.fill_slot_data()["store_prices"]
    store = {multiworld.get_location(store_location_name(s), 1): prices[s - 1]
             for s in range(1, slots + 1)}
    others = [l for l in multiworld.get_locations() if l.item and l not in store]
    state, done, received, spent = CollectionState(multiworld), set(), 0, 0
    while True:
        moved = False
        for location in others:
            if location not in done and location.can_reach(state):
                done.add(location)
                state.collect(location.item, True, location)
                received += location.item.name == AP_POINT and location.item.player == 1
                moved = True
        if moved:
            continue
        affordable = [l for l in store if l not in done and store[l] <= received - spent]
        if not affordable:
            return multiworld.can_beat_game(state)
        location = rng.choice(affordable)
        spent += store[location]
        done.add(location)
        state.collect(location.item, True, location)
        received += location.item.name == AP_POINT and location.item.player == 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=1,
                        help="seeds per combination; 150 is what always_open "
                             "was measured at")
    seeds = range(1, parser.parse_args().seeds + 1)
    failures = []
    print(f"{'gating':>11} {'checks':>6} {'asked':>5} {'slots':>5} {'points':>6} "
          f"{'filler':>6} {'locations':>9}  result")
    for gating in STORE_GENERATED_GATINGS:
        for checks in CHECKS:
            for slots in SLOTS:
                for seed in seeds:
                    verdict, facts = run(checks, slots, gating, seed=seed)
                    if verdict != "ok":
                        failures.append(f"{gating} checks={checks} slots={slots} "
                                        f"seed={seed}: {verdict}")
                        break
                print(f"{gating:>11} {checks:>6} {slots:>5} {facts['slots']:>5} "
                      f"{facts['points']:>6} {facts['filler']:>6} "
                      f"{facts['locations']:>9}  {verdict}")

    print()
    if failures:
        for line in failures:
            print(f"FAIL  {line}")
        return 1
    print(f"every store size, in both shapes, over {len(seeds)} seed(s): fills, is "
          f"beatable, leaves nothing unreachable, and an always-open store "
          f"strands none of {CARELESS_PLAYERS} random-order buyers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
