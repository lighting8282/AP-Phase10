"""Rewrite each contents list from the headings of its own file.

A hand-written contents list is wrong the first time a heading moves, and
nothing notices. This generates them, and `--check` fails when a file on disk
disagrees -- so a list is either correct or the check is red.

    python tools/update_toc.py
    python tools/update_toc.py --check

Anchors follow GitHub's rule: lower-cased, punctuation dropped, spaces to
hyphens, and a repeated heading gets `-1`, `-2` and so on. Two headings in
DEVELOPMENT.md really are identical, so that last part is not hypothetical --
it was checked against GitHub's own markdown API rather than assumed.
"""

from __future__ import annotations

import pathlib
import sys
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Every file that carries a generated contents list.
FILES = [ROOT / "README.md", ROOT / "DEVELOPMENT.md"]

START = "<!-- toc -->"
END = "<!-- /toc -->"

#: Deeper than this is detail, not navigation.
MAX_DEPTH = 3


def anchor(title: str, seen: dict[str, int]) -> str:
    slug = title.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    count = seen.get(slug, 0)
    seen[slug] = count + 1
    return slug if count == 0 else f"{slug}-{count}"


def headings(text: str) -> list[tuple[int, str]]:
    out = []
    fenced = False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = re.match(r"^(#{2,6})\s+(.*?)\s*$", line)
        if match and len(match.group(1)) <= MAX_DEPTH:
            out.append((len(match.group(1)), match.group(2)))
    return out


def build(text: str) -> str:
    seen: dict[str, int] = {}
    lines = []
    for depth, title in headings(text):
        indent = "  " * (depth - 2)
        # Strip the inline formatting from the link text; a label carrying
        # backticks or asterisks renders as literal punctuation here.
        label = re.sub(r"[`*_]", "", title)
        lines.append(f"{indent}- [{label}](#{anchor(title, seen)})")
    return "\n".join(lines)


def update(path: pathlib.Path, check: bool) -> int:
    text = path.read_text(encoding="utf-8")
    if START not in text or END not in text:
        print(f"{path.name} has no {START} / {END} markers", file=sys.stderr)
        return 2

    before, rest = text.split(START, 1)
    _, after = rest.split(END, 1)
    # Built from the body below the markers, so the contents cannot list itself
    # and a heading inside the old block cannot survive a rewrite.
    toc = build(after)
    fresh = before + START + "\n\n" + toc + "\n\n" + END + after
    entries = len(toc.splitlines())

    if check:
        if fresh != text:
            print(f"{path.name}'s table of contents is out of date; "
                  "run python tools/update_toc.py", file=sys.stderr)
            return 1
        print(f"{path.name}: matches ({entries} entries)")
        return 0

    if fresh == text:
        print(f"{path.name}: already current ({entries} entries)")
        return 0
    path.write_text(fresh, encoding="utf-8")
    print(f"{path.name}: rewritten ({entries} entries)")
    return 0


def main() -> int:
    check = "--check" in sys.argv
    return max(update(path, check) for path in FILES)


if __name__ == "__main__":
    raise SystemExit(main())
