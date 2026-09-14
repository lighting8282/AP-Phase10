# Phase 10 for Archipelago

A solo Phase 10 implementation that ships *inside* its own apworld — Python game
and Archipelago world in one package, no mod loader, no IPC. Structured after
`Archipelago/worlds/apquest/`, which is the reference for that pattern.

The engine has no Archipelago dependency, so the rules can be tested and tuned
on their own.

## Layout

    phase10/                     the apworld package
      world.py options.py items.py locations.py regions.py rules.py
      test/                      37 world tests, run inside an AP checkout
      game/                      the engine, no Archipelago dependency
        cards.py                 card model, deck construction, scoring
        phases.py                phase specs + the solver
        engine.py                solo hand: deal, draw, discard, lay down
        autoplay.py              greedy autoplayer (difficulty measurement)
        play_in_console.py       headless runner and difficulty sweeps
    tests/test_phases.py         18 engine tests, no dependencies
    tests/yaml/Phase10.yaml      generation smoke-test YAML

## Run

Engine only, no Archipelago needed:

    python tests/test_phases.py
    cd phase10 && python -m game.play_in_console --phase 6
    cd phase10 && python -m game.play_in_console --sweep --trials 200 --max-draws 8
    cd phase10 && python -m game.play_in_console --draws --trials 200

The engine imports as a top-level `game` package rather than through
`phase10/__init__.py`, which pulls in Archipelago. That is what keeps it
testable on its own.

## Apworld

Targets Archipelago 0.6.8 and its `rule_builder` rule DSL. Needs an Archipelago
**source** checkout; the packaged release on A: is frozen and has no usable
interpreter. Link the package in once (PowerShell):

    New-Item -ItemType Junction -Path <AP checkout>\worlds\phase10 -Target <this repo>\phase10

Generation needs four of AP's dependencies: `pathspec schema colorama jinja2`.
Then, from the Archipelago root:

    python -m unittest discover -s worlds/phase10/test -t . -p "test_*.py"

**Items.** Ten phase unlocks, Wild Card, Extra Draw, Hand Size Upgrade, Skip
Card, plus filler and traps. The deck starts with no wilds at all and a small
draw budget; items build both back up.

Only as many Wild Cards and Extra Draws as logic can actually demand are
classified `progression` — the surplus is `useful`. Without that split the pool
runs about 80% progression, which fill cannot place into a location set this
small.

**Locations.** Each phase is worth up to four checks (cleared / went out / no
wilds / under par), plus ten cumulative "Hands Won" milestones. 50 at default
options.

**Rules.** Unlocking a phase only seats you at the table; the measured
difficulty gates *clearing* it. That also keeps every unlock immediately worth
something.

### Two fill failures worth remembering

Both were caught by generating, not by reading the code.

1. **Empty sphere zero.** Gating every location behind a phase unlock meant a
   fresh seed had nothing reachable, so fill had nowhere to place its first
   item. Fixed by the Hands Won milestones, which gate on nothing, plus
   precollected starting phases drawn from the easy set.
2. **Progression density.** 32 of 40 items were progression. Fixed by
   classifying surplus power items as `useful` and widening the pool to 50.

AP's own `test_empty_state_can_reach_something` and `test_fill` cover both. The
option combinations that stress them are pinned in
`phase10/test/test_capacity.py`.

## Solo model

Multiplayer Phase 10 pressures you with the race to go out. Solo replaces that
with a bounded **draw budget**: lay the phase down within `max_draws` or the
hand fails. No opponent AI needed, and every AP item that adds wilds or draws
becomes directly measurable.

`GameConfig` is the full set of knobs Archipelago items may move:
`hand_size`, `wilds_in_deck`, `skips_in_deck`, `max_draws`.

## Measured difficulty

200 autoplayed hands per cell. **These numbers overturn the intuitive read of
the phase list.**

Success rate, hand 10, `max_draws` 8:

| phase | requirement | 0W | 2W | 4W | 8W |
|---|---|---|---|---|---|
| 1 | set of 3 + set of 3 | 40% | 54% | 68% | 83% |
| 2 | set of 3 + run of 4 | 66% | 78% | 88% | 92% |
| 3 | set of 4 + run of 4 | 20% | 30% | 42% | 68% |
| 4 | run of 7 | 42% | 55% | 62% | 81% |
| 5 | run of 8 | 19% | 36% | 48% | 66% |
| 6 | run of 9 | 14% | 21% | 40% | 56% |
| 7 | **2 sets of 4** | **1%** | **6%** | **11%** | **22%** |
| 8 | 7 of one color | 38% | 42% | 48% | 68% |
| 9 | **set of 5 + set of 2** | **7%** | **16%** | **24%** | **42%** |
| 10 | **set of 5 + set of 3** | **4%** | **8%** | **8%** | **30%** |

### Findings

1. **Big sets are far harder than long runs.** Phase 7 (two sets of 4) is the
   hardest phase in the game at 1% with no wilds — well below phase 6's run of
   9 at 14%. Each rank has only 8 copies in the deck, so a set of 5 competes
   for a scarce rank, while a run slot accepts any of 8 copies of its rank.
   Runs look intimidating and are cheap; sets look cheap and are brutal.

2. **The printed phase order is not a difficulty ramp.** Roughly:
   easy (1, 2, 4, 8), medium (3, 5, 6), very hard (7, 9, 10). Since AP unlocks
   phases out of order anyway, there is no vanilla curve being destroyed.

