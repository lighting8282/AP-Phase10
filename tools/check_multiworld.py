"""Generate the multiworld in tests/yaml/multi and check it is a real one.

Every seed this project generated for a long time held a single slot of a
single game, which is the one arrangement that cannot exercise the thing most
likely to break: fill placing this world's items into someone else's
locations, and someone else's into this world's. Two AP_Phase10 slots with
different options are in the set deliberately -- same game twice is where item
IDs, option-dependent location counts and progression balancing collide.

Generation succeeding is itself the beatability proof: Archipelago validates
completion and builds a playthrough before it writes anything.

    python tools/check_multiworld.py

Needs an Archipelago source checkout (AP_ROOT, default C:/Users/turtl/Archipelago)
with this world available to it.
"""

from __future__ import annotations

import collections
import os
import re
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
YAMLS = PROJECT_ROOT / "tests" / "yaml" / "multi"
GAME = "AP_Phase10"

AP = os.environ.get("AP_ROOT", "C:/Users/turtl/Archipelago")
sys.path.insert(0, AP)
os.chdir(AP)

import ModuleUpdate  # noqa: E402

ModuleUpdate.update_ran = True

import Generate  # noqa: E402
from Main import main as ERmain  # noqa: E402

PLACEMENT = re.compile(r"^(.+?) \(([^)]+)\): (.+?) \(([^)]+)\)$", re.M)


def generate(out_dir: Path) -> Path:
    sys.argv = [
        "Generate.py",
        "--player_files_path", str(YAMLS),
        "--outputpath", str(out_dir),
        "--seed", "20260917",
    ]
    erargs, seed = Generate.main()
    ERmain(erargs, seed)

    spoilers = list(out_dir.glob("*Spoiler.txt"))
    if not spoilers:
        import zipfile

        for zip_path in out_dir.glob("*.zip"):
            zipfile.ZipFile(zip_path).extractall(out_dir)
        spoilers = list(out_dir.glob("*Spoiler.txt"))
    if not spoilers:
        raise SystemExit("generation produced no spoiler to inspect")
    return spoilers[0]


def check(spoiler: Path) -> list[str]:
    text = spoiler.read_text(encoding="utf-8")
    problems: list[str] = []

    slots = dict(zip(
        re.findall(r"^Player \d+: (.+)$", text, re.M),
        re.findall(r"^Game:\s+(.+)$", text, re.M),
    ))
    print(f"  slots: {len(slots)}")
    for name, game in slots.items():
        print(f"    {name} -- {game}")

    ours = [n for n, g in slots.items() if g == GAME]
    if len(ours) < 2:
        problems.append(f"expected at least two {GAME} slots, found {len(ours)}")
    if len(set(slots.values())) < 2:
        problems.append("only one game in the seed; this is not a multiworld")

    rows = PLACEMENT.findall(text)
    print(f"  placements: {len(rows)}")

    crossings = collections.Counter()
    for _loc, loc_player, _item, item_player in rows:
        if loc_player != item_player:
            crossings[(item_player, loc_player)] += 1

    sent = sum(n for (src, _dst), n in crossings.items() if src in ours)
    received = sum(n for (_src, dst), n in crossings.items() if dst in ours)
    between_ours = sum(
        n for (src, dst), n in crossings.items() if src in ours and dst in ours
    )
    print(f"  {GAME} items placed elsewhere : {sent}")
    print(f"  foreign items placed in {GAME}: {received}")
    print(f"  between the two {GAME} slots  : {between_ours}")

    if not sent:
        problems.append(f"no {GAME} item was placed in another world")
    if not received:
        problems.append(f"no other world's item was placed in a {GAME} location")
    if not between_ours:
        problems.append(f"nothing crossed between the two {GAME} slots")

    return problems


def main() -> int:
    global YAMLS
    if len(sys.argv) > 1:
        # Overridable so the checks themselves can be shown to fail -- pointed
        # at the single-slot set, every cross-world assertion must fire.
        YAMLS = Path(sys.argv[1])
        if not YAMLS.is_absolute():
            YAMLS = PROJECT_ROOT / YAMLS

    with tempfile.TemporaryDirectory(prefix="p10multi") as tmp:
        spoiler = generate(Path(tmp))
        problems = check(spoiler)

    if problems:
        print("\nmultiworld check FAILED:")
        for p in problems:
            print("  " + p)
        return 1
    print("\nmultiworld generates, and items cross in both directions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
