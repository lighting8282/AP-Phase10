"""Stamp a build id onto every module URL the page loads.

GitHub Pages serves each file with `max-age=600`, and every file's clock
starts when that browser first fetched it. So a visitor can hold a new
engine.js beside a ten-minute-old ui.js -- a build that never existed and was
never tested. It fails quietly: a Skip that denies a turn in the new engine,
with the old UI that says nothing about it, looks exactly like a Skip that did
nothing.

A query string makes each version a different URL, so a deploy is all or
nothing. It cannot be inherited -- a relative import inside a module resolves
against the module's path without its query -- so every import specifier has
to carry it, which is what this rewrites.

    python tools/stamp_build.py            # stamp with the sources' own hash
    python tools/stamp_build.py --check    # fail if any are missing or stale

Node keeps working: it treats the query as part of the specifier and still
finds the file, so the test suites run against the stamped sources.

One consequence to know about. The tests import `../src/engine.js` while the
sources import `./engine.js?v=...`, and Node keys its module cache on the
specifier -- so a test run holds two copies of any module it imports both ways.
That is harmless here and was checked rather than assumed: nothing uses
`instanceof` across a module boundary, and the only module-level state is a
memo keyed by content. If either stops being true, stamp docs/test/*.mjs too
and accept the diff noise.
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "src"
INDEX = ROOT / "docs" / "index.html"
STYLE = ROOT / "docs" / "style.css"
#: Everything the page loads, in a fixed order so the hash is stable. The
#: stylesheet counts: it is served with the same ten-minute cache, and half the
#: layout lives in it, so a CSS-only deploy left the old rules in place with
#: nothing in the markup to say so.
SOURCES = sorted(SRC.glob("*.js")) + [STYLE]

#: `from "./engine.js"` and `from "../node_modules/..."`, with or without a
#: stamp already on them.
IMPORT = re.compile(r'(from\s+")(\.{1,2}/[^"?]+\.js)(\?v=[^"]*)?(")')
#: The page's own entry point.
SCRIPT = re.compile(r'(<script type="module" src=")([^"?]+)(\?v=[^"]*)?(")')
#: And its stylesheet.
SHEET = re.compile(r'(<link rel="stylesheet" href=")([^"?]+)(\?v=[^"]*)?(")')


def build_id() -> str:
    """A short hash of the sources themselves.

    Not the world version: browser-only changes do not bump that, and an
    unchanged stamp means an unchanged URL means the old file stays cached --
    which is the whole problem. The existing stamps are stripped before
    hashing, or the id would depend on itself.
    """
    digest = hashlib.sha256()
    for path in SOURCES:
        # Only the stamp is stripped, not the import: a changed module path
        # is a changed source and has to move the hash.
        bare = IMPORT.sub(lambda m: m[1] + m[2] + m[4],
                          path.read_text(encoding="utf-8"))
        digest.update(bare.encode("utf-8"))
    return digest.hexdigest()[:8]


def stamp(text: str, version: str, pattern: re.Pattern) -> tuple[str, int]:
    changed = 0

    def swap(match: re.Match) -> str:
        nonlocal changed
        head, path, existing, tail = match.groups()
        wanted = f"?v={version}"
        if existing == wanted:
            return match.group(0)
        changed += 1
        return f"{head}{path}{wanted}{tail}"

    return pattern.sub(swap, text), changed


def main() -> int:
    version = build_id()
    check = "--check" in sys.argv
    stale: list[str] = []
    stamped = 0

    targets = [(path, IMPORT) for path in sorted(SRC.glob("*.js"))]
    # Two passes over the page: the entry point and the stylesheet are
    # different tags, and one regex for both would match neither cleanly.
    targets.append((INDEX, SCRIPT))
    targets.append((INDEX, SHEET))
    # index.html also carries module imports if any are ever inlined.
    for path, pattern in targets:
        text = path.read_text(encoding="utf-8")
        fresh, changed = stamp(text, version, pattern)
        if not changed:
            continue
        if check:
            stale.append(path.name)
        else:
            path.write_text(fresh, encoding="utf-8")
            stamped += changed

    if check:
        if stale:
            print(f"unstamped or stale for {version}: {', '.join(stale)}",
                  file=sys.stderr)
            return 1
        print(f"every module URL carries ?v={version}")
        return 0

    print(f"stamped {stamped} module URL(s) with ?v={version}"
          if stamped else f"already stamped with ?v={version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
