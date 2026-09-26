# AP_10

A twenty-phase rummy game, playable on its own in a browser or as an
[Archipelago](https://archipelago.gg) randomizer world. The rules, the computer
opponents and the Archipelago world all ship in one package — no mod loader, no
second process.

## Contents

<!-- toc -->

- [Play it](#play-it)
  - [In a browser, with nothing to install](#in-a-browser-with-nothing-to-install)
  - [In a browser, connected to a room](#in-a-browser-connected-to-a-room)
  - [From the Archipelago launcher](#from-the-archipelago-launcher)
- [Install the apworld](#install-the-apworld)
- [How a hand plays](#how-a-hand-plays)
- [Options](#options)
- [Items and locations](#items-and-locations)
- [Layout](#layout)
- [Build and test](#build-and-test)

<!-- /toc -->

## Play it

### In a browser, with nothing to install

**<https://lighting8282.github.io/AP-Phase10/>** → **Just play**.

That is the whole game with no room, no slot and no login: the full eight
wilds, three computer opponents, and twenty phases that open one at a time as
you clear them. **No draw budget** — a round runs until somebody empties their
hand, the way the printed game does. The run is saved in your browser, so a
reload picks up where you left off, but it lives only on that device.

### In a browser, connected to a room

Same page. Put in the server address, your slot name and any password, and
press **Connect**. Your phases, wilds, draws and skips arrive as Archipelago
items, and your cleared phases send checks.

Works on a phone.

### From the Archipelago launcher

Install the apworld (below), then pick **Phase 10 Client** in the launcher. It
plays through commands in the client console:

    /phases     every phase, what it needs, whether it is open
    /status     the deck and draw budget your items have built
    /play <n>   start a hand
    /hand       your cards, the discard top, draws left
    /draw [d]   draw from the stock, or from the discard with `d`
    /discard <i>  discard by position
    /hit <n>    play a card onto a group already on the table
    /skip       spend a Skip to see the top three of the pile
    /take <i>   keep one of the revealed cards
    /lay        lay your phase down
    /mulligan   throw back a dead opening hand
    /store      what the store sells and what you can afford
    /buy <n>    buy a store slot with AP Points
    /table      what the opponents have down
    /score      the scorecard: recent rounds and the running total
    /auto       play the current hand out with the built-in player
    /grind <n> [k]  autoplay k rounds of phase n

## Install the apworld

1. Download `phase10.apworld` from
   [the latest release](https://github.com/lighting8282/AP-Phase10/releases/latest).
2. Drop it into your Archipelago `custom_worlds/` folder.
3. Generate a YAML template from the launcher, or copy one from a previous
   seed and check the version line.

Requires **Archipelago 0.6.7 or newer**.

The version of the world your YAML expects is a line in that file:

```yaml
game: AP_10
requires:
  version: 0.6.7
  game:
    AP_10: 0.9.0
```

Releases that change the items or locations need a new seed; each release says
so at the top of its notes.

## How a hand plays

Each hand is one attempt at one phase — *two sets of three*, *a run of seven*,
*seven cards of one colour*, and so on up to twenty.

You draw a card and discard a card, and the moment your hand satisfies the
phase you lay it down. After that you keep going: you can play spare cards onto
any group on the table, yours or an opponent's, and shed your whole hand to go
out. Whatever you are still holding when the round ends is what it costs you,
and **lower is better**.

A round ends on whichever comes first:

- **your draw budget runs out** — the solo clock, raised by Extra Draw items
- **an opponent goes out** — the table clock, three seats racing you

Laying your phase down clears it either way. The clocks only stop you shedding
the rest.

Two cards are special. A **Wild** stands in for anything except a Skip. A
**Skip** is not dead weight here — play it to look at the top three of the
draw pile and keep one, free, without spending a draw.

## Options

Set in your YAML. The launcher's template lists every one with its full
explanation; these are the ones that change the shape of a run most.

| Option | Default | What it does |
|---|---|---|
| `goal` | all phases | Clear every phase, or just Phase 10 |
| `checks_per_phase` | 2 | 1–4 checks per phase: cleared, under par, no wilds, went out |
| `store_slots` | 6 | Checks you can buy outright with AP Points; 0 for none |
| `starting_phases` | 2 | How many phases you open with |
| `opponents` | 3 | Computer players at the table; 0 for the pure solo game |
| `starting_draws` | 4 | Draws per hand before Extra Draw items |
| `extra_draw_items` | 5 | Extra Draw items in the pool |
| `wild_card_items` | 8 | Wilds put back into the deck, which starts with none |
| `skip_card_items` | 4 | Skips dealt into your hand each round |
| `hand_size_upgrades` | 2 | Extra cards dealt each round |
| `trap_chance` | 0 | Percentage of filler replaced by traps |
| `death_link` | off | A death is a lost hand |

## Items and locations

**Items.** Twenty phase unlocks, Wild Card, Extra Draw, Hand Size Upgrade and
Skip Card. The deck starts with no wilds at all and a small draw budget; items
build both back up.

**AP Point** buys a check outright in the store. Each slot has a price, and a
slot opens once you hold enough points to have afforded every cheaper one — so
you can buy them in any order.

**Filler.** A **Mulligan** throws back a dead opening hand before your first
draw. A **Score Reduction** takes 25 points off your total, which is what a
Wild left in your hand costs you.

**Traps**, when enabled: **Phase Lock** pins you to the phase you just lost,
**Lean Deal** costs you two cards on one hand, **Wild Theft** takes a wild out
of the deck for one hand.

**Locations.** Each phase is worth up to four checks — clearing it, clearing it
inside half your draw budget, clearing it without a wild, and shedding your
whole hand to go out, in that order. On top of those are ten cumulative "hands
won" milestones, and one location per store slot. **56 at default options.**

## Layout

    phase10/                     the apworld package
      world.py                   the World subclass
      options.py items.py locations.py regions.py rules.py data.py
      client/                    the in-process client
        context.py               CommonContext, commands, the AP loop
        session.py               items and slot data -> a playable run
        game_manager.py          the Kivy tab
      game/                      the engine, no Archipelago dependency
        cards.py                 card model, deck construction, scoring
        phases.py                phase specs, the solver, melds
        engine.py                one hand: deal, draw, discard, lay down, hit
        opponents.py             the computer seats
        game.py                  many hands, one scorecard
        autoplay.py              greedy autoplayer (difficulty measurement)
        play_in_console.py       headless runner and difficulty sweeps
      test/                      world and session tests, run in an AP checkout
      docs/                      the setup and game-info pages AP ships

    docs/                        the browser client, served by GitHub Pages
      src/                       a port of game/ and client/ to JavaScript
      test/                      its own tests, plus the differential fixtures

    tests/test_phases.py         engine tests, no dependencies
    tests/test_game.py           game, opponents and scorecard tests
    tests/ui_check.py            drives the Kivy tab and screenshots it
    tests/yaml/                  generation smoke tests, solo and multiworld

    tools/                       build, export and check scripts

## Build and test

The engine has no Archipelago dependency, so it runs on its own:

    python tests/test_phases.py
    python tests/test_game.py
    cd phase10 && python -m game.play_in_console --phase 6

The browser client, locally — use this rather than `python -m http.server`,
which sends no cache headers and will serve you the previous build:

    python tools/serve_docs.py
    cd docs && node test/session_test.mjs

The world's own tests need an Archipelago **source** checkout with this package
linked into `worlds/`, and run from its root:

    SKIP_REQUIREMENTS_UPDATE=1 python -m unittest discover -s worlds/phase10/test -t .

Packaging:

    python tools/build_apworld.py                          # dist/phase10.apworld
    python tools/build_apworld.py --verify dist/phase10.apworld

[DEVELOPMENT.md](DEVELOPMENT.md) has the rest: what was measured, why the
numbers above are the numbers, and the bugs worth not reintroducing.
