"""Rewrite the README's table of contents from its own headings.

A hand-written contents list is wrong the first time a heading moves, and
nothing notices. This generates it, and `--check` fails when the file on disk
disagrees -- so the list is either correct or the check is red.

    python tools/update_toc.py
    python tools/update_toc.py --check

Anchors follow GitHub's rule: lower-cased, punctuation dropped, spaces to
hyphens, and a repeated heading gets `-1`, `-2` and so on. Two headings in this
file really are identical, so that last part is not hypothetical.
"""

from __future__ import annotations

import pathlib
import re
import sys

README = pathlib.Path(__file__).resolve().parent.parent / "README.md"

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
        # Strip the inline formatting from the link text; a link whose label
        # carries backticks or asterisks renders as literal punctuation here.
        label = re.sub(r"[`*_]", "", title)
        lines.append(f"{indent}- [{label}](#{anchor(title, seen)})")
    return "\n".join(lines)


def main() -> int:
    text = README.read_text(encoding="utf-8")
    if START not in text or END not in text:
        print(f"README.md has no {START} / {END} markers", file=sys.stderr)
        return 2

    before, rest = text.split(START, 1)
    _, after = rest.split(END, 1)
    # Built from the body below the markers, so the contents cannot list
    # itself and a heading inside the old block cannot survive a rewrite.
    toc = build(after)
    fresh = f"{before}{START}\n\n{toc}\n\n{END}{after}"

    if "--check" in sys.argv:
        if fresh != text:
            print("README.md's table of contents is out of date; "
                  "run python tools/update_toc.py", file=sys.stderr)
            return 1
        print(f"table of contents matches ({len(toc.splitlines())} entries)")
        return 0

    if fresh == text:
        print(f"table of contents already current ({len(toc.splitlines())} entries)")
        return 0
    README.write_text(fresh, encoding="utf-8")
    print(f"table of contents rewritten ({len(toc.splitlines())} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
