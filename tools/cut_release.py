"""Cut the release: check, build, tag, publish, and clear out the old one.

The version is read from `phase10/archipelago.json`, which is the only place
it lives. Bump it there, merge that, and run this -- nothing here takes a
version argument, because a release tagged differently from the manifest
inside its own .apworld is the kind of thing nobody notices for a month.

    python tools/cut_release.py --dry-run    # say what would happen
    python tools/cut_release.py

**Two files are attached.** The apworld always, and the YAML options template
when Archipelago can be reached through `AP_ROOT` -- skipped with a line saying
so when it cannot, because a release with the apworld and no template is still
a release, and one that refuses to be cut over an unset path is not.

It refuses rather than guesses. A dirty tree, a branch that is not the default
one, a local branch behind its remote, a failing check, a tag that already
exists: each stops the run before anything reaches GitHub, and says which one
it was.

**Older releases and tags are deleted.** That is the convention for this
repository -- only the current release should exist -- and it is the whole
reason this is a script rather than a note in DEVELOPMENT.md, because doing it
by hand is where the wrong tag gets deleted.

Needs the `gh` CLI, authenticated (`gh auth login`). This cannot run from a
cloud session: that GitHub access is brokered by a proxy which permits commits,
branches and pull requests but not tags or releases, so the push and every `gh
release` call come back 403. It is meant for a machine you are signed in on.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "phase10" / "archipelago.json"
ARTIFACT = ROOT / "dist" / "phase10.apworld"
TEMPLATE = ROOT / "dist" / "AP_10.yaml"
README = ROOT / "README.md"
#: export_template.py's "no Archipelago here" code, as opposed to a real
#: failure. A release without the template is still a release.
NO_ARCHIPELAGO = 2
DEFAULT_BRANCH = "main"

#: Run before anything is published. The same battery CLAUDE.md asks for
#: before a push -- a release is a push with an audience.
CHECKS: list[tuple[str, list[str]]] = [
    ("the JS suite and the table check", ["npm", "test"]),
    ("the solver", [sys.executable, "tests/test_phases.py"]),
    ("the hand loop and the table", [sys.executable, "tests/test_game.py"]),
    ("the build stamp", [sys.executable, "tools/stamp_build.py", "--check"]),
    ("the rules prose", [sys.executable, "tools/check_rules_doc.py"]),
    ("the duplicated tables", [sys.executable, "tools/check_js_tables.py"]),
]


def program(name: str) -> str:
    """The full path to a command, or a refusal naming it.

    Resolved rather than passed through, because of Windows. `npm` there is
    `npm.cmd`, and CreateProcess only ever appends `.exe` -- so a bare "npm"
    is not found, and what comes back is a FileNotFoundError from deep inside
    subprocess with a traceback that says nothing about npm. `shutil.which`
    honours PATHEXT and finds the `.cmd`, and a missing program now says which
    one it was. Reported from a real run on Windows, having only been tested on
    Linux, where "npm" resolves and the bug does not exist.
    """
    found = shutil.which(name)
    if found is None:
        raise SystemExit(f"! {name} is not on PATH. Install it, or open a "
                         f"terminal where it is, and run this again.")
    return found


def attempt(args: list[str]) -> tuple[int, str]:
    """Run a command, returning its code and output instead of raising.

    Output is captured rather than let through: this is for steps that are
    allowed to fail, and a child writing to stderr on its own lands after the
    summary that explains it, which reads like an error in a run that
    succeeded.
    """
    result = subprocess.run([program(args[0]), *args[1:]], cwd=ROOT, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return result.returncode, (result.stdout or "").strip()


def run(args: list[str], *, capture: bool = True) -> str:
    """Run a command in the repository, raising on failure."""
    args = [program(args[0]), *args[1:]]
    result = subprocess.run(
        args, cwd=ROOT, text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )
    if result.returncode != 0:
        output = (result.stdout or "").strip()
        shown = [pathlib.Path(args[0]).name, *args[1:]]
        raise SystemExit(f"! {' '.join(shown)} failed\n{output}")
    return (result.stdout or "").strip()


def version() -> str:
    """The one the manifest declares, and the only one this script will use."""
    declared = json.loads(MANIFEST.read_text(encoding="utf-8"))["world_version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", declared):
        raise SystemExit(f"! world_version is {declared!r}, which is not x.y.z")
    return declared


def readme_says(declared: str) -> None:
    """The README's sample YAML pins a world version. Keep it honest.

    It is a line a player copies, and nothing else checks it, so it sat nine
    releases out of date (`AP_10: 0.9.0` against a shipped 1.4.1) until someone
    read the file against the code. A release is exactly when it goes stale, so
    a release is where it is caught.
    """
    found = re.search(r"^\s*AP_10:\s*(\d+\.\d+\.\d+)\s*$",
                      README.read_text(encoding="utf-8"), re.M)
    if found is None:
        raise SystemExit("! no `AP_10: x.y.z` sample found in README.md. If the "
                         "sample moved, update this check with it.")
    if found.group(1) != declared:
        raise SystemExit(f"! README.md's sample YAML says AP_10: {found.group(1)}, "
                         f"but this release is {declared}. Fix the README.")


def refuse_unless_ready(tag: str) -> None:
    """Every reason not to cut, checked before anything is published."""
    # Checked here as well as at first use: it is the one whose absence should
    # stop the run before ten seconds of tests, not after them.
    if shutil.which("gh") is None:
        raise SystemExit(
            "! the gh CLI is not on PATH. Install it and `gh auth login`.\n"
            "  On Windows: winget install GitHub.cli\n"
            "  This script cannot run from a cloud session -- see the module "
            "docstring."
        )
    if run(["git", "status", "--porcelain"]):
        raise SystemExit("! the working tree has changes. Commit or stash them.")

    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if branch != DEFAULT_BRANCH:
        raise SystemExit(f"! on {branch}, not {DEFAULT_BRANCH}. A release is cut "
                         f"from {DEFAULT_BRANCH}.")

    run(["git", "fetch", "origin", DEFAULT_BRANCH])
    local = run(["git", "rev-parse", "HEAD"])
    remote = run(["git", "rev-parse", f"origin/{DEFAULT_BRANCH}"])
    if local != remote:
        raise SystemExit(
            f"! {DEFAULT_BRANCH} is not what origin has ({local[:8]} vs "
            f"{remote[:8]}). Pull, or push, before cutting."
        )

    # Locally and on the remote both: a tag that exists here but not there is
    # exactly as much of a problem, and it is the one `git push` would report
    # last rather than first.
    if run(["git", "tag", "-l", tag]):
        raise SystemExit(f"! tag {tag} already exists locally. Bump "
                         f"world_version, or delete it.")
    if run(["git", "ls-remote", "--tags", "origin", tag]):
        raise SystemExit(f"! tag {tag} already exists on origin. Bump "
                         f"world_version, or delete it.")


def make_template() -> pathlib.Path | None:
    """The YAML template, None when there is no Archipelago to make it with."""
    TEMPLATE.unlink(missing_ok=True)
    code, said = attempt([sys.executable, "tools/export_template.py",
                          "--out", str(TEMPLATE)])
    if code == 0 and TEMPLATE.exists():
        print(f"  ok   {TEMPLATE.relative_to(ROOT)} generated")
        return TEMPLATE
    if code == NO_ARCHIPELAGO:
        why = said.splitlines()[0].lstrip("! ") if said else "no checkout found"
        print(f"  --   no YAML template attached ({why})")
        return None
    raise SystemExit(f"{said}\n\nStopped before anything was built, tagged or "
                     f"published -- fix the above and run this again.")


def old_releases(keep: str) -> list[str]:
    """Every published release tag except the one being cut."""
    listed = run(["gh", "release", "list", "--limit", "100",
                  "--json", "tagName", "--jq", ".[].tagName"])
    return [tag for tag in listed.splitlines() if tag.strip() and tag != keep]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="check and build, but publish nothing")
    args = parser.parse_args()

    tag = f"v{version()}"
    print(f"cutting {tag}")

    refuse_unless_ready(tag)
    readme_says(version())
    print("  ready: clean tree, on the default branch, level with origin, "
          "README in step")

    # The YAML template people fill in, generated by Archipelago from the
    # option docstrings. First, before the battery: the likeliest way for it to
    # fail is an old AP_10 installed in that Archipelago, and that should cost
    # seconds rather than a minute of tests. Attached when it can be made and
    # skipped when there is no Archipelago at all -- a release with the apworld
    # and no template is still a release.
    template = make_template()

    for what, command in CHECKS:
        run(command)
        print(f"  ok   {what}")

    uploads: list[pathlib.Path] = [ARTIFACT] + ([template] if template else [])
    run([sys.executable, "tools/build_apworld.py"])
    if not ARTIFACT.exists():
        raise SystemExit(f"! {ARTIFACT} was not built")
    # The manifest inside the zip decides what Archipelago reports, so it is
    # the copy worth checking rather than the one on disk.
    run([sys.executable, "tools/build_apworld.py", "--verify", str(ARTIFACT)])
    print(f"  ok   {ARTIFACT.relative_to(ROOT)} built and verified")

    stale = old_releases(tag)
    if args.dry_run:
        print(f"\n--dry-run, so stopping here. Would have:")
        print(f"  tagged {run(['git', 'rev-parse', '--short', 'HEAD'])} as {tag} "
              f"and pushed it")
        print(f"  published {tag} with "
              f"{', '.join(p.name for p in uploads)} attached")
        for old in stale:
            print(f"  deleted release {old} and its tag")
        return 0

    run(["git", "tag", "-a", tag, "-m", f"AP_10 {version()}"])
    run(["git", "push", "origin", tag])
    print(f"  ok   tagged and pushed {tag}")

    notes = ["Drop `phase10.apworld` into Archipelago's `custom_worlds/`."]
    if TEMPLATE in uploads:
        notes.append(f"`{TEMPLATE.name}` is the options template, for your "
                     f"`Players/` folder.")
    notes.append(f"Built from {run(['git', 'rev-parse', 'HEAD'])}.")
    run(["gh", "release", "create", tag, *(str(p) for p in uploads),
         "--title", f"AP_10 {version()}", "--notes", "\n\n".join(notes)])
    print(f"  ok   published {tag}")

    # Last, and only once the new one exists: a failure earlier should leave
    # the old release standing rather than leave the repository with none.
    for old in stale:
        run(["gh", "release", "delete", old, "--yes", "--cleanup-tag"])
        print(f"  ok   deleted the old release {old} and its tag")

    print(f"\n{tag} is the only release.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
