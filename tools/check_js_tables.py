"""Fail if docs/src/data.js has drifted from phase10/data.py.

These tables decide which location a check lands on. A divergence would report
the wrong check and nothing would notice until a seed was half played, so this
compares the two directly rather than against a committed snapshot -- a
snapshot is one more thing that can go stale silently.

    python tools/check_js_tables.py

Exits 1 on any difference. Needs node on PATH.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_python_tables() -> dict:
    # Loaded by path: importing the package pulls in components.py ->
    # worlds.LauncherComponents, which would need an Archipelago checkout for
    # what is just a table comparison.
    spec = importlib.util.spec_from_file_location("p10data", ROOT / "phase10" / "data.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {
        "game": module.GAME_NAME,
        "items": module.ITEM_NAME_TO_ID,
        "locations": module.LOCATION_NAME_TO_ID,
        "tiers": list(module.TIERS),
        "milestones": list(module.HANDS_WON_MILESTONES),
        "baseHandSize": module.BASE_HAND_SIZE,
        "maxSkips": module.MAX_SKIPS,
        "traps": list(module.TRAPS),
        "fillers": list(module.FILLERS),
    }


def load_js_tables() -> dict:
    script = """
    import(process.argv[1]).then((d) => {
      process.stdout.write(JSON.stringify({
        game: d.GAME_NAME,
        items: d.ITEM_NAME_TO_ID,
        locations: d.LOCATION_NAME_TO_ID,
        tiers: d.TIERS,
        milestones: d.HANDS_WON_MILESTONES,
        baseHandSize: d.BASE_HAND_SIZE,
        maxSkips: d.MAX_SKIPS,
        traps: d.TRAPS,
        fillers: d.FILLERS,
      }));
    });
    """
    target = (ROOT / "docs" / "src" / "data.js").as_uri()
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, target],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def main() -> int:
    py = load_python_tables()
    js = load_js_tables()

    problems: list[str] = []
    for field in sorted(py):
        if py[field] != js.get(field):
            if isinstance(py[field], dict):
                only_py = {k: v for k, v in py[field].items() if js.get(field, {}).get(k) != v}
                only_js = {k: v for k, v in js.get(field, {}).items() if py[field].get(k) != v}
                problems.append(f"  {field}: python-only {only_py} | js-only {only_js}")
            else:
                problems.append(f"  {field}: python {py[field]!r} != js {js.get(field)!r}")

    if problems:
        print("docs/src/data.js has drifted from phase10/data.py:")
        print("\n".join(problems))
        return 1

    print(f"data.js matches phase10/data.py "
          f"({len(py['items'])} items, {len(py['locations'])} locations)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
