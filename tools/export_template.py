"""Write the game's YAML options template, for attaching to a release.

    python tools/export_template.py                 # dist/AP_10.yaml
    python tools/export_template.py --out some.yaml

The template is generated from the option docstrings by Archipelago itself, so
this needs a checkout: `AP_ROOT`, defaulting to the path on the original
author's machine. It is the same file the Launcher's "Generate Template
Options" writes -- taken from there rather than rendered here, because a
hand-rolled copy would drift from what players actually get.

Exits 2, distinctly, when Archipelago is not reachable. `cut_release.py` reads
that as "skip the YAML" rather than as a failed release: a release with the
apworld and no template is still a release, and one that refuses to be cut
because a path is unset is not.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GAME = "AP_10"
NO_ARCHIPELAGO = 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(PROJECT_ROOT / "dist" / f"{GAME}.yaml"))
    args = ap.parse_args()

    root = os.environ.get("AP_ROOT", "C:/Users/turtl/Archipelago")
    if not Path(root).is_dir():
        print(f"! no Archipelago checkout at {root}. Set AP_ROOT to yours.",
              file=sys.stderr)
        return NO_ARCHIPELAGO

    sys.path.insert(0, root)
    os.chdir(root)
    try:
        import ModuleUpdate
        ModuleUpdate.update_ran = True
        import Options
    except Exception as err:  # pragma: no cover - environment dependent
        print(f"! could not load Archipelago from {root}: {err}", file=sys.stderr)
        return NO_ARCHIPELAGO

    write = getattr(Options, "generate_yaml_templates", None)
    if write is None:  # pragma: no cover - environment dependent
        print("! this Archipelago has no Options.generate_yaml_templates; "
              "generate the template from the Launcher and pass it to "
              "cut_release.py with --yaml", file=sys.stderr)
        return NO_ARCHIPELAGO

    # Templates are written for every installed world, so take ours out of a
    # scratch folder rather than pointing the generator at dist/.
    with tempfile.TemporaryDirectory() as tmp:
        write(tmp, False)
        made = Path(tmp) / f"{GAME}.yaml"
        if not made.is_file():
            found = sorted(p.name for p in Path(tmp).glob("*.yaml"))
            print(f"! no {GAME}.yaml was generated. Is this world installed? "
                  f"Found: {found[:5]}", file=sys.stderr)
            return 1
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(made, out)

    text = out.read_text(encoding="utf-8")
    problems = mismatches(text)
    if problems:
        out.unlink()
        print(f"! the template Archipelago rendered is not this build's. It "
              f"loaded AP_10 from:\n    {loaded_from()}\n  "
              + "\n  ".join(problems)
              + "\n  Remove or replace that copy so Archipelago loads this "
                "repository's world, then run this again.", file=sys.stderr)
        return 1
    print(f"{out}  {len(text.splitlines())} lines, AP_10 {built_version()}")
    return 0


# -- is it ours? ----------------------------------------------------------------
# Archipelago renders the template for whichever AP_10 it loaded, and that is
# whatever is installed in the checkout -- an old phase10.apworld left in
# custom_worlds/ wins as easily as this repository does. v1.5.0 shipped exactly
# that: a 1.2.0 template, old option text and no store_gating, beside a 1.5.0
# apworld, because nothing compared the two. Now the template has to name this
# build's version and carry every option this build declares, or it is refused.

def built_version() -> str:
    manifest = PROJECT_ROOT / "phase10" / "archipelago.json"
    return json.loads(manifest.read_text(encoding="utf-8"))["world_version"]


def declared_options() -> set[str]:
    """The option names this build's options dataclass declares.

    Read from the source rather than imported, so the check cannot be fooled
    by the same stale copy it is looking for.
    """
    tree = ast.parse((PROJECT_ROOT / "phase10" / "options.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Phase10Options":
            return {item.target.id for item in node.body
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)}
    raise SystemExit("! no Phase10Options in phase10/options.py")


def mismatches(text: str) -> list[str]:
    problems = []
    found = re.search(rf"^\s+{GAME}:\s*([\d.]+)", text, re.M)
    version = found.group(1) if found else None
    if version != built_version():
        problems.append(f"it says {GAME} {version}; this build is {built_version()}")
    keys = set(re.findall(r"^  ([a-z_]+):", text, re.M))
    missing = sorted(declared_options() - keys)
    if missing:
        problems.append(f"it is missing options this build has: {', '.join(missing)}")
    return problems


def loaded_from() -> str:
    try:
        from worlds.AutoWorld import AutoWorldRegister
        world = AutoWorldRegister.world_types[GAME]
        return sys.modules[world.__module__].__file__ or world.__module__
    except Exception as err:  # pragma: no cover - environment dependent
        return f"(could not tell: {err})"


if __name__ == "__main__":
    raise SystemExit(main())
