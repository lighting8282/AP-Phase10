"""Package phase10/ as an installable .apworld.

An .apworld is a zip holding one top-level directory named for the module,
dropped into Archipelago's custom_worlds/. Everything in this project has so
far been run from source through a dev junction, which only works on this
machine and only against a source checkout -- this is what other people can
actually install.

    python tools/build_apworld.py
    python tools/build_apworld.py --verify dist/phase10.apworld

Timestamps are fixed so two builds of the same source are byte-identical;
otherwise every build looks like a change and you cannot tell whether a
shipped file differs from the one you have.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys
import zipfile

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = PROJECT_ROOT / "phase10"
MODULE = "phase10"

#: Dev-only trees. Both reference apworlds ship neither, and the test suite
#: needs Archipelago's own test framework, so it is no use to an installer.
EXCLUDED_DIRS = {"__pycache__", "test"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}

#: A build missing any of these is broken in a way that only shows up when
#: somebody tries to generate with it.
REQUIRED = [
    "phase10/__init__.py",
    "phase10/archipelago.json",
    "phase10/world.py",
    "phase10/data.py",
    "phase10/items.py",
    "phase10/locations.py",
    "phase10/options.py",
    "phase10/regions.py",
    "phase10/rules.py",
    "phase10/web_world.py",
    "phase10/components.py",
    "phase10/client/context.py",
    "phase10/client/session.py",
    "phase10/client/game_manager.py",
    "phase10/game/engine.py",
    "phase10/game/phases.py",
    "phase10/game/cards.py",
]

#: Fixed so the build is reproducible (zip stores 1980-01-01 as its epoch).
FIXED_TIME = (1980, 1, 1, 0, 0, 0)

#: Container-format fields, injected at build time rather than committed.
#: They describe the package, not the world, and Archipelago generates them
#: itself in APWorldContainer.get_manifest -- the source manifest stays a
#: description of the world, the way worlds/apquest/archipelago.json is.
#: Without them the loader raises KeyError on compatible_version and reports
#: it as "This might be the incorrect world version for this file", which
#: points nowhere near the actual problem. Mirrors worlds/Files.py
#: container_version; if Archipelago bumps it, the loader will say so.
CONTAINER_VERSION = 7


def collect() -> list[pathlib.Path]:
    files = []
    for path in sorted(PACKAGE.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(PACKAGE)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        if path.suffix in EXCLUDED_SUFFIXES:
            continue
        files.append(path)
    return files


def build(target: pathlib.Path) -> pathlib.Path:
    files = collect()
    target.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in files:
            rel = path.relative_to(PACKAGE)
            name = f"{MODULE}/{rel.as_posix()}"
            payload = path.read_bytes()
            if rel.as_posix() == "archipelago.json":
                payload = container_manifest(payload)
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, payload)

    return target


def container_manifest(source: bytes) -> bytes:
    """The world's manifest plus the container fields the loader validates."""
    import json

    manifest = json.loads(source)
    manifest["compatible_version"] = CONTAINER_VERSION
    manifest["version"] = CONTAINER_VERSION
    return json.dumps(manifest, indent="	").encode("utf-8")


def verify(target: pathlib.Path) -> list[str]:
    problems = []
    with zipfile.ZipFile(target) as z:
        names = set(z.namelist())
        bad = z.testzip()
        if bad is not None:
            problems.append(f"corrupt entry: {bad}")

        for required in REQUIRED:
            if required not in names:
                problems.append(f"missing {required}")

        tops = {n.split("/")[0] for n in names}
        if tops != {MODULE}:
            problems.append(f"expected a single top-level {MODULE}/, found {sorted(tops)}")

        for name in names:
            if "__pycache__" in name or name.endswith((".pyc", ".pyo")):
                problems.append(f"bytecode leaked in: {name}")
            if f"{MODULE}/test/" in name:
                problems.append(f"dev test tree leaked in: {name}")

        # The Kivy client loads these at runtime; a world without them imports
        # fine and then shows blank cards.
        if not any(n.startswith(f"{MODULE}/client/assets/cards/") for n in names):
            problems.append("no card art -- the desktop client would render blanks")

        # The game name has to match the docs filename or the WebHost page 404s.
        import json

        manifest = json.loads(z.read(f"{MODULE}/archipelago.json"))
        for field in ("compatible_version", "version"):
            if field not in manifest:
                problems.append(f"manifest is missing {field}; the loader will reject it")
        game = manifest["game"]
        doc = f"{MODULE}/docs/en_{game}.md"
        if doc not in names:
            problems.append(f"manifest game is {game!r} but {doc} is not in the package")

    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="dist/phase10.apworld")
    ap.add_argument("--verify", metavar="PATH", default=None,
                    help="verify an existing package instead of building")
    args = ap.parse_args()

    if args.verify:
        target = pathlib.Path(args.verify)
        if not target.is_absolute():
            target = PROJECT_ROOT / target
        problems = verify(target)
        if problems:
            print(f"{target.name} is not a valid apworld:")
            for p in problems:
                print("  " + p)
            return 1
        print(f"{target.name} verified")
        return 0

    target = pathlib.Path(args.out)
    if not target.is_absolute():
        target = PROJECT_ROOT / target
    build(target)

    problems = verify(target)
    if problems:
        print("built, but the package is not valid:")
        for p in problems:
            print("  " + p)
        return 1

    with zipfile.ZipFile(target) as z:
        entries = len(z.namelist())
    digest = hashlib.sha256(target.read_bytes()).hexdigest()[:16]
    size = target.stat().st_size
    print(f"{target.relative_to(PROJECT_ROOT)}  {entries} files  "
          f"{size / 1024:.0f} KB  sha256:{digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
