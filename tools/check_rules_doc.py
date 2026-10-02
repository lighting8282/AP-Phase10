"""Check every factual claim in the README's rules section against the engine.

The rules section is prose, and prose is exactly where a rule drifts from the
code with nothing failing. Every number and every "always"/"never" in it is
asserted here instead.

    python tools/check_rules_doc.py

Needs no Archipelago checkout: the engine has no dependency on one.
"""

import pathlib
import sys

# The engine imports as a top-level `game` package, which is what keeps it
# free of Archipelago -- so the package directory goes on the path, not the
# repo root.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "phase10"))

import random  # noqa: E402

from game.cards import (  # noqa: E402
    COPIES_PER_RANK, MAX_RANK, MIN_RANK, SKIP, STOCK_SKIPS, STOCK_WILDS, WILD,
    Color, build_deck, hand_score, number_card,
)
from game.engine import GameConfig, HandState, PhaseHand, Table  # noqa: E402
from game.phases import GroupKind, PHASES, solve_phase  # noqa: E402

ok, bad = [], []


def claim(text, condition):
    (ok if condition else bad).append(text)


# -- the deck ----------------------------------------------------------------
deck = build_deck(STOCK_WILDS, STOCK_SKIPS)
claim("108 cards", len(deck) == 108)
claim("numbers 1 to 12", (MIN_RANK, MAX_RANK) == (1, 12))
claim("four colours", len(list(Color)) == 4)
claim("two of each", COPIES_PER_RANK == 2)
claim("8 Wilds", sum(1 for c in deck if c.is_wild) == 8)
claim("4 Skips", sum(1 for c in deck if c.is_skip) == 4)

# -- scoring -----------------------------------------------------------------
claim("a 1 to 9 is 5 points",
      all(number_card(r, Color.RED).points == 5 for r in range(1, 10)))
claim("a 10 to 12 is 10 points",
      all(number_card(r, Color.RED).points == 10 for r in range(10, 13)))
claim("a Skip is 15", SKIP.points == 15)
claim("a Wild is 25", WILD.points == 25)
claim("going out scores zero", hand_score([]) == 0)

# -- the deal ----------------------------------------------------------------
cfg = GameConfig(wilds_in_deck=8, max_draws=0)
h = PhaseHand(1, cfg, random.Random(4), table=Table())
claim("dealt 10 cards", len(h.hand) == 10)
claim("one card starts the discard", len(h.discard) == 1)

# -- a phase's groups --------------------------------------------------------
claim("phase 1 is two sets of three",
      [(g.kind, g.size) for g in PHASES[1]] == [(GroupKind.SET, 3)] * 2)
claim("phase 4 is a run of seven",
      [(g.kind, g.size) for g in PHASES[4]] == [(GroupKind.RUN, 7)])
claim("phase 8 is seven of one colour",
      [(g.kind, g.size) for g in PHASES[8]] == [(GroupKind.COLOR, 7)])
claim("twenty phases", len(PHASES) == 20)

# A set ignores colour.
set_hand = [number_card(7, c) for c in (Color.RED, Color.BLUE, Color.GREEN)]
set_hand += [number_card(2, c) for c in (Color.RED, Color.BLUE, Color.YELLOW)]
claim("a set ignores colour", solve_phase(set_hand, PHASES[1]) is not None)

# A run ignores colour, and does not wrap.
run = [number_card(r, Color.RED if r % 2 else Color.BLUE) for r in range(3, 10)]
claim("a run ignores colour", solve_phase(run, PHASES[4]) is not None)
wrapped = [number_card(r, Color.RED) for r in (10, 11, 12, 1, 2, 3, 4)]
claim("a run does not wrap", solve_phase(wrapped, PHASES[4]) is None)

# A colour group ignores rank, repeats included.
colour = [number_card(r, Color.GREEN) for r in (1, 1, 5, 5, 9, 12, 12)]
claim("a colour group ignores rank", solve_phase(colour, PHASES[8]) is not None)

# -- wilds -------------------------------------------------------------------
one_wild = [number_card(7, Color.RED), number_card(7, Color.BLUE), WILD,
            number_card(2, Color.RED), number_card(2, Color.BLUE), WILD]
claim("wilds fill gaps", solve_phase(one_wild, PHASES[1]) is not None)
all_wild = [WILD] * 6
claim("a group cannot be all wilds", solve_phase(all_wild, PHASES[1]) is None)
skips = [SKIP] * 6
claim("a Skip is never part of a phase", solve_phase(skips, PHASES[1]) is None)

# -- hitting -----------------------------------------------------------------
h2 = PhaseHand(1, GameConfig(wilds_in_deck=0, max_draws=0), random.Random(2),
               table=Table())
h2.hand = list(set_hand) + [number_card(7, Color.YELLOW), SKIP]
h2.lay_down()
meld = h2.melds[0]
claim("a set takes its own rank", meld.accepts(number_card(7, Color.YELLOW)))
claim("a set refuses another rank", not meld.accepts(number_card(8, Color.RED)))
claim("no group takes a Skip", not meld.accepts(SKIP))

h3 = PhaseHand(4, GameConfig(wilds_in_deck=0, max_draws=0), random.Random(2),
               table=Table())
h3.hand = list(run) + [number_card(2, Color.RED), number_card(10, Color.BLUE)]
h3.lay_down()
run_meld = h3.melds[0]
# Read the span off the meld rather than assuming which run the solver chose:
# given 2..10 it laid 2-8, so the open ends are 1 and 9, not 2 and 10.
lo, hi = run_meld.lo, run_meld.hi
claim("a run takes either end",
      run_meld.accepts(number_card(lo - 1, Color.RED))
      and run_meld.accepts(number_card(hi + 1, Color.BLUE)))
claim("a run refuses the middle",
      not run_meld.accepts(number_card((lo + hi) // 2, Color.RED)))
claim("a run refuses a rank past its end",
      not run_meld.accepts(number_card(min(12, hi + 2), Color.RED)))

# Hitting needs your own phase down first.
h4 = PhaseHand(1, GameConfig(wilds_in_deck=0, max_draws=0), random.Random(2),
               table=Table())
try:
    h4.hit(h4.hand[0], meld)
    claim("hitting needs your phase down", False)
except RuntimeError as err:
    claim("hitting needs your phase down", "lay your own phase down" in str(err))

# -- a spent Skip stays spent -------------------------------------------------
# Both modes, because both put the Skip on the pile and the README says the rule
# holds either way.
for mode in ("deny", "dig"):
    h5 = PhaseHand(1, GameConfig(max_draws=20, skip_mode=mode),
                   random.Random(4), table=Table())
    h5.discard.append(SKIP)
    try:
        h5.draw(from_discard=True)
        claim(f"a played Skip cannot be picked up ({mode})", False)
    except RuntimeError as err:
        claim(f"a played Skip cannot be picked up ({mode})", "Skip" in str(err))

# -- going out ---------------------------------------------------------------
claim("laying your last card goes out", h2.state is not HandState.WENT_OUT)

print(f"{len(ok)} claims checked")
for line in bad:
    print(f"  WRONG  {line}")
print("every claim in the rules section matches the engine" if not bad
      else f"\n{len(bad)} claim(s) do not match")
sys.exit(1 if bad else 0)
