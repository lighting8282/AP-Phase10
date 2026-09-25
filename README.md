# AP_10

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
    tests/yaml/solo/             single-slot generation smoke test
    tests/yaml/multi/            four-slot multiworld, two of them this game

## Run

To drive the browser client locally:

    python tools/serve_docs.py        # http://127.0.0.1:8137, no-store

Use this rather than `python -m http.server`, which sends no cache headers --
browsers then heuristically cache ES modules, and you spend an afternoon
testing the previous build. Local HTTP also still reaches `ws://` servers; the
published HTTPS site can only reach `wss://`.

Engine only, no Archipelago needed:

    python tests/test_phases.py
    cd phase10 && python -m game.play_in_console --phase 6
    cd phase10 && python -m game.play_in_console --sweep --trials 200 --max-draws 8
    cd phase10 && python -m game.play_in_console --draws --trials 200

The engine imports as a top-level `game` package rather than through
`phase10/__init__.py`, which pulls in Archipelago. That is what keeps it
testable on its own.

## Apworld

Targets Archipelago **0.6.7**, the current stable release, and its
`rule_builder` rule DSL. Needs an Archipelago
**source** checkout; the packaged release on A: is frozen and has no usable
interpreter. Link the package in once (PowerShell):

    New-Item -ItemType Junction -Path <AP checkout>\worlds\phase10 -Target <this repo>\phase10

Generation needs four of AP's dependencies: `pathspec schema colorama jinja2`.
Then, from the Archipelago root:

    SKIP_REQUIREMENTS_UPDATE=1 python -m unittest discover -s worlds/phase10/test -t . -p "test_*.py"

That environment variable is not optional dressing.
`ModuleUpdate.RequirementsSet.add` runs `update_ran &= _skip_update` every time
a world registers a requirements file, so the flag Archipelago's own
`test/__init__.py` sets gets undone by any world discovered afterwards. The next
`update()` call then blocks on an input prompt that EOFs, naming whichever world
import order happened to reach -- so it reads as a random failure in a different
world each run. The variable is read before `ModuleUpdate` loads, which is why
no test module can fix it from inside.

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

### The log

One feed, chronological, carrying both your own game events and everything the
room says -- items sent and received, hints, joins, chat. The browser client was
blind to the multiworld before this; the desktop client gets the same thing free
from Archipelago's own log tab.

Messages arrive as nodes rather than a flat string, and the nodes carry what a
player actually scans for, so they are rendered rather than flattened:

- **items by classification** -- progression, useful, trap, filler -- straight
  from what `items.py` declares, so a Wild Card and a Phase Lock never look
  alike
- **your own name underlined**, to pick your own traffic out at a glance
- locations, entrances, and the server's own colour directives

The feed follows new lines only when you were already at the bottom -- yanking
the scroll while somebody is reading back is worse than missing a line -- and
caps at 300 lines, because a busy room never stops.

Verified against the four-slot multiworld: a second client joined as another
slot and sent checks, and the feed showed
`QuestPal sent Phase 8 Unlocked to P10Default (Right Room Enemy Drop)` with the
item purple for progression, the location green, and P10Default underlined as
self -- immediately followed by this client's own `Phase 8 unlocked.`

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
websockets 17.1, but AP pins `websockets==13.1` (`<14`) and uses
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

## Twenty phases

The stock ten, plus ten measured at the same baseline (0 wilds, 8 draws, greedy
autoplayer) and ordered by that measurement:

| phase | requirement | clears |
|---|---|---|
| 11 | 5 cards of one colour | 93% |
| 12 | set of 3 + set of 2 | 90% |
| 13 | run of 5 + set of 2 | 79% |
| 14 | 6 cards of one colour | 72% |
| 15 | run of 4 + run of 4 | 58% |
| 16 | run of 4 + run of 4 + set of 2 | 52% |
| 17 | run of 5 + set of 3 | 50% |
| 18 | run of 6 + set of 3 | 31% |
| 19 | run of 5 + run of 5 | 20% |
| 20 | 3 sets of 3 | 12% |

They fill a hole the originals left: nothing among the stock ten clears above
66%, so every phase was a fight and a bad opening had nowhere to go.

### A ceiling you cannot design past

