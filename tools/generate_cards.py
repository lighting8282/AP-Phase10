"""Procedurally render the Phase 10 deck to PNG.

Every pixel here is drawn by the code below -- rounded rectangles, text and
lines. No generative model is involved, so the output is an ordinary work of
authorship whose expressive choices (palette, proportions, typography) live
in this file and can be edited directly.

The deck holds 108 physical cards but only 51 distinct faces: 12 ranks in 4
colors, plus Wild, Skip and the back. Duplicates share an image, so that is
what gets rendered.

Usage, from the project root:

    python tools/generate_cards.py                 # default 200x300
    python tools/generate_cards.py --scale 3       # 600x900
    python tools/generate_cards.py --check-palette # sync check only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_cards_module():
    """Load phase10/game/cards.py directly, bypassing the package __init__.

    Importing `phase10` normally pulls in components.py, which needs AP's
    `worlds.LauncherComponents`. This tool only needs the card model, so it
    loads that one module by path and stays runnable without an AP checkout.
    Still the real model, so the deck it renders cannot drift from the deck
    the game deals.
    """
    import importlib.util

    path = PROJECT_ROOT / "phase10" / "game" / "cards.py"
    if not path.is_file():
        raise SystemExit(f"cannot find the card model at {path}")
    spec = importlib.util.spec_from_file_location("_p10_cards", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["_p10_cards"] = module
    spec.loader.exec_module(module)
    return module


_cards = _load_cards_module()
Card = _cards.Card
Color = _cards.Color
Kind = _cards.Kind
MIN_RANK = _cards.MIN_RANK
MAX_RANK = _cards.MAX_RANK

# Defined next to the model so the renderer and the UI that loads these files
# cannot disagree about what a card is called.
card_filename = _cards.card_filename

# ---------------------------------------------------------------------------
# Palette
#
# Deliberately identical to CARD_COLORS / WILD_COLOR / SKIP_COLOR in
# phase10/client/game_manager.py, so a rendered card and the Kivy button for
# the same card agree. That module imports Kivy, which this script must not
# pull in, hence the duplication. verify_palette() below reports any drift.
# ---------------------------------------------------------------------------

CARD_COLORS: dict[Color, tuple[float, float, float, float]] = {
    Color.RED: (0.78, 0.22, 0.22, 1),
    Color.BLUE: (0.20, 0.42, 0.85, 1),
    Color.GREEN: (0.18, 0.62, 0.32, 1),
    Color.YELLOW: (0.85, 0.68, 0.12, 1),
}
WILD_COLOR = (0.55, 0.30, 0.78, 1)
SKIP_COLOR = (0.42, 0.44, 0.50, 1)

CARD_STOCK = (248, 248, 245, 255)   # off-white rim, like real card stock
BACK_COLOR = (0.13, 0.16, 0.28, 1)
INK = (255, 255, 255, 255)

FONT_CANDIDATES = (
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/calibrib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


def rgba(c: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    """Kivy-style 0..1 floats -> Pillow 0..255 ints."""
    return tuple(int(round(v * 255)) for v in c)  # type: ignore[return-value]


def load_font(size: int, explicit: str | None = None) -> ImageFont.FreeTypeFont:
    paths = ((explicit,) + FONT_CANDIDATES) if explicit else FONT_CANDIDATES
    for p in paths:
        if p and Path(p).is_file():
            return ImageFont.truetype(p, size)
    raise SystemExit(
        "No usable TrueType font found. Pass one with --font /path/to/font.ttf\n"
        "Tried: " + ", ".join(str(p) for p in paths)
    )


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def _blank(w: int, h: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _card_base(w: int, h: int, fill: tuple[int, int, int, int]):
    """Card stock with an inset colored panel."""
    img, d = _blank(w, h)
    radius = int(w * 0.09)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=CARD_STOCK)
    inset = int(w * 0.045)
    d.rounded_rectangle(
        (inset, inset, w - 1 - inset, h - 1 - inset),
        radius=int(radius * 0.72),
        fill=fill,
    )
    return img, d


def _underline(d: ImageDraw.ImageDraw, cx: int, cy: int, font, glyph: str) -> None:
    """Underline 6 and 9 so a rotated card is never ambiguous."""
    if glyph not in ("6", "9"):
        return
    box = d.textbbox((cx, cy), glyph, font=font, anchor="mm")
    half = (box[2] - box[0]) * 0.42
    y = box[3] + (box[3] - box[1]) * 0.10
    d.line((cx - half, y, cx + half, y), fill=INK, width=max(2, int(half * 0.14)))


def render_number(rank: int, color: Color, w: int, h: int, font_path: str | None) -> Image.Image:
    img, d = _card_base(w, h, rgba(CARD_COLORS[color]))
    glyph = str(rank)

    big = load_font(int(h * 0.40), font_path)
    cx, cy = w // 2, int(h * 0.49)
    d.text((cx, cy), glyph, font=big, fill=INK, anchor="mm")
    _underline(d, cx, cy, big, glyph)

    small = load_font(int(h * 0.115), font_path)
    pad = int(w * 0.135)
    d.text((pad, pad), glyph, font=small, fill=INK, anchor="mm")

    # Bottom-right corner, rotated 180 the way a real card reads.
    corner, cd = _blank(int(w * 0.34), int(h * 0.24))
    ccx, ccy = corner.width // 2, corner.height // 2
    cd.text((ccx, ccy), glyph, font=small, fill=INK, anchor="mm")
    _underline(cd, ccx, ccy, small, glyph)
    corner = corner.rotate(180)
    img.alpha_composite(corner, (w - pad - corner.width // 2, h - pad - corner.height // 2))
    return img


def render_wild(w: int, h: int, font_path: str | None) -> Image.Image:
    img, d = _card_base(w, h, rgba(WILD_COLOR))
    big = load_font(int(h * 0.40), font_path)
    d.text((w // 2, int(h * 0.49)), "W", font=big, fill=INK, anchor="mm")

    # Four pips in the deck colors -- a wild stands in for any of them.
    r = int(w * 0.045)
    pad = int(w * 0.15)
    spots = (
        (pad, pad, Color.RED),
        (w - pad, pad, Color.BLUE),
        (pad, h - pad, Color.GREEN),
        (w - pad, h - pad, Color.YELLOW),
    )
    for x, y, c in spots:
        d.ellipse(
            (x - r, y - r, x + r, y + r),
            fill=rgba(CARD_COLORS[c]),
            outline=INK,
            width=max(1, r // 4),
        )
    return img


def render_skip(w: int, h: int, font_path: str | None) -> Image.Image:
    img, d = _card_base(w, h, rgba(SKIP_COLOR))

    # Ring and slash, with nothing inside it. An earlier version centered an
    # "S" in the ring and the slash cut straight through the letter, which
    # turned to mush at hand size. The word below carries the meaning instead.
    cx, cy = w // 2, int(h * 0.42)
    rad = int(w * 0.26)
    width = max(2, int(w * 0.045))
    d.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), outline=INK, width=width)
    off = int(rad * 0.7071)
    d.line((cx - off, cy + off, cx + off, cy - off), fill=INK, width=width)

    label = load_font(int(h * 0.115), font_path)
    d.text((cx, int(h * 0.74)), "SKIP", font=label, fill=INK, anchor="mm")
    return img


def render_back(w: int, h: int, font_path: str | None) -> Image.Image:
    img, d = _card_base(w, h, rgba(BACK_COLOR))
    inset = int(w * 0.045)
    step = int(w * 0.075)
    for i in range(1, 4):
        o = inset + step * i
        d.rounded_rectangle(
            (o, o, w - 1 - o, h - 1 - o),
            radius=int(w * 0.06),
            outline=(255, 255, 255, 70),
            width=max(1, int(w * 0.012)),
        )
    font = load_font(int(h * 0.20), font_path)
    d.text((w // 2, int(h * 0.49)), "10", font=font, fill=(255, 255, 255, 200), anchor="mm")
    return img


# ---------------------------------------------------------------------------
# Drift check
# ---------------------------------------------------------------------------

def verify_palette() -> list[str]:
    """Compare this palette with game_manager.py without importing Kivy.

    Values are parsed and compared numerically. Comparing source text would
    report false drift, since 0.20 in the file round-trips as "0.2".
    """
    import ast
    import re

    src = PROJECT_ROOT / "phase10" / "client" / "game_manager.py"
    if not src.is_file():
        return [f"game_manager.py not found at {src}"]
    text = src.read_text(encoding="utf-8")

    def grab(pattern: str) -> tuple[float, ...] | None:
        m = re.search(pattern, text)
        if not m:
            return None
        try:
            return tuple(float(v) for v in ast.literal_eval(m.group(1)))
        except (ValueError, SyntaxError):
            return None

    found: dict[str, tuple[float, ...] | None] = {
        f"Color.{c.name}": grab(rf"Color\.{c.name}:\s*(\([^)]*\))") for c in Color
    }
    found["WILD_COLOR"] = grab(r"WILD_COLOR\s*=\s*(\([^)]*\))")
    found["SKIP_COLOR"] = grab(r"SKIP_COLOR\s*=\s*(\([^)]*\))")

    expected: dict[str, tuple[float, ...]] = {
        f"Color.{c.name}": tuple(float(v) for v in CARD_COLORS[c]) for c in Color
    }
    expected["WILD_COLOR"] = tuple(float(v) for v in WILD_COLOR)
    expected["SKIP_COLOR"] = tuple(float(v) for v in SKIP_COLOR)

    problems = []
    for key, want in expected.items():
        got = found.get(key)
        if got is None:
            problems.append(f"{key}: not found in game_manager.py")
        elif got != want:
            problems.append(f"{key}: generator has {want}, game_manager has {got}")
    return problems


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--out", default="phase10/client/assets/cards", help="output directory")
    ap.add_argument("--width", type=int, default=200)
    ap.add_argument("--height", type=int, default=300)
    ap.add_argument("--scale", type=float, default=1.0, help="multiply both dimensions")
    ap.add_argument("--font", default=None, help="path to a bold .ttf")
    ap.add_argument("--check-palette", action="store_true", help="verify palette sync, render nothing")
    args = ap.parse_args()

    problems = verify_palette()
    if problems:
        print("PALETTE DRIFT vs client/game_manager.py:")
        for p in problems:
            print("  " + p)
        if args.check_palette:
            return 1
        print("  (rendering anyway)")
    else:
        print("palette matches client/game_manager.py")
    if args.check_palette:
        return 0

    w = int(args.width * args.scale)
    h = int(args.height * args.scale)
    out = Path(args.out)
    if not out.is_absolute():
        out = PROJECT_ROOT / out
    out.mkdir(parents=True, exist_ok=True)

    written = 0
    for rank in range(MIN_RANK, MAX_RANK + 1):
        for color in Color:
            card = Card(Kind.NUMBER, rank, color)
            render_number(rank, color, w, h, args.font).save(out / card_filename(card))
            written += 1
    render_wild(w, h, args.font).save(out / "wild.png")
    render_skip(w, h, args.font).save(out / "skip.png")
    render_back(w, h, args.font).save(out / "back.png")
    written += 3

    print(f"wrote {written} faces at {w}x{h} to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
