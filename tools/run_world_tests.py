"""Run as much of phase10/test/ as does not need a real Archipelago.

    python tools/run_world_tests.py
    python tools/run_world_tests.py TestGoal      # one class, or one module

CLAUDE.md said for a long time that these could not run in a cloud session,
and that was half right. The ones that build a multiworld cannot, and never
will here. But most of `phase10/test/` is about the session, the store, the
data tables and the save payload, all of which are plain Python -- the only
reason they would not import is that `phase10/__init__.py` reaches for
`worlds.AutoWorld` on the way past.

So this builds `worlds.phase10` as a package pointed at the real directory,
with its own `__init__` never executed, and loads the test modules through it.
No Archipelago, no stubbing of the World API, and nothing pretended: a module
that genuinely needs a multiworld fails to import and is reported as needing
one rather than counted as passing.

They had gone three batches unrun when this was written, and the first run
found two real bugs -- a `NameError` that crashed the Python client the moment
a seat won a run, and a goal that fired at half the seed. Worth the fifteen
lines.

The real suite, from an Archipelago checkout, remains the authority:

    SKIP_REQUIREMENTS_UPDATE=1 python -m unittest discover -s worlds/phase10/test -t .
"""

from __future__ import annotations

import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def mount() -> None:
    """Make `worlds.phase10` importable without Archipelago on the path."""
    worlds = types.ModuleType("worlds")
    worlds.__path__ = []
    package = types.ModuleType("worlds.phase10")
    # A __path__ and no execution: submodules are found and imported as
    # normal, and the package's own __init__ -- the only part that needs
    # Archipelago -- never runs.
    package.__path__ = [str(ROOT / "phase10")]
    package.__package__ = "worlds.phase10"
    worlds.phase10 = package
    sys.modules["worlds"] = worlds
    sys.modules["worlds.phase10"] = package


def main() -> int:
    mount()
    wanted = sys.argv[1] if len(sys.argv) > 1 else None

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    needs_ap: list[tuple[str, str]] = []
    for path in sorted((ROOT / "phase10" / "test").glob("test_*.py")):
        name = f"worlds.phase10.test.{path.stem}"
        try:
            module = __import__(name, fromlist=["*"])
        except Exception as err:
            needs_ap.append((path.stem, f"{type(err).__name__}: {err}"))
            continue
        if wanted and wanted not in (path.stem, *dir(module)):
            continue
        suite.addTests(loader.loadTestsFromName(wanted, module) if wanted
                       else loader.loadTestsFromModule(module))

    result = unittest.TextTestRunner(verbosity=1).run(suite)
    print(f"\n{result.testsRun} run, {len(result.failures)} failed, "
          f"{len(result.errors)} errored")
    for stem, why in needs_ap:
        print(f"  needs an Archipelago checkout: {stem}  ({why})")
    return 1 if (result.failures or result.errors) else 0


if __name__ == "__main__":
    raise SystemExit(main())