A phase can never ask for more cards than a hand holds. Three sets of four
wants twelve; at a hand size of ten it measured a flat 0% even with eight wilds
and sixteen draws, which is how the constraint surfaced. `MAX_PHASE_CARDS` and
a test pin it now.

### Anchored groups

`SET` and `COLOR` can be pinned to a particular rank or colour -- `SET(3, rank=7)`
is three 7s, `COLOR(5, color=GREEN)` is five green cards. Nothing ships using
them yet; they exist for phases 21 and up.

Anchoring runs opposite to the intuition that a named target is simpler. A free
group lets you pivot to whichever rank or colour the deal was kind about; an
anchored one does not. Measured, five cards of a *named* colour clears 49%
where five of any one colour clears 79%, on the same budget. Each rank has only
eight copies in the deck, so an anchored SET is scarcer still.

`RUN` cannot be anchored, and COLOR still cannot be mixed with SET or RUN --
that needs joint rank-and-colour search.

### Two ID collisions, one caught and one nearly missed

Phase unlocks take IDs 1..PHASE_COUNT. At twenty phases `Phase 20 Unlocked`
walked straight onto `Wild Card` at ID 20; `test_item_ids_are_unique` caught it,
which is exactly what it is for. The fixed items now start at 50 and a test
pins the invariant rather than the symptom.

Location addresses were the same shape of problem. Phase checks run to
`100 + phase * 10 + tier`, which at twenty phases reaches 303 -- head on into
milestones that had been moved to 300 precisely to avoid the last collision.
They are at 400 now.

### The pool could not absorb the locations

Twenty phases at four checks each is ninety locations, and every power item is
capped by something real: the deck holds eight wilds, extra draws stop buying
anything past eight total, skips and hand size have their own ceilings. The
remainder can only be filler, and it measured:

| checks/phase | locations | power | filler |
|---|---|---|---|
| 1 | 30 | 10 | 7% |
| **2** | **50** | **19** | **26%** |
| 3 | 70 | 19 | 47% |
| 4 | 90 | 19 | 59% |

At four, the pool held **thirty-five Mulligans** -- an infinite supply of
redeals. The default is two checks a phase now, which keeps the world at fifty
locations, the size the item pool was actually built for, while doubling the
phases. Tests guard both the ratio and the single-filler count.


## Opponents

Three computer seats share the deck by default. They build toward their own
phases, lay down, shed, and going out ends your round wherever it stands. Each
seat carries its phase between rounds, so the table stiffens as the run goes on.

`Table` owns the stock and the discard; `PhaseHand` holds only your hand and
reads the rest through properties. With no seats a hand builds its own private
table and behaves exactly as it did before the split -- which is the point. The
whole existing suite passed the refactor untouched, so the solo measurements
are the regression guard for it.

Skill is two probabilities over one policy rather than three policies:
`discard_awareness` (does it look at the pile at all this turn) and
`discard_error` (does it throw the second-best card). At 1.0/0.0 it is the
greedy autoplayer exactly. Mid is 0.7/0.25, and costs the player 1 to 13 points
of clear rate across the ten phases at eight draws.

### The two clocks do not layer

The guess was that the draw budget would bind early and the opponents would
take over once Extra Draw items piled up. The opposite happens, and it is
structural rather than a tuning miss:

| fastest of N goes out at turn | 1 seat | 2 seats | 3 seats |
|---|---|---|---|
| opponents on phase 1 | 7.8 | 5.6 | **4.9** |
| opponents on phase 7 | 14.6 | 9.0 | **8.0** |

One seat needs about eight turns. Three seats race, and the round ends on the
*fastest* of them -- a minimum-of-N effect that lands near turn five and barely
moves with phase or skill. So the race resolves before a large budget can
matter. Going from 4 draws to 8 buys real clear rate; from 8 to 14 buys nothing
at all.

That made roughly eight of the twelve Extra Draw items dead, so the pool was
trimmed to match what the measurements say is worth having: `extra_draw_items`
now defaults to 5, ranging 5 to 8.

### A latent bug the trim uncovered

