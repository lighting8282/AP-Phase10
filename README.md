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
- [The rules](#the-rules)
  - [The deck](#the-deck)
  - [A round](#a-round)
  - [What a phase asks for](#what-a-phase-asks-for)
  - [Hitting](#hitting)
  - [Going out](#going-out)
  - [Scoring, where low is good](#scoring-where-low-is-good)
  - [Skips](#skips)
  - [How this version differs from the box](#how-this-version-differs-from-the-box)
- [Options](#options)
- [Items and locations](#items-and-locations)
- [Layout](#layout)
- [Build and test](#build-and-test)

<!-- /toc -->

## Play it

### In a browser, with nothing to install

**<https://lighting8282.github.io/AP-Phase10/>** → **Just play**.

That is the whole game with no room, no slot and no login: the full eight
wilds, three computer opponents, and phases that open one at a time as you
clear them. **No draw budget** — a round runs until somebody empties their
hand, the way the printed game does. The run is saved in your browser, so a
reload picks up where you left off, but it lives only on that device.

**It is a race.** The opponents climb the phases too, and the run ends the
moment anybody finishes the last one — them included. If more than one of you
finishes in the same round, the lowest score wins.

Start a run at **10 phases** for the game as it comes in the box, or **20** for
those ten plus the ten measured to fill the gap they leave. There is also a
**Quick tutorial** button that walks through the screen a step at a time.

The opponents play one at a time so you can watch them, and the **Speed**
button on the table sets how long each of their turns stays on screen — `1x`,
`2x`, `4x`, or `Off` for no pause at all. It works while they are playing, so
you can hurry a turn along once it has started, and your choice is remembered.

The **Sort** button orders your hand — `by number` for the sets and runs that
make up seventeen of the twenty phases, `by colour` for the three that are
colour groups, or `Off` to leave cards where they land. Wilds and Skips go to
the end either way. Once it is on it stays on, so a card you draw arrives in
its place rather than on the end, and the choice is remembered. Sorting is not
a move: it costs no draw, ends no turn, and works while the table is playing.

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
    /sort [c]   order your hand by number, or by colour with `c`
    /draw [d]   draw from the stock, or from the discard with `d`
    /discard <i>  discard by position
    /hit <n>    play a card onto a group already on the table
    /skip       spend a Skip to see the top three of the pile
    /take <i>   keep one of the revealed cards
    /lay        lay your phase down
    /mulligan   throw back a dead opening hand
    /store      what the store sells and what you can afford
    /buy <n>    buy a store slot with AP Points
    /buy wild   buy a One-Use Wild into your hand
    /buy skip   buy a One-Use Skip into your hand
    /table      what the opponents have down
    /score      the scorecard: recent rounds and the running total
    /auto       play the current hand out with the built-in player
    /grind <n> [k]  autoplay k rounds of phase n

## Install the apworld

1. Download `phase10.apworld` from
   [the latest release](https://github.com/lighting8282/AP-Phase10/releases/latest).
2. Drop it into your Archipelago `custom_worlds/` folder.
3. Take `AP_10.yaml` from the same release for a template with every option in
   it, or generate one from the launcher. Copying a YAML from a previous seed
   works too — check the version line.

Requires **Archipelago 0.6.7 or newer**.

The version of the world your YAML expects is a line in that file:

```yaml
game: AP_10
requires:
  version: 0.6.7
  game:
    AP_10: 1.5.1
```

A seed is generated against one version of the world. After updating, generate
a new one rather than rejoining an old room with the new apworld installed:
a release that moves the items or locations moves what those names mean.

## The rules

### The deck

108 cards: the numbers **1 to 12** in four colours, two of each, plus **8
Wilds** and **4 Skips**.

A **Wild** stands in for any card. A **Skip** can never be part of a phase.

### A round

Each round is one attempt at one phase. You are dealt **10 cards**, one card
goes face up to start the discard pile, and the rest is the stock.

A turn is three steps, in this order:

1. **Draw one card** — off the top of the stock, or the face-up card from the
   discard pile.
2. **Lay down**, if your hand now satisfies the phase, and then **hit** — play
   spare cards onto any group already on the table.
3. **Discard one card**, which ends your turn.

You can only lay down once, and only when you can make the *whole* phase at
once. Once it is down it stays down: nothing later in the round takes it back.

### What a phase asks for

Every phase is one or more groups:

| | |
|---|---|
| **set of N** | N cards of the same rank. Colours do not matter — three 7s is a set of 3, whatever colour they are. |
| **run of N** | N cards of consecutive ranks. Colours do not matter, and runs **do not wrap**: 11-12-1 is not a run. |
| **N cards of one colour** | N cards sharing a colour. Ranks do not matter, and repeats are fine. |

So *set of 3 + set of 3* wants six cards in two groups of matching ranks, and
*run of 7* wants seven consecutive ranks in one group.

Wilds fill any gap, but **every group needs at least one real card** — you
cannot lay a group made entirely of Wilds.

**You choose what your wild is.** A run of 4 from `W 4 5 6` can be laid as
3-4-5-6 or as 4-5-6-7, and that decides what the group will take afterwards —
a 2 or a 7 in the first case, a 3 or an 8 in the second. When a wild could mean
more than one thing, the game lists the choices and asks. When it could only
mean one (`4 W 6 7` is a 5 and nothing else) it just lays it down.

### Hitting

Once your own phase is down, you can play spare cards onto any group on the
table, **including your opponents'**. That is how you empty your hand.

- a **set** takes another card of its rank
- a **run** takes either end, and grows as it does
- a **colour group** takes another card of its colour
- **no group ever takes a Skip**

You cannot hit before your own phase is down, which is what stops hitting being
a way to dump cards you could not otherwise place.

### Going out

Shed your last card — by discarding it, or by hitting it onto a group — and you
have **gone out**. The round ends immediately for everyone.

### Scoring, where low is good

When the round ends, everyone still holding cards scores what is in their hand:

| | |
|---|---|
| a 1 to 9 | **5** points |
| a 10 to 12 | **10** points |
| a Skip | **15** points |
| a Wild | **25** points |

Going out scores **zero**. Points accumulate across rounds, and **the lowest
total is the best** — so being caught holding a Wild is the most expensive
thing that can happen to you.

Laying your phase down and being caught still clears the phase. You just pay
for what you were holding.

### Skips

A Skip is never part of a phase, and it does one of two things depending on
where you are playing.

**Without Archipelago**, it is the printed rule: **discard it and choose who
loses their turn**. Draw as usual, then throw the Skip instead of a card, and
say which player sits the next one out. It does not have to be the player whose
turn comes next — the one worth denying is usually whoever is closest to going
out.

The computer players do exactly the same, and **you are a target like anybody
else**. When one is thrown at you, the table simply comes round twice before
your next turn, and the log and your own seat both say so.

**In an Archipelago seed**, play it *before* you draw to look at the **top
three cards of the stock and keep one**, free. It costs you no draw. That is not
the printed rule, and it is deliberate — the access rules in a seed are built on
measured clear rates, and every one of those was measured with the dig.

Either way the Skip itself becomes that turn's discard, so playing one sheds
the 15 points it would have cost you to be caught holding it.

**A played Skip cannot be picked up.** It stays face up on the pile, where you
can see it was spent, but it is out of play — nobody takes it back to deny
another turn with the same card. It can come round again only the way every
other card does: when an exhausted stock is reshuffled from the pile.

### How this version differs from the box

- **Twenty phases**, not ten. The extra ten were measured to fill a gap the
  original ten left: none of the printed phases clears more than about two
  thirds of the time, so every one of them was a fight.
- **In an Archipelago seed, Skips are dealt to you rather than shuffled in.**
  Shuffled in, one turns up only about once every three hands — too rarely for
  an *item* to be worth the density it costs every other draw, so each Skip
  Card puts one in your hand instead. Free play deals the box's deck: the four
  Skips are shuffled in, and everybody at the table gets ten random cards off
  it.
- **In an Archipelago seed a Skip digs rather than denying a turn**, for the
  reason above. Only there — free play denies, and lets you pick the target the
  way the box does. The computer players do the same: they throw Skips at
  whoever is closest to going out, and that can be you.
- **If the stock runs out**, the discard pile is shuffled back into it, leaving
  the top card face up.
- **In an Archipelago seed**, the deck starts with *no* Wilds and you have a
  limited number of draws per round; items put the Wilds back and raise the
  budget. Free play has all eight Wilds and no draw limit.

## Options

Set in your YAML. The launcher's template lists every one with its full
explanation; these are the ones that change the shape of a run most.

| Option | Default | What it does |
|---|---|---|
| `goal` | all phases | Clear every phase, or just Phase 10 |
| `checks_per_phase` | 2 | 1–4 checks per phase: cleared, under par, no wilds, went out |
| `phases_to_win` | 20 | How many phases `all_phases` asks for; `random-range-10-20` for a random length |
| `skip_mode` | `dig` | What a Skip does: `dig` looks at three cards, `deny` costs somebody a turn |
| `store_slots` | 6 | Checks you can buy outright with AP Points; 0 for none |
| `store_gating` | `ladder` | `ladder` opens slots one at a time; `all_at_once` opens every slot together and lets you pick the order |
| `store_buff_points` | 8 | Spending money for the store's one-use cards; 0 for none |
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

**AP Point** buys a check outright in the store, in one of two shapes set by
`store_gating`:

- **`ladder`** (the default) — prices climb 1, 1, 1, 1, 2, 2, 3, 3 and the
  slots open one at a time: your first point opens slot 1, your second slot 2,
  and so on. A store check from your very first point, but the order is set.
- **`all_at_once`** — every slot costs 1, and they all open together once you
  hold enough to buy the lot: 6 points at 6 slots. Nothing until then, but
  then you choose the order. It also fits a full store into tight seeds that
  the ladder has to trim.

Either way, spending can't strand you: once a slot is open you can always
afford it, whatever you bought before.

Connected to a room, each slot **says what it is holding** — the item's own
name, and whose it is when it is not yours. That is a scout, not a hint: it
costs no hint points and tells the room nothing.

The store also sells a **card** rather than a check: a **One-Use Wild** for two
points or a **One-Use Skip** for one, as often as you can afford them. The card
goes straight into your hand, it costs you no draw, and it is gone the moment
you play or discard it — it is one more card to shed, and one more to be caught
holding. They are there for the round where the deck will not give you the one
card you need.

**Buying cards can never cost you a check.** The store holds back what your
unbought slots still cost and only lets you spend what is left over, so no
amount of buying can strand a location. `store_buff_points` sets how much
spending money the seed carries beyond the slots; 0 turns the cards off.

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
      test/                      world and session tests (tools/run_world_tests.py)
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

Pages serves each file with its own ten-minute cache, so a visitor can end up
holding a new module beside an old one — a build that never existed. Every
module URL carries a hash of the sources, so a change moves all of them at
once:

    python tools/stamp_build.py            # after changing anything in docs/src
    python tools/stamp_build.py --check    # fails if a stamp is stale

Most of the world's own tests — the session, the store, the data tables, the
save payload — run with nothing installed:

    python tools/run_world_tests.py

The handful that build a multiworld need an Archipelago **source** checkout with
this package linked into `worlds/`, and that run, from the AP root, is the
authority:

    SKIP_REQUIREMENTS_UPDATE=1 python -m unittest discover -s worlds/phase10/test -t .

Packaging:

    python tools/build_apworld.py                          # dist/phase10.apworld
    python tools/build_apworld.py --verify dist/phase10.apworld

    python tools/export_template.py                        # dist/AP_10.yaml
    python tools/cut_release.py --dry-run                  # what a release would do
    python tools/cut_release.py                            # and do it

`cut_release.py` takes the version from `phase10/archipelago.json`, runs the
whole battery, builds and verifies the apworld, tags, publishes, and then
retires every older release and tag -- only the current one should exist. It
needs the `gh` CLI and refuses on a dirty tree, the wrong branch, a branch that
is not level with origin, a failing check, or a tag that already exists.

It attaches two files: the apworld, and the YAML options template when
Archipelago can be reached through `AP_ROOT`. Without a checkout it says so and
cuts the release without the template.

Every number and every "always" or "never" in the rules section above is
asserted against the engine, because prose is where a rule drifts from the code
with nothing failing:

    python tools/check_rules_doc.py

[DEVELOPMENT.md](DEVELOPMENT.md) has the rest: what was measured, why the
numbers above are the numbers, and the bugs worth not reintroducing.
