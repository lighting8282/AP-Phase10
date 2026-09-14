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
    tests/test_phases.py         engine tests, no dependencies
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
    /grind <n> [k]  autoplay k rounds of phase n
    /score      the scorecard: recent rounds and the running total

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

## Game and scoring

A `PhaseHand` is one attempt at one phase and knows nothing about what came
before it. `game/game.py` wraps a sequence of them into a game with a round
count, a history and a running score.

Scoring follows the printed rules — you score the cards still in hand when the
hand ends, and lower is better. Going out is worth zero, a phase laid down with
junk left over costs whatever that junk is worth, and a failed hand costs the
lot. Cards 1–9 are 5, 10–12 are 10, a Skip is 15, a Wild is 25.

Config is passed per round rather than held, because items keep arriving: the
deck you play round nine with is not the one you played round one with.

The session keeps no separate tallies — `hands_won` and `cleared_phases` are
properties reading off the scorecard, so the two cannot drift.

`/grind <phase> [rounds]` autoplays up to 50 rounds through the same policy the
difficulty measurements were taken with. The Hands Won milestones run to thirty
and clicking through that by hand is not a game.

**One limitation.** Commands are synchronous while sending is async, so a long
grind blocks the loop that drains checks: every round in one grind plays with
the deck it started with, and items earned along the way only apply once it
finishes. Verified live — a 30-round grind ran all 30 at the starting config.
Short grinds keep the two closer together.

## UI

`client/game_manager.py` adds a Phase 10 tab to the client window, alongside the
usual Archipelago log and hints tabs.

- the hand as colour-coded cards — click one to discard it
- round, running score, wins, phases cleared
- the current phase and its objective, draws left, stock, discard top, skips held
- Draw / Take discard / Lay down / Dig / Auto / Score
- a phase row: blue is unlocked, green is cleared, grey is locked out
- when a Skip reveals the top of the pile, the three cards appear as buttons

Two things worth knowing about how it is put together.

**Every control routes through the command processor.** A button runs exactly
what typing the command runs, so the two cannot drift — which is the same reason
`/auto` and `/grind` share one autoplayer.

**The view redraws only when a signature of the visible state changes.** A card
game is idle between clicks; tearing down a dozen widgets four times a second to
redraw an unchanged hand is waste.

Kivy is imported lazily inside `make_gui`, so it stays off the import path for
the headless tests and for anyone running without a display.

### Checking it

Kivy needs a real window, so the UI is not unit tested. `tests/ui_check.py`
launches it with a seeded session, dispatches real button events to prove the
bindings work, screenshots the result and exits:

    <AP checkout>/.venv/Scripts/python.exe tests/ui_check.py out.png

It needs `kivy==2.3.1` and kivymd (AP pins a git commit) in the venv. Note that
`kvui` must be imported before anything from `kivy` — it asserts on that for
frozen-build compatibility, so do not let an import sorter reorder those lines.

## Persistence

The scorecard lives in Archipelago's Data Storage under
`phase10_game_<team>_<slot>`, so it follows the slot rather than the machine:
reconnect anywhere and the rounds, score and phase history come back.

Saved on every settled round; restored on connect before anything is written
back. That ordering matters — saving before the restore lands would overwrite a
real scorecard with the empty one just built from slot_data, so the context
tracks `needed / requested / done` and refuses to save until the restore has
resolved.

**Checked locations are deliberately not stored.** The server is the authority
on those; a second copy could only ever disagree with it. What is stored is the
part the server has no idea about — rounds, score, spent traps, an active Phase
Lock.

The payload comes back over the network, so nothing in it is trusted. A
malformed, truncated or foreign-version payload is discarded whole and the game
starts fresh rather than half-loading; `test_persistence.py` covers wrong types,
bad versions, missing fields, unknown hand states and out-of-range values.

Verified live: played to 530 points over 12 rounds, disconnected, reconnected
with a fresh context, got 12 rounds and 530 points back, and carried on to round
15 without restarting the numbering.

## Not built yet

Score is local only — it resets on reconnect, since the session is rebuilt from
slot_data and the server tracks checks, not points.

## Naming

Game rules are not copyrightable, but "Phase 10" and the card art belong to
Mattel. Shipping this publicly means giving it its own name and art.