The old range started at 3, but the No Wilds check on every phase asks for
`Extra Draw x5`. At 3 or 4 those checks are unreachable and generation fails
outright:

    extra_draw_items=3: UNREACHABLE  Phase 1 - No Wilds unreachable
    extra_draw_items=4: UNREACHABLE  Phase 1 - No Wilds unreachable
    extra_draw_items=5: reachable

The range start is now tied to `MIN_EXTRA_DRAWS`, and a test asserts the tie so
the two cannot drift apart again.

### Hitting

Laying down is no longer terminal. It sets `laid` and clears the phase, while
`state` stays IN_PROGRESS so the round carries on and the rest of the hand can
be shed onto anything already on the table -- your groups or an opponent's. The
hand settles when a clock actually runs out, and once the phase is down neither
clock is a loss: running out of draws and losing the race both settle as
PHASE_LAID, because a clear cannot be taken back.

Hand size only falls by hitting. Drawing one and discarding one is net zero, so
going out means hitting enough that a final discard empties the hand, which is
how the real game works.

Two things that restructure broke, both found by measuring rather than by the
suite:

  * Discarding your *last* card was not going out. `discard_card` had no such
    check, so a player who shed down to one card and threw it finished holding
    nothing and was never credited with it.
  * **Under Par** became unearnable on the easy phases. It asks whether you
    cleared inside half your budget, but the round now runs on past the
    lay-down burning the rest of it, so `draws_used` was always the maximum. It
    measures `draws_at_lay_down` now -- 0% on phases 1 and 11 before the fix,
    49% and 87% after.

### What the tiers are worth now

At 4 wilds and 9 draws, with three opponents:

| phase | Cleared | Went Out | No Wilds | Under Par |
|---|---|---|---|---|
| 1 | 68% | 7% | 29% | 56% |
| 6 | 35% | 24% | 7% | 20% |
| 11 | 96% | 7% | 58% | 94% |
| 20 | 32% | 23% | 6% | 18% |

### The tier order is a tuning decision

`checks_per_phase` takes a *prefix* of TIERS, so the order decides which tiers
a low setting keeps. Measured per attempt across all twenty phases:

| mean rate | Cleared | Under Par | No Wilds | Went Out |
|---|---|---|---|---|
| 3 opponents | 57% | 47% | 23% | 23% |
| solo | 66% | 39% | 25% | 17% |
| **phases under 2%, solo** | 0 | 0 | 1 | **8** |

Went Out was second. Solo it is 0% on eight of the twenty phases -- the small
ones, which leave more cards in hand and fewer groups to hit onto, so there is
nowhere to put them. At the default of two checks that put a fifth of a solo
world out of reach. It is also bimodal rather than merely low: 40-79% on
phases 15-19, where a big multi-group phase leaves almost nothing in hand.

The order is now Cleared, Under Par, No Wilds, Went Out, which also reads as a
ladder: clear it, clear it fast, clear it clean, clear it completely. Under Par
tracks Cleared closely and has no dead cases in either configuration.

`earned_tiers` walks TIERS rather than the order it collected them in, so a
future reorder reaches it for free -- it did not, before, and the reorder
silently failed to take until the tests caught it.

Under Par's gate dropped from Wild Card x4 to x2. It is the second tier now, so
at the default it gates every phase's other check, and x4 is also the
hard-phase gate -- most of the world would have funnelled through one
threshold.

### Still not built

A Skip still digs rather than skipping a player's turn. With opponents at the
table it has a real meaning again, and that conflict is unresolved.

### Keeping the two ports honest

`crosscheck_opponents.mjs` replays recorded Python turns through the JS port and
compares every seat's hand size, laid/out state and score, the discard top, the
stock depth and the winner, turn by turn. Both clients read the same seed, so a
divergence means they disagree about whether you lost a round -- and nothing
else would catch it.

It earned itself immediately, on three separate bugs:

  * `card.points` is a *function* in the JS port, not a property, so every
    tie-break was `-undefined` -- `NaN` -- and the discard ordering was junk.
  * The JS laid cards down with `splice(indexOf(card), 1)`, but `solvePhase`
    materialises its own card objects, so `indexOf` returned -1 and
    `splice(-1, 1)` quietly deleted the *last* card in hand instead.
  * `build_deck` repeats a card with `[number_card(...)] * COPIES_PER_RANK`, so
    both copies of a rank are the **same object**. The Python seat excluded
    candidates with `c is not card`, which dropped *both* copies, rated every
    duplicate as twice the loss it really was, and refused to throw it -- in a
    RUN phase, exactly the card it should throw. Both sides now exclude by
    position.

