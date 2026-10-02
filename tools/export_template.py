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
import os
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
    print(f"{out}  {len(text.splitlines())} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