3. **Draw budget is the primary difficulty knob; wilds are secondary.** At 20
   draws everything saturates above 80% and the wild count barely registers.
   At 8 draws the spread is wide and wilds swing outcomes hard. Tune with
   `max_draws` first.

### Logic requirements implied by the data

These are what `rules.py` actually implements. Clearing a phase costs:

- phases 1, 2, 4 (easy) — nothing beyond the unlock
- phases 3, 5, 6, 8 (medium) — 2 Wild Cards *or* 2 Extra Draws
- phases 7, 9, 10 (hard) — 4 Wild Cards *or* 4 Extra Draws

Each check tier then adds its own cost on top: Went Out wants 3 Extra Draws,
No Wilds wants 5, Under Par wants 4 Wild Cards. Those maxima are what set
`MIN_WILD_CARDS` and `MIN_EXTRA_DRAWS`, the counts above which copies stop
being progression.

## Open design questions

- **All-wild groups.** Official rules forbid completing a phase entirely with
  wilds, but printings vary. Exposed as `min_naturals_per_group`, default 1.
- **COLOR groups only solve as a phase's sole group** (fine for the stock ten).
  Mixing COLOR with SET/RUN raises `NotImplementedError` rather than silently
  answering wrong — needs joint rank+color search if Masters phases get added.


## Client

Played through commands in the client console rather than a bespoke GUI. A card
game reads fine as text, and it keeps everything in one process with no
rendering layer to maintain.

    /phases     every phase, what it needs, whether it is open
    /status     the deck and draw budget your items have built
    /play <n>   start a hand
    /hand       your cards, the discard top, draws left
    /draw [d]   draw from stock, or from the discard with `d`
    /discard <i>  discard by position
    /skip       spend a Skip to see the top three of the pile
    /take <i>   keep one of the revealed cards
    /lay        lay the phase down
    /auto       play the current hand out with the greedy player

`client/session.py` holds the whole bridge and stays pure — no sockets, no
async — so the parts worth testing can be tested directly: how received items
become a `GameConfig`, and which location IDs a finished hand is worth.

Traps do something now. Lean Deal costs two cards on the next deal, Wild Theft
one wild, Phase Lock pins you to a phase until you clear it. Received counts
only ever grow, so pending effects are tracked as received minus consumed.

### Verified against a live server

Generated a seed, hosted it, connected the real client, played 15 hands: the
server acknowledged 9 checks and missing locations went 50 to 41.

That round trip caught a bug nothing else did. Phase checks run 110–203, and
the milestones originally started at 200 — so `Phase 10 - Cleared` and
`Hands Won: 1` claimed the same address. The world builds and fills perfectly
happily with two names on one ID; the assertion only fires when the datapackage
is written during a real generation. `test_data.py` guards it now.

## Environment

Two things about this machine are worth knowing before touching AP again.

**Use the venv at `<AP checkout>\.venv`.** The system Python has
websockets 17.1, but AP 0.6.8 pins `websockets==13.1` (`<14`) and uses
`socket.open` / `socket.closed` throughout — both removed in websockets 14. The
server crashes on every client connection without the pin. This affects every
world, not just this one.

**`Generate.py` hangs with no output on this machine.** `ModuleUpdate.update()`
wants `pkg_resources`, which setuptools 84 removed, then blocks on an
interactive prompt that EOFs when there is no stdin. Setting
`ModuleUpdate.update_ran = True` before importing `Generate` skips the check
entirely; the venv also has `setuptools<81`, which fixes it properly.

## Skips

A Skip has no opponent to deny in solo play, so it digs instead. Play one to see
the top three of the draw pile and keep a card; the Skip becomes that turn's
discard, and the dig costs no draw. That sells **selection**, which is the
resource a solo player actually lacks — Extra Draw already sells volume.

Getting there took three measured attempts, and the first two were wrong.

| design | result |
|---|---|
| dig costs a draw, Skips shuffled into the deck | −1% to −7% on every phase |
| dig is free, Skips still in the deck | −4% to +2%, mostly still negative |
| dig is free, Skips **granted into hand** | +7 to +12 points per Skip |

The first two failed for the same reason, which only showed up when instrumented:
**a Skip shuffled into a 108-card deck is played 0.34 times per hand.** Two
thirds of hands never see one, so it cannot repay the density it costs every
other draw no matter how strong each use is — deepening the dig from 3 cards to
8 moved Phase 6 only from 53% to 56%. The lever was access, not power.

So Skip Cards are granted, never shuffled in: each item puts a Skip in your hand
at the start of every hand, dealt on top of your hand size so holding one costs
no room to build the phase in.

Success rate at 8 draws with stock wilds:

| phase | none | 1 Skip | 2 Skips | 4 Skips |
|---|---|---|---|---|
| 6 — run of 9 | 59% | 71% | 83% | 96% |
| 7 — 2 sets of 4 | 31% | 43% | 61% | 87% |
| 10 — set of 5 + set of 3 | 33% | 45% | 64% | 87% |

Skip Card is classified `useful`, not `progression`, so no access rule depends
on it and the fill balance is unchanged.

## Not built yet

A multi-hand game loop with scoring, and any visual presentation beyond text.

## Naming

Game rules are not copyrightable, but "Phase 10" and the card art belong to
Mattel. Shipping this publicly means giving it its own name and art.