The third was a real AI bug in the engine that shipped nowhere near a test
until the two implementations were forced to agree.


## Fillers

Both filler items were inert for a long time — named in the tables, classified,
and read by nothing. At default settings that is roughly sixteen of the fifty
items in the pool doing literally nothing, which is a lot of dead pool for
whoever is playing the seed.

**Mulligan** redeals the opening hand. The restriction is the whole design: it
only works *before your first draw*, and it costs no draw.

A reroll available at any moment is a far stronger item than bad-opening
insurance — it would let a player fish for a layable hand all the way down the
draw budget, and every clear rate in the table above is measured against a
budget that cannot be rewound. Fixing it to the untouched deal keeps it what
filler should be: it cuts the variance of a dead deal without raising the
ceiling, so the access rules built on those measurements still hold.

The engine and the session each enforce the restriction. The session's copy
exists to explain a refusal in words; the engine's is what protects every other
driver — the autoplayer, a fixture replay, a player poking at the console — and
it has its own tests, because the session's guard otherwise shadows it and the
engine's could be deleted with every test still green.

**Score Reduction** takes 25 points off the running total, the same as a Wild
left in your hand — the deck's own largest penalty. It is applied to the
reported total, not to the rounds: the scorecard still shows what each hand
actually cost, and the reduction is its own line. A reduction forgives points,
it does not rewrite the history. The total is floored at zero.

Nothing in logic depends on score, so this stays honest filler — it moves the
number the player is judged on and nothing else.

## The store

**AP Point** is the one item that is not filler and not a power item: it buys a
check outright. `store_slots` adds that many locations, each with a price, and
the pool carries enough points to buy them all.

The design question was whether points should buy *any* unearned check. They
should not. The locations declare real rules — `Phase 7 - Under Par` needs the
unlock and two wilds — and a store that bypassed them would make the declared
logic fiction, with hints, the spoiler playthrough and progression balancing
all reasoning from rules that no longer describe play. Worse, if points came
from playing, the cheapest point would be the one from the easiest phase, and
the optimal line would become replaying phase 11 (94%) forever instead of
climbing toward phase 20 (11%). The store is its own locations instead, which
is the ordinary Archipelago shop pattern and logically exact.

### The gate is not the price

A slot's *price* is what it costs. Its *gate* — the rule the seed is generated
under — is the sum of the cheapest prices up to it, not its own. That is what
makes buying in any order legal: holding enough points to meet slot 6's gate
means you could have bought the six cheapest slots instead, so no purchase
order can strand you.

It also makes the affordability check unreachable by construction while the
prices ascend, since any set of slots whose gates you have met costs at most
the largest of those gates. The check stays anyway — it is what would catch a
future ladder that stopped ascending — and both ports test the invariant
exhaustively, over every point count against all 720 purchase orders.

### Sizing it, measured

A store of S slots brings S locations with it, so it only costs the pool once
there are more points than slots:

    filler' = filler + slots - points

Six slots paid for with ten points costs **two** filler items, not ten. The
binding constraint is `checks_per_phase`, not the store size: at one check a
phase there are two filler items in the whole seed, and the store trims itself
to what fits — slack first, then slots, landing on five slots there. Generated
across every combination of `checks_per_phase` 1–4 and 0/4/6/8 slots: all fill,
all beatable, every location reachable.

The trap found while prototyping: the points have to be reserved *before* the
power items are sized. Otherwise the store's own new locations are swallowed by
power items that were previously being trimmed away, and the points have
nowhere to go — the store silently pays for Wild Cards.

### It runs alongside the phases

Measured over fifteen seeds at the default, six slots and ten points:

| | |
|---|---|
| mean seed depth | 11.5 spheres |
| first slot opens at | sphere 2.1 |
| last slot opens at | sphere 8.5 |

So it opens early and finishes before the endgame, rather than being six checks
that all come due at once.

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

`client/game_manager.py` adds a game tab to the client window, alongside the
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

## Browser version

`docs/` is the web root, laid out for GitHub Pages ("Deploy from a branch:
main, /docs"). Open `docs/index.html` over HTTP and it is the whole game: the
rules run in the browser, `archipelago.js` talks to the server.

    docs/index.html          the page
    docs/style.css
    docs/src/ui.js           DOM layer, holds no game state of its own
    docs/src/client.js       Archipelago wiring, no DOM
    docs/src/session.js      items to config, hand to location IDs
    docs/src/{cards,phases,engine,game}.js   the rules, ported from Python
    docs/assets/cards/       the same 51 faces the Kivy client uses
    docs/node_modules/       archipelago.js, vendored

`archipelago.js` is vendored rather than pulled from a CDN, the way ap-rummy
does it: Pages serves it with no build step and the game gains no runtime
dependency on anyone else's uptime. It has no dependencies of its own, so the
vendored tree is one package.

The card faces exist twice, under `phase10/` and under `docs/`, because the
apworld ships as a zip of `phase10/` and Pages cannot reach above `docs/`. One
run of `tools/generate_cards.py` writes both rather than leaving the second to
be remembered.

### Verified against a live server

Served `docs/`, drove the page in a real browser, clicked through a hand with
the actual buttons: phase cleared, **four checks acknowledged, missing 50 to
46**, and the item that check awarded came back and appeared in the log.
Reloading and reconnecting restored the scorecard.

Then the Python client was pointed at the same slot and **read the scorecard
the browser had written** -- same Data Storage key, same payload -- so a game
started in one continues in the other.

### One bug that only a browser could have found

`login(url, slot, game, { password: password || undefined })` hangs for the
full ten-second timeout and reports the server as unresponsive. archipelago.js
spreads those options over its defaults, so an explicit `undefined` overwrites
the default empty string. `|| undefined` is precisely the idiom to reach for
there and precisely the wrong one; omit the key instead. Node never saw it,
because the node check passed no options at all.

### Serving it on Pages

Two settings, both easy to get wrong:

**The source path must be `/docs`, not `/`.** Settings, Pages, Deploy from a
branch, `main`, `/docs`. Pointed at the root it serves a repo with no
`index.html` and every URL 404s.

**`docs/.nojekyll` must exist.** Pages runs Jekyll by default, and Jekyll's
default excludes contain `node_modules` -- so the vendored `archipelago.js`
would simply not be published and the client would fail to import it. The empty
`.nojekyll` file turns Jekyll off and serves the directory verbatim.

There is no autoplay in the browser. `/auto` and `/grind` exist only in the
Kivy client, because porting the autoplayer without a differential test would
be exactly the drift the rest of this is careful to avoid.

## Multiworld

    python tools/check_multiworld.py

Every seed this project generated for a long time held one slot of one game,
which is the single arrangement that cannot exercise what is most likely to
break: fill putting this world's items into someone else's locations, and
someone else's into this world's.

`tests/yaml/multi/` is four slots -- APQuest, ChecksFinder, and **two
AP_10 slots with deliberately different options**. Same game twice is
where item IDs, option-dependent location counts and progression balancing
collide, and one of the two runs the tightest legal option set (two checks per
phase, one starting phase, minimum items, `accessibility: minimal`), because
that slot has the least room for fill to work in.

The check asserts the seed really is mixed and that items crossed in both
directions, not merely that generation exited zero. Generation succeeding is
itself the beatability proof -- Archipelago validates completion and builds a
playthrough before writing anything.

Current result: 4 slots, 210 placements, 64 of this world's items placed
elsewhere, 79 foreign items placed here, 37 crossing between the two
AP_10 slots.

Pointed at the single-slot set it must fail, and does:

    python tools/check_multiworld.py tests/yaml/solo

## DeathLink

Off by default; `death_link: true` in your YAML turns it on.

A card game has nothing to kill, so a death is **a lost hand**: when someone
else dies your hand in progress fails on the spot, and when a hand of yours
runs out of draws everyone linked loses theirs. Between rounds you have nothing
to lose and an incoming death passes harmlessly -- inventing a penalty a player
cannot see coming would be worse than letting one through.

Settling a hand that was killed by a death never sends one back, or two linked
players would bounce deaths at each other forever.

The semantics live in the session (`kill_hand` / `killHand`), not in either
client, so the desktop and browser versions cannot disagree about what a death
does. Verified live in both directions and across both clients: a third client
sent a death and the browser lost its hand; the browser then lost a hand of its
own and the Python client, holding one open, lost that.

## A word on the version floor

`minimum_ap_version` is `0.6.7`, and getting that wrong is easy in a way worth
recording.

Development here happens against a **source checkout of `main`**, which reports
`__version__ = "0.6.8"` -- an unreleased, in-development number. Archipelago's
latest *stable* release is 0.6.7. Declaring a floor of 0.6.8 therefore made the
world uninstallable by everyone: the loader refuses it outright with

    Did not load phase10.apworld as its minimum core version 0.6.8 is higher
    than current core version 0.6.7

and since nothing loads, no options template is generated either -- which is
how the problem actually shows up, several steps from its cause.

Nothing in this world needs 0.6.8. Verified by generating with the 0.6.7
release build's own `ArchipelagoGenerate.exe`, and by running its Launcher's
"Generate Template Options", which now produces `AP_10.yaml` with all ten
options.

The lesson for next time: the floor is a claim about the oldest release that
works, not about whatever your checkout happens to say.

## Packaging

    python tools/build_apworld.py                          # dist/phase10.apworld
    python tools/build_apworld.py --verify dist/phase10.apworld

Drop the result in Archipelago's `custom_worlds/`. It ships the world, the
docs and the 51 card faces, and omits `__pycache__` and the test tree, which
is what the two reference apworlds on this machine do. Timestamps are fixed so
two builds of the same source are byte-identical -- otherwise every build looks
like a change and you cannot tell whether a shipped file differs from yours.

`--verify` is not a formality. It checks the required modules are present, that
nothing bytecode-shaped leaked in, that the card art is there, and that the
manifest's `game` matches the docs filename -- a mismatch there 404s the
WebHost page and nothing else notices.

### Two things packaging broke that source never would

Both were found by installing the package with the dev junction removed, not
by reading it.

**The manifest was incomplete.** Archipelago's container loader reads
`compatible_version`, and without it raises `KeyError` -- which surfaces as
"This might be the incorrect world version for this file", pointing nowhere
near the cause, plus "will stop working with Archipelago 0.7.0". The build now
injects `compatible_version` and `version`; the committed manifest stays a
description of the world, the way `worlds/apquest/archipelago.json` is, since
those fields describe the container and Archipelago generates them itself.

**The card art silently vanished.** `Path(__file__).parent / "assets"` points
*inside* the zip for an installed world, so every `is_file()` was False, every
face fell back to a text chip, and nothing was logged -- the client just
quietly looked like it did before the art existed. Faces are now read through
`importlib.resources`, which reads a folder and a zip the same way, and the
widget builds its texture from bytes rather than a `source` path.

Verified from the installed package with no source junction: the world
registers, a seed generates, and all 51 faces read back as real PNG bytes.

## Not built yet

Nobody has actually played a full seed by hand — every difficulty number in
this file comes from the greedy autoplayer. There is no browser autoplay, no
hint display in the browser client, and `/grind` blocks the check-draining loop
while it runs.

## Naming

The world is registered as `AP_10`, defined once in `data.py` as
`GAME_NAME` and read from there by the world, items, locations, client,
launcher and UI tab. `archipelago.json` and the docs filename carry their own
copies because they are not Python — a generation run is what catches those
drifting.

Game rules are not copyrightable, so the engine is original work, and the card
art is generated rather than borrowed. The **name** was the one part still
shared with Mattel's product, and `AP_Phase10` prefixed the mark rather than
replacing it, which creates no distance at all.

`AP_10` drops the word "Phase", which is the half that carried the mark. It is
a placeholder rather than a decision: it is short and it no longer reproduces
the product name, but it also says nothing about what the game is, and a bare
"10" next to a rummy game is still suggestive. The candidates worth a proper
look are the ones from the folk game this is a version of -- contract rummy,
and the family it belongs to -- since naming it after what it actually is
resolves the question rather than dodging it.

Renaming is cheap while nobody is mid-seed and expensive afterwards, because
the game name is what a client sends on connect.
