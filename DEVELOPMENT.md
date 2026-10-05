# AP_10 development notes

How this was built, what was measured, and the decisions that came out of it.
Nothing here is needed to play the game or install it -- [README.md](README.md)
has that.

It is kept because most of it is the reasoning behind a number that would
otherwise look arbitrary, and because several sections are bugs that took a
while to find and would be easy to reintroduce.

## Contents

<!-- toc -->

- [Run](#run)
- [Apworld](#apworld)
  - [Two fill failures worth remembering](#two-fill-failures-worth-remembering)
  - [Hands Won without replays](#hands-won-without-replays)
- [Solo model](#solo-model)
- [Measured difficulty](#measured-difficulty)
  - [Findings](#findings)
  - [Logic requirements implied by the data](#logic-requirements-implied-by-the-data)
- [Open design questions](#open-design-questions)
- [Client](#client)
  - [The log](#the-log)
  - [Verified against a live server](#verified-against-a-live-server)
- [Environment](#environment)
- [Skips](#skips)
- [Twenty phases](#twenty-phases)
  - [A ceiling you cannot design past](#a-ceiling-you-cannot-design-past)
  - [Anchored groups](#anchored-groups)
  - [Two ID collisions, one caught and one nearly missed](#two-id-collisions-one-caught-and-one-nearly-missed)
  - [The pool could not absorb the locations](#the-pool-could-not-absorb-the-locations)
- [Opponents](#opponents)
  - [The two clocks, and a conclusion that was an artifact](#the-two-clocks-and-a-conclusion-that-was-an-artifact)
  - [A latent bug the trim uncovered](#a-latent-bug-the-trim-uncovered)
  - [Hitting](#hitting)
  - [What the tiers are worth now](#what-the-tiers-are-worth-now)
  - [The tier order is a tuning decision](#the-tier-order-is-a-tuning-decision)
  - [Still not built](#still-not-built)
  - [Keeping the two ports honest](#keeping-the-two-ports-honest)
- [Fillers](#fillers)
- [The store](#the-store)
  - [The gate is not the price](#the-gate-is-not-the-price)
  - [Always open](#always-open)
  - [Sizing it, measured](#sizing-it-measured)
  - [The slots say what they hold](#the-slots-say-what-they-hold)
  - [The rebuyable half](#the-rebuyable-half)
  - [It runs alongside the phases](#it-runs-alongside-the-phases)
- [The build was not reproducible across platforms](#the-build-was-not-reproducible-across-platforms)
- [Six starting draws, not four](#six-starting-draws-not-four)
- [The option help is for choosing, not for showing work](#the-option-help-is-for-choosing-not-for-showing-work)
  - [The template that was not this build's](#the-template-that-was-not-this-builds)
- [The Skip, in a seed](#the-skip-in-a-seed)
  - [A played Skip could be picked up again](#a-played-skip-could-be-picked-up-again)
- [The goal, and two ways it was wrong](#the-goal-and-two-ways-it-was-wrong)
- [Game and scoring](#game-and-scoring)
- [UI](#ui)
  - [Sorting the hand](#sorting-the-hand)
  - [Checking it](#checking-it)
- [Persistence](#persistence)
- [Browser version](#browser-version)
  - [Watching the table play](#watching-the-table-play)
  - [Free play, with no server](#free-play-with-no-server)
  - [Verified against a live server](#verified-against-a-live-server-1)
  - [One bug that only a browser could have found](#one-bug-that-only-a-browser-could-have-found)
  - [Serving it on Pages](#serving-it-on-pages)
- [Multiworld](#multiworld)
- [DeathLink](#deathlink)
  - [Score traps, going-out points, and the other players' scores](#score-traps-going-out-points-and-the-other-players-scores)
  - [The seats play your phase](#the-seats-play-your-phase)
- [A word on the version floor](#a-word-on-the-version-floor)
- [Packaging](#packaging)
  - [Two things packaging broke that source never would](#two-things-packaging-broke-that-source-never-would)
- [Not built yet](#not-built-yet)
- [Naming](#naming)

<!-- /toc -->

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

### Hands Won without replays

The fix for the first failure had a cost that took a real run to see. Logic
treated every Hands Won milestone as reachable from the start, which is true
only because any won round can be played again. So fill was free to put the
next phase unlock on `Hands Won: 12` with nine phases open and every one of
them already cleared, and the only way on was to win the same rounds again.

`hands_won_logic: new_phases`, the default, asks of `Hands Won: N` what forward
play actually guarantees. A won round *is* a cleared round
(`Phase10Game.rounds_won` counts `r.cleared`), so clearing N different phases
is N wins with nothing replayed: the rule is N of the `Phase k Clear` events.
25 and 30 are past what twenty phases can give, so they hold nothing required.
The client is unchanged -- a replayed win still counts, so grinding gets a
milestone early; it just never has to.

Taking ten free checks out of sphere zero made fill fragile, and each fix was
measured over solo seeds, which are the tightest a seed gets:

| Change | Why |
|---|---|
| Only the store's cost is progression, for the ladder too | The ladder's slack and spending points were progression for no rule's sake |
| Two easy phase unlocks placed early (`local_early_items`) | The opening is two checks per starting phase and each easy phase adds two: a chain. 1 of 300 default seeds failed without; three early made the big store worse |
| `starting_phases` below 2 is raised to 2 | One starting phase opens with two checks: 8 of 300 failed |
| A ladder store above 6 slots is cut to 6 | Its last slots end an 11- then 14-point chain: 4 of 1,000 failed at 8, 1 of 800 at 7, none of 3,000 at 6. `always_open` asks 3 a slot and keeps 8 |
| `checks_per_phase: 1` falls back to `replays` | All but three locations already hold a required item there; it failed every seed |

Each adjustment logs a warning naming the option it changed. With them, 0 of
6,800 seeds failed across seventeen option sets, both store shapes and up to
eight slots. `phase10/test/test_hands_won_logic.py` pins the rule and each
adjustment.

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

**That is a claim about an item, and it spent a while deciding how the game
deals.** `skipsInDeck` defaults to zero and the session never overrode it, so
free play — which grants no items at all — ran on a deck with no Skips in it
and handed the player two a round that nobody else at the table could get. The
measurement above says a shuffled Skip is a poor *item*; it says nothing about
how the printed game deals, and the two were conflated. Free play now sends
`skips_in_deck: 4` and no grant, so the opening hand is ten random cards off
the box's deck. A seed is unchanged, because its numbers are the ones above.

Success rate at 8 draws with stock wilds:

| phase | none | 1 Skip | 2 Skips | 4 Skips |
|---|---|---|---|---|
| 6 — run of 9 | 59% | 71% | 83% | 96% |
| 7 — 2 sets of 4 | 31% | 43% | 61% | 87% |
| 10 — set of 5 + set of 3 | 33% | 45% | 64% | 87% |

Skip Card is classified `useful`, not `progression`, so no access rule depends
on it and the fill balance is unchanged.

**Clicking one plays it.** Every other card in the hand is a discard, so a Skip
clicked in the browser client used to go on the pile: fifteen points thrown away
and the Skip with it, off a click that looked like every other click. Playing a
Skip and discarding one are never both legal -- playing it is a whole turn and so
only happens before you draw, a discard only after -- so the first click is
unambiguous, and a Skip clicked after the draw asks for a second click before it
goes. The hand says which is which before the click rather than in the log
afterwards: green outline for a Skip you could play, dashed red for one waiting
on its second click.

None of that wording says "dig", because what a Skip does depends on the seed --
a seed digs, free play denies a turn. `skipAction()` in `ui.js` is the one place
the words are chosen, the same way the button already chose its own label. The
button is also disabled unless playing a Skip would actually work, which differs
the same way: a denial needs somebody still to deny, a dig needs a stock to dig
into. Enabled regardless, its whole function was to explain afterwards that it
could not be pressed.

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

### The two clocks, and a conclusion that was an artifact

The guess was that the draw budget would bind early and the opponents would
take over once Extra Draw items piled up. The measurement said the opposite --
that the race resolved near turn five, long before a large budget could matter,
so the two clocks never layered.

**That conclusion was an artifact of a bug in the seats, and it is withdrawn.**

A seat that had laid down used to skip its draw and discard anyway, so its hand
fell by one every turn for nothing. No other player can take that turn: your
draw and your discard cancel out, and hitting is the only thing that shortens
your hand. The seats were going out roughly twice as fast as the rules allow.
It surfaced from a real game rather than from the suite -- a seat went out
having laid eight of the ten cards it was dealt, and the board could not be
reconciled.

Re-measured with the seats taking the player's turn, 500 rounds a cell, no
draw budget, MID skill, no player at the table (the same shape as before, so
the columns are comparable):

| fastest of N goes out at turn | 1 seat | 2 seats | 3 seats |
|---|---|---|---|
| opponents on phase 1 | 42.0 | 17.8 | **10.3** |
| opponents on phase 7 | 26.5 | 13.6 | **10.8** |

Every cell ended -- 500 of 500, so nothing stalls once the free shed is gone.

Two things changed shape, not just magnitude:

1. **The race now lands near turn ten, not turn five.** A draw budget of eight
   is inside that, so the claim that the budget cannot matter no longer holds.
   Whether 8 to 14 draws now buys anything is an open question, not a settled
   one.
2. **A small phase is now the slow one.** Phase 1 takes longer than phase 7 at
   one seat, which reads backwards until you notice it is the same effect the
   tier order already records: a small phase leaves more cards in hand and
   fewer, smaller groups to hit onto, so going out is harder. The seats now hit
   that wall exactly as the player does.

**What this leaves stale.** `extra_draw_items` defaults to 5 because roughly
eight of twelve Extra Draws were judged dead against the old race, and that
judgement rested on the withdrawn conclusion. The tier percentages in the next
section but one were also measured with three of the old seats. Neither was
re-run here, and neither is trusted until it is. The *gates* are unaffected:
`rules.py` stands on the solo difficulty tables, which were measured with no
opponents at all.

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

> **Measured against the old seats, and not re-run.** These three opponents
> were the ones that skipped their draw once down, so they ended the round
> about twice as early as they now do. Every number here is therefore a floor:
> the player has roughly twice as many turns today, so the real rates are
> higher, and Went Out -- which needs the most turns -- is the one most
> understated. The tier *order* was chosen partly from this column, so it is
> worth re-deriving before anything is tuned on it.

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

In an Archipelago seed a Skip digs rather than denying a turn, which is the one
place the two differ: every measured clear rate the access rules stand on was
measured with the dig. Free play denies, in both directions -- see
[Free play, with no server](#free-play-with-no-server).

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

### Always open

`store_gating: always_open`: every slot sellable from the first point, priced
by what fill put in it — trap or filler 1, useful 2, progression 3. It replaced
1.5.0's `all_at_once` (every slot 1, all opening together at the total), which
was built from a misreading of the request; that YAML word is now an alias for
`always_open`, and the clients still understand an `all_at_once` seed.

**The price is only known after fill, and the logic is written before it.**
That one fact decides the design, and it was measured rather than argued:

| logic rule for each slot | fails to generate, 6 / 8 slots (150 seeds) | random-order buyer stuck |
|---|---|---|
| the store's worst case, 3 a slot (exact) | 2 / **90** | 0 |
| 3 points — any one slot (shipped) | **0 / 0** | **0 of 750** |

The exact rule had to wait for every slot's worst case before counting any slot
reachable, and in a solo seed that packs too much progression in too early.
The shipped rule is the one Archipelago shops use. It does not model spending,
so in principle the logic can count a slot reachable a little before the player
can afford everything it assumes. What makes that safe in practice is the pool:
it carries three points a slot *as progression*, so fill puts every point the
store could cost somewhere reachable, plus the slack and the card budget as
`useful`. `check_store_balance.py --seeds 150` replays the evidence: for every
seed it also plays five buyers who pick affordable slots at random, and fails if
any is stranded. Over the whole grid at 150 seeds, none was — 6,750 playthroughs.

Two things tried and dropped, both measured:

- **Marking every point progression** — the first cut — failed fill on 5–25%
  of seeds. Only the worst case needs to be.
- **Keeping your own AP Points out of the store** (an item rule, the usual
  shop fix) brought failures back: 15 of 150 at the default size. Instead your
  own point is priced at 1, so a slot holding it is change rather than a loss
  of two. Without either, a third to a half of slots held one.

At the default six slots and two checks a phase, the store costs 8–18
(averaging 12.4) and the pool carries 27, so about 15 are left for one-use
cards. At `checks_per_phase: 1` there is no room for three points a slot and
the store is dropped; the option says so.

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

### The slots say what they hold

A shop that will not say what is on the shelf is a shop you cannot shop in.
The decision the store offers is *which slot to spend a point on*, and that
decision is the item behind the slot; without it the six differ only by price.
So on connect both clients scout the store's locations and put the item's name
on the slot, with the receiver's name when it is somebody else's and a mark
when it is progression.

`create_as_hint` is **0**. That is a scout, not a hint: no hint points are
spent, nothing is broadcast, and no other player learns anything. It tells this
client what it is being asked to buy and nothing more.

Failing is quiet. A slot whose contents are unknown shows its price and buys
exactly as it did before, which is also what every offline and free-play seed
sees, so the store has to read an empty stock as "not asked yet" rather than as
"nothing there".

### The rebuyable half

The store also sells a card rather than a check: a **One-Use Wild** for two
points, a **One-Use Skip** for one, as often as the points allow. The card goes
into your hand, costs no draw, and is gone the moment it is played or
discarded. It is for the run where you are three rounds into phase 17 and the
deck will not give you a fourth nine — which is a real place to be, and until
now the only answer to it was to keep losing rounds.

It is one currency, because two would be a second economy to learn for no gain.
That has one hazard, and it is the only thing here that could break a seed
rather than a round: **Archipelago's logic reasons about points *received*, and
cannot model one being spent.** A player who spent the store's own money on
cards would leave locations the seed was generated as reachable with nothing
left to reach them with — in a multiworld, somebody else's progression sitting
in a slot nobody can buy.

**So the store reserves what the unbought slots cost and sells out of the rest.**
`points_reserved` is the sum of the prices of the slots you have not bought;
`buff_points_left` is what is left after it. Buying a card can therefore never
make a slot unaffordable, whatever order you do anything in. The invariant is
tested the way the ladder's own is — every purse a default store can hold,
spent down to the last card the store will sell, then all 720 orders the six
slots can be bought in — in both ports.

Two consequences worth stating. The **slack is spendable**: it existed so the
last slot was not hostage to where the final point landed, and the reservation
now does that job outright, so holding it back as well would make it a point
nobody could ever use. And the refusal **says where the points went** rather
than reporting a flat no, because "8 unspent, but 8 of those are held for the 6
slots you have not bought" is the difference between a rule and a bug.

**How much spending money, measured.** Four was a run's worth of three Wilds,
which is not relief — it is a thing to hoard and agonise over, which is the
opposite of what it is for. Points are items, though, so they come out of the
same location budget as everything else, and at the default two checks a phase
that budget is genuinely tight: 56 locations, 29 of them already claimed by
logic. Modelled through `plan_store` and `build_power_item_counts` at default
options:

| buff points | total points | spare for cards | wilds in deck | skip items | filler |
|---|---|---|---|---|---|
| 0 | 10 | 2 | 8 | 4 | 9 |
| **8** | **18** | **10** | **8** | **3** | **2** |
| 12 | 22 | 14 | 8 | 0 | 2 |
| 16 | 26 | 18 | 5 | 0 | 2 |
| 20 | 27 | 19 | 4 | 0 | 2 |

The curve turns twice. Up to 8 it costs one Skip Card item and some filler. By
12 the Hand Size Upgrades and the rest of the Skip Cards are gone. **Past 12 it
starts eating the Wild Card items themselves** — trading a wild that is in the
deck every round for a wild you get once, which is a bad trade whichever way
you read it. So the default is 8 and the ceiling is 20 for the seeds that can
afford it: at three or four checks a phase there are 76 and 96 locations, and
20 costs nothing but filler.

The prices stay 2 and 1. Making them equal would be the obvious way to buy more
cards for the same points, and it would quietly delete the Skip: a One-Use Wild
fits any phase and is the best card in the deck, so at the same price nobody
would ever buy the other one. Volume is the lever, not price.

`store_buff_points` is how much spending money the seed carries beyond the
ladder. It is trimmed **first** when the pool is tight — before the slack and
before any slot — so a seed that could only just fit its store still gets the
store it would have got without these: at one check a phase the planner still
lands on five slots with nothing spare, exactly where it landed before.

### It runs alongside the phases

Measured over fifteen seeds at the default, six slots and ten points:

| | |
|---|---|
| mean seed depth | 11.5 spheres |
| first slot opens at | sphere 2.1 |
| last slot opens at | sphere 8.5 |

So it opens early and finishes before the endgame, rather than being six checks
that all come due at once.

## The build was not reproducible across platforms

`build_apworld.py` fixes every timestamp in the zip so two builds of the same
source are byte-identical, and says why: *otherwise every build looks like a
change and you cannot tell whether a shipped file differs from the one you
have.* That guarantee held on one machine and quietly failed across two.

Found by verifying a release rather than by reading. The published v1.4.1 was
downloaded and compared against a build of the same commit here: same 77 files,
nothing added or missing, and **24 of them different** — all of them text, all
of them identical once newlines were normalised. Git on Windows with
`core.autocrlf` hands the working tree CRLF, the builder zips the working tree,
and the artifact carries them.

Nothing was ever broken by it. Python reads either ending, and the world runs.
What broke is the only use the guarantee has: rebuilding a shipped artifact and
seeing that it matches.

So the builder normalises newlines to LF on the way in for text suffixes, and
leaves everything else — a card face has no lines — exactly as it is. `--verify`
now refuses an apworld with a CRLF in any text file, which was checked by
building one deliberately and watching it fail.

The alternative, a `.gitattributes` with `eol=lf`, would fix the checkout
rather than the builder. That is worth having too, but it only helps people who
re-clone, and the builder is the thing that must not care.

## Six starting draws, not four

Raised after play-testing found four "way too low". Measured with the
autoplayer against three MID opponents, 300 rounds per phase:

| draws | easy | medium | hard | easy rounds lost to the draw budget |
|---|---|---|---|---|
| 4 | 59% | 20% | 2% | 90% |
| 5 | 65% | 28% | 4% | 86% |
| **6** | **72%** | **39%** | **8%** | **76%** |
| 7 | 73% | 44% | 12% | 63% |
| 8 | 76% | 51% | 14% | 53% |
| 10 | 82% | 56% | 29% | 32% |

That is the start of a run, with no Wild Card items yet. At four draws nine
easy-round losses in ten were the budget, not the table, so a round was a fight
with the draw limit rather than the game. Four to six is the biggest step per
draw: medium phases nearly double. Six rather than eight, because past about
eight the opponents become what ends rounds and Extra Draw items stop buying
anything; at six, three-quarters of losses are still the budget, so those items
still matter.

**The logic was not changed.** Its Extra Draw thresholds are fixed counts set
against four starting draws — medium phases want two, hard ones four, No Wilds
five. At six they ask for more than the game now needs, which is the safe
direction: items gate checks a little later than strictly necessary, never
earlier. Rewriting them as totals (`max(0, total - starting_draws)`) would be
exact, but it moves the Extra Draw floor with the option and needs the pool
sizing reworked to match; not done.

## The option help is for choosing, not for showing work

The YAML template is generated from the option docstrings, so every word in
them lands in front of a player deciding what to roll. They were carrying the
*reasoning* as well as the choice — sphere counts, sample sizes, percentages
off the autoplayer, the history of why a ceiling is where it is — and that is
this document's job rather than theirs. Reported plainly: nobody picking
settings wants the working.

So the docstrings say what the option does, what the values mean, which
direction is harder, and any interaction that would surprise someone. The
measurements stay here, which is where anyone who wants to check them is
already looking. Two that lived only in the option text, kept so they are not
lost with it:

  * **Three opponents end a round around turn five**, and one seat alone takes
    about eight. That is a minimum-of-N effect, so more opponents make rounds
    shorter rather than merely busier.
  * **Skips shuffled into the deck turn up about 0.34 times a hand**, which is
    why Archipelago grants them instead and leaves `skips_in_deck` at zero.


### The template that was not this build's

v1.5.0 went out with an `AP_10.yaml` that said `AP_10: 1.2.0`, carried the long
measured-out help text this section had already removed, and had no
`phases_to_win`, `skip_mode`, `store_buff_points` or `store_gating` at all. The
apworld beside it was 1.5.0.

`export_template.py` asks the Archipelago at `AP_ROOT` to render the template,
and Archipelago renders whichever AP_10 *it* loads — an old `phase10.apworld`
in that install's `custom_worlds/` wins as easily as this repository does.
Reproduced exactly with a 1.2.0 build in a scratch checkout's `custom_worlds/`:
the output matched the released file on every AP_10 line.

The exporter now checks what it got against this build — the `AP_10:` version
against `archipelago.json`, and the option keys against `Phase10Options` read
from source, so the check cannot be fooled by the stale copy it is looking for —
and refuses with the path of the file Archipelago really loaded. `cut_release.py`
treats that as a failure, so the release stops before anything is tagged.

## The Skip, in a seed

`skip_mode` is a YAML option now, and it defaults to `dig` for the same reason
it always did: every measured clear rate the access rules stand on was
measured with the dig. `deny` is the printed rule, available to anyone who
wants it, and the seed records which it used so a client never guesses.

**The deny was measured before it was offered, and it is a large difficulty
increase.** 600 autoplayed rounds per cell through the same policy every other
number here came from, at default options — clear rate against how many Skips
you hold:

| skips held | dig % | deny, dealt to hand | deny, shuffled into deck |
|---|---|---|---|
| 0 | 18.5 | 18.5 | 18.5 |
| 1 | 32.7 | 19.2 | 20.2 |
| 2 | 51.2 | 21.2 | 16.2 |
| 3 | 61.0 | 22.2 | 12.8 |
| 4 | 74.3 | 22.2 | 15.2 |

(Phase 10. Percentage points throughout — not score, which is the other thing
this game calls points.)

**The Skip does not become harmful under the deny. It stops doing much of
anything.** Zero to four Skips is worth +55.8 percentage points of clear rate
under the dig and +3.7 under the deny, where it also plateaus after two. More
Skips still helps, slightly, and never hurts, so `skip_card_items` wants
leaving alone — turning it down only makes a deny seed harder. What changes is
that the strongest item in the pool becomes one of the weakest.

This was stated backwards first, and the correction is worth keeping: the
claim that a `Skip Card` becomes a *drawback* is true only of the **deck**
column, which is not what the option does. Shuffling Skips in rather than
dealing them is genuinely self-defeating — a Skip in the deck is a card you
might spend one of four draws pulling, and then still have to shed — but that
variant was measured and not shipped, and its conclusion got carried across to
the one that was.

The cause is structural rather than a tuning accident. A seed is a race
against the draw budget, not against the table — at four draws the opponents
end a round about once in three hundred — so a denied turn buys you nothing,
while the Skip itself occupies a hand slot and costs fifteen if you are caught
with it. The dig, by contrast, is three cards looked at for no draw, which is
worth a great deal when you only get four. **Deny is the free-play mechanic,
and free play is where it earns its keep**, because there the race is real and
there is no budget.

So: offered, measured, documented, and not the default. Turning it on is a
legitimate way to make a seed harder; it is not a way to make Skips feel like
Skips without paying for it. Were the default ever to move, every tier
percentage in this document would need re-measuring first, because they price
a game in which the Skip helps.

`autoplay.play_out` knows both modes. It had only ever known the dig, and
would have called `play_skip` into an engine that refuses it.

### A played Skip could be picked up again

Reported from a real game: a Skip thrown onto the discard could be taken
straight back off it and played a second time. The box has a rule for this and
the engine did not — `draw(from_discard=True)` took whatever was on top.

It is worse than a missing rule in each mode for a different reason. Denying,
one card can cost a turn every time round the table, for as long as players keep
handing it back and forth. Digging, where a dig costs *no draw*, picking the
Skip back up is an unbounded free choice of three: take it, dig, it lands back
on the pile, and the next player does the same.

Both ports now refuse it, the seats' own policy refuses it before `draw` is
reached, and `check_rules_doc.py` pins the claim in both modes.

**No measured number moves.** The worry was that the clear rates were measured
with the recycling available, since `autoplay` is what measured them. It was
not: across a sweep where a spent Skip sat on the pile at 9,996 draw decisions,
the autoplayer took it **zero** times — adding a Skip can never reduce
`cards_short`, and the policy only takes the top when it strictly does. So the
tier percentages above stand as measured.

What *did* record the bug was `engine_traces.json`. The trace exporter is a
fuzzer: it offered every legal-looking action, including this one, so the
fixtures contained draws the fixed JS port correctly refuses. The fixture was
the wrong side, not the engine. Re-exported, 480 traces, 16,325 actions.

That re-export needed an Archipelago checkout it should never have needed —
the traces are pure engine. `export_engine_traces.py` now falls back to the
`worlds.phase10` mount that `run_world_tests.py` uses, which was verified by
re-exporting the *unchanged* exporter through it and getting the committed
fixture back byte for byte before any rule change was made.

## The goal, and two ways it was wrong

`goal: all_phases` now means *clear phases 1 up to `phases_to_win`*, a range
option defaulting to 20. Ten is the game the box ships; twenty is everything
here; and because it is a range, the YAML's own `random-range-10-20` covers a
random goal length with no new machinery. The world builds its completion rule
from it and slot data carries it, so the clients ask for the same phases the
seed was generated around.

That last clause is the point, because it was not true. **The clients declared
victory at ten phases while the world's rule required all twenty.** `goal_met`
read `len(cleared_phases) == 10`, written when there were ten phases and never
moved when the other ten arrived. The client sends `CLIENT_GOAL` the first
time that turns true, and the server believes the client — so a default seed
finished at half its length. Worse in detail than in summary: `== 10` is false
again at eleven, so the flag fired once and then unset itself.

The second was subtler and would have survived a naive fix. A *count* lets any
ten phases stand in for the first ten, and `HasAll(Phase 1..N Clear)` does not
say that. It is the named phases now, in both ports, with a test that clears
1, 2 and 7 against a goal of three and expects it not to count.

Both are pinned by `TestGoal` in `phase10/test/test_session.py` and the block
of the same name in `docs/test/session_test.mjs`, and the recorded session
fixtures were re-exported: exactly two values moved, both `goalMet`, which is
what a narrow fix should look like.

**A `NameError` came out of the same run.** `Phase10Session.seat_name` used
`OPPONENT_NAMES`, which the Python port never defined — the names lived inside
`build_opponents` as a local, while the JS port had exported them all along.
Any run won by a seat crashed the Kivy client on the spot. `NAMES` is a module
constant now, in both ports.

Neither bug was reachable from the runnable suite, and both were found the
first time `phase10/test/` was executed in a cloud session — see
`tools/run_world_tests.py`, which is what made that possible.

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
- Draw / Take discard / Lay down / Dig / Hit / Sort / Auto / Score
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

### Sorting the hand

Two orders, not one, and the split is not aesthetic: seventeen of the twenty
phases are sets and runs, which are read by rank, and three — 8, 11 and 14 —
are colour groups, where a rank sort scatters the one thing being counted.
Wilds and Skips go last in both, as a block: they belong to no run and no set,
so leaving them in rank position breaks up the sequence the sort exists to make
readable.

Both orders are **total** — ties in the leading key fall through to the other
attribute — so sorting an already-sorted hand cannot rearrange equal cards. A
partial order would have made the hand appear to shuffle itself on a re-sort,
and the browser re-sorts on every render.

It re-sorts on every render on purpose: the order has to stick as cards arrive,
or a drawn card lands on the end and the player presses the button again. That
is safe only because sorting is **not a move** — no draw, no turn ended, legal
at any point, including mid-dig and while the table is playing. Everything the
engine does takes a card rather than an index, so nothing cares where in the
list a card sits. The browser's `Off` is the resting state and stops re-sorting
rather than undoing: the dealt order is not kept, so putting it "back" would be
a shuffle rather than a restore.

**It is proved by the trace fuzzer rather than by a fixture of its own.**
`export_engine_traces.py` offers `sort` alongside every other action, so sorts
land mid-turn, between a draw and a discard, mid-dig and after laying down —
4,841 of them across the 480 traces, split evenly between the two orders. The
trace snapshot records the hand *in order*, so `crosscheck_engine.mjs` compares
the two ports' sorts card for card rather than merely confirming both are
sorted.

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

### Watching the table play

The three seats used to move in the same instant you discarded: the table simply
arrived in a new state, and the log explained all of it afterwards, so which seat
had taken your discard and which had ended the round was something you read
rather than watched. The browser client now shows them one at a time, three
seconds a seat (`OPPONENT_TURN_MS` in `ui.js`), and drains the table's log after
each one so the lines arrive beside the pause they belong to.

Two pieces, neither of them in the rules:

- A hand built with `paced: true` queues the seats in `pendingSeats` instead of
  playing them, and the driver walks them with `stepOpponent()`. Headless drivers
  leave it off and the turn resolves on the spot as before.
- `ui.js` holds the player's controls shut for the length of the walk, marks the
  seat whose turn it is (and your own seat between turns) with a ring on the seat
  itself, and marks the newest line in the log. Only the newest: two highlights
  are no highlight.

**Three seconds a seat is a guess about the player, so it is a setting.** It is
right the first time somebody watches a table play and long by the tenth round,
and the page has no way to tell which of those it is in. The **Speed** button
divides `OPPONENT_TURN_MS` by 1, 2 or 4, or skips the pause entirely; the
choice is kept in `localStorage` under the speed's own name rather than its
position, so adding a speed later cannot silently turn somebody's saved choice
into a different one.

Two details it would be easy to get wrong. The button is not in `#actions` and
so is not disabled with the rest of the controls while the table plays --
speeding the table up during the table's turn is the whole point of it. And the
pause is waited out in tenth-of-a-second slices that re-read the setting rather
than as one timer, so a press shortens the pause already running instead of the
one after it; `Off` ends the current one within a tick. None of this reaches the
engine, and there is nothing to mirror into Python: the paced walk is
presentation for a driver the Kivy client does not have.

The narration is the one main already had. `Table.log` and `say()` were added
with the opponents and are mirrored in the Python port, so the walk reuses them
rather than recording a second account of the same turn -- draining per seat
instead of once per turn is the only difference, and `game_test.mjs` asserts the
paced walk produces byte-identical lines to the unpaced one.

**A card played onto a group is ringed in the colour of whoever played it**, and
the group's caption gains `+1 Ada`. Three things were wrong with the first
attempt at this, and each of them made it useless in a different way:

- **It cleared per seat**, so a mark survived about three seconds -- gone before
  anybody looked at it, which is the same as not marking at all. It now holds
  everything played since the table last started moving, and clears when the
  table next moves rather than on a timer, so there is as long as you like to
  read it. Not on your own move either: a hit and the discard that follows it
  are one turn, and clearing on the discard would erase the mark on the card
  you had just played, in the same breath as playing it.
- **It said nothing about who.** A seat can hit onto anybody's group, so what is
  recorded is who *played* the card, not whose group it landed in -- which is
  the whole question when Ada's card turns up in Cy's set. The seat palette
  moved to `:root` so the ring and the seat border cannot drift apart.
- **Your own hits were not marked.** Hitting is the one move whose result lands
  somewhere other than your own hand, so it is the hardest to see you made.

Two details that are not decoration. The ring is drawn with `outline-offset`,
because the seat colours and the card colours are both green/red/yellow -- flush
against the card, a green ring on a green card disappears, exactly on the card
it exists to point at. And the count is written out beside the group name,
because four similar rings is a lot to ask of colour alone.

**The mark outlives the flash.** Those two are answering different questions and
were doing only the first. The ring says *what just changed*, and it has to
clear or everything is ringed by the end of a round. Whose card a card is does
not change, and it is the thing you want two turns later: a run of nine with
two of your cards and one of Ada's in it is a different thing from a run of
nine Cy built alone, and counting back through the log is not reading the
table. So a card played onto a group that was already down keeps a border in
the player's colour for the rest of the round, under the flash while the flash
lasts.

`playedBy` is a second map beside `justHit`, written at the same two points and
cleared when a round starts rather than when the table moves. It lives in the
UI rather than the engine because it can: `toPayload` keeps finished rounds and
nothing else, so a hand in progress is never restored and a round always begins
with the table empty. Nothing to mirror into Python, and no `SAVE_VERSION` bump.

The border is drawn *inside* the card, at `outline-offset: -1px`. Outside it
would cost no layout either but would reach the card beside it -- groups pack
at a 2px gap -- so a group with three marked cards in it would read as one
smear. Two pixels of card art is a cheap price for a border that is still
unambiguous at the 20px a seat's cards are drawn at on a phone.

**The turn moved into `Table.playSeat`, and that is the part worth remembering.**
It is the body of the old `endOfTurn` loop, so a seat played one at a time is
played exactly as it was played all at once -- including consuming a Skip, which
the loop used to own. Leaving the Skip consumption in the loop is the obvious
refactor and it is wrong: the paced walk never calls the loop, so a denied seat
would have quietly taken its turn. That is invisible on screen and changes who
wins the round. `game_test.mjs` asserts the two walks reach identical state off
one seed, and pins the denied seat on its own.

`play_seat` is mirrored into Python for the same reason -- a turn should live in
the same place in both ports -- though the paced walk itself is not, being
presentation for a driver the Kivy client does not have.

**A group has no width limit, and a seat does.** A run of seven laid down is
twelve cards by the time everybody has hit it, and a set has no ceiling at all.
Reported from a real game: the row ran on past the edge of the seat and drew
underneath the next player's panel, on the desktop and on a phone both. A flex
item does not shrink below its own content unless it is told it may, so the row
was simply wider than the box it was in and nothing clipped it.

Fanning the cards over each other was the first fix and it was measured rather
than admired: at the width a seat actually gets -- about a hundred pixels on a
phone, three of them across -- nine cards leave seven pixels of each. On a run,
where the rank is the entire content, that says a card is there without saying
which one. So the row wraps instead and every card stays whole; the seat grows
downwards, and height is the one thing a phone has and a seat has not. A seat's
cards drop to 20px there for the same reason its backs did: at 26px a group
wraps every third card and reads as a column rather than a group. Your own
groups keep the full size, having the width of the page.

**The middle of the table was most of the table, on a phone.** Measured
mid-round at 412x872: the felt came to 815px of an 872px viewport, so the seats
across from you and your own cards could not be on screen together — and 188px
of that was the middle, for two piles and a line of text. The piles gave up the
most for the least: at 54px a pile is still a 76px button, comfortably over the
44px floor everything else on a touch screen is held to, and a card face reads
perfectly at two thirds. With them that size the prompt fits *beside* them
rather than taking a row of its own, which was the other half of it. The middle
is now 117px — exactly the height of a pile — at every width from 320 to 768,
and on the board this was measured on the whole table fits one screen.

One trap in that, found by measuring rather than by reading. `#prompt` is given
a 4rem basis, and the basis is set for the *wrap* rather than for the width:
flex decides what fits from the basis and only then lets the prompt grow into
whatever the piles leave. At 7rem it fit on every phone tested and then came
apart at 320px, putting the prompt and the stock on one line and the discard
alone on the next — worse than the row it replaced.

All of it sits inside the existing `max-width: 768px`/`pointer: coarse` block,
so the desktop page is untouched, and the Kivy client reads no CSS at all.

**Your own hand went 58px to 48px** for the same reason and with the same
floor. What matters there is not the card but how many fit a row: at 58px it
was five across, so ten cards cost *three* rows on a 360 or 390px phone and two
on a 412px one. At 48px it is six across on anything from 360 up — two rows
everywhere, which is 125px off the common phones and 30px off the widest. Not
smaller than that: these are the cards you tap rather than the ones you read
across the table, 48px still clears the 44px floor, and a mis-tap here
discards.

**The stylesheet is stamped too**, and was not. Half the layout lives in
`style.css`, Pages serves it with the same ten-minute cache as everything else,
and a CSS-only deploy left the old rules in place with nothing in the markup to
say so -- the exact failure `stamp_build.py` exists to prevent, on the one file
it did not cover.

### Free play, with no server

The page opens on a connection form, which is a wall for anyone who has never
heard of Archipelago — and the game underneath it is a perfectly good game of
Phase 10 on its own. **Just play** starts a run with no room, no slot and no
login.

It is the printed game rather than a sandbox: the full eight wilds, the box's
four Skips shuffled into the deck, three Mulligans, three opponents — and **the
phases open one at a time as they are cleared**. The opening hand is ten random
cards off that deck, the same as every seat gets; the Skip *item*, which hands
you one a round, belongs to a seed and stays there. A run is ten phases or twenty, chosen when it starts: ten is
what the box holds, and a ten-phase run shows ten buttons rather than twenty
with half of them permanently dark. The cap is saved with the run, so a reload
does not quietly turn a ten into a twenty, and a saved run from before the
choice existed restores as twenty, which is what it was. Archipelago's out-of-order unlocking is the thing being replaced
here, so handing over all twenty at once would miss the point.

**The run ends when somebody finishes the last phase**, whoever it is, and the
lowest score among those who did takes it. That is the printed game, and it was
missing entirely: free play had no end condition in either direction. A seat
that finished the last phase carried on to a phase that does not exist, and the
run went on forever -- reported from a real game as a seat completing phase 10
while the round counter climbed past sixteen.

Two bugs in one, and the first was hiding the second. `advance_opponents`
capped a seat at `PHASE_COUNT` rather than at the *run's* cap, so a ten-phase
run had seats on phase 16; nothing consumed the signal, so even the correct
value would have done nothing. A seat now stops one past the cap and stays
there. That is not a phase anybody plays -- it is where "finished" is recorded,
the same way your cleared set records that you did -- and it only exists in a
race, because a seed showing "phase 21" would be a marker for an event that
mode does not have.

`run_over` and `run_winner` are derived rather than stored. The seat phases and
the scorecard are both saved already, so a reloaded run knows it is finished
without a save format that could disagree with it -- and no `SAVE_VERSION` bump,
which would have thrown away every run in progress.

`race_to_end` is a slot-data field, false by default. **An Archipelago seed is
never ended by a seat**: it has its own goal, and an opponent finishing is not
an Archipelago notion.

A tie on score goes to you, then round the table. The box would play another
hand; a solitaire run cannot, so somebody has to be named.

**A Skip denies the next player a turn**, which is the printed rule. An
Archipelago seed keeps the dig instead, and the split is deliberate rather than
lazy: every measured clear rate the access rules are built on was measured with
the dig, so changing what a Skip does in a seed would mean re-deriving the
difficulty tables and every gate standing on them. Free play gates nothing on a
difficulty number, so it can have the rule off the box for free.

`skip_mode` is a `GameConfig` knob defaulting to `"dig"`, so a seed cannot
reach the new behaviour by accident. The seat carries a `skipped` flag that
`Table.play_seat` consumes where the turn would have happened, rather than
where the Skip was played -- that way it costs exactly one turn however long it
waits for that seat to come round. `next_actor` passes over a seat already
denied, or a second Skip in the same cycle would cost nothing.

Measured rather than asserted: a denied round takes one seat's worth less off
the stock than an ordinary one.

**The Skip is the discard, and the thrower picks the target.** Both halves of
that are the printed rule and neither was true at first, which cost a real
player a real Skip for nothing.

It was a pre-draw move: `play_skip` spent the Skip, denied whoever `next_actor`
named, and ended the turn without a draw. That reads fine and plays badly. The
move stopped being legal the instant you drew, so a player holding a Skip past
their draw had exactly one thing left to do with it -- throw it away, fifteen
points, no effect -- and the browser client walked them into it: the button went
dark, and the card sat in a row of cards whose every other member was a discard.
Reported from a real game as "a skip doesn't skip anyone, at all", which is
precisely what it looked like.

So discarding a Skip *is* playing it. `discard_card` sees the Skip, holds the
turn open in `pending_deny`, and `deny_seat` names the victim and ends it.
Holding the turn open rather than resolving immediately is what buys the choice,
and the choice is the point: the seat worth denying is the one closest to going
out, which is rarely the one whose turn comes next. Nothing else lands while a
Skip is waiting to be aimed, or a player could draw their way out of answering.

Two cases that have to stay ordinary rather than become refusals. Going out on a
Skip denies nobody -- the round is over and there is no next turn to miss.
With no eligible seat it is a plain discard, because refusing the throw would
strand a player holding a card they cannot legally get rid of.

The pre-draw path is gone in deny mode rather than kept as a second way in: two
routes to one effect, one of which skips the target choice, is the kind of
surface that drifts between the two ports. Dig mode is untouched, so no measured
clear rate moves.

**The seats play them too, and can aim at you.** For a while they could not:
`skipped` was a flag done *to* a seat, the AI had no notion of spending one, and
the player was not a seat at all, so a Skip ran one way and only one way.

Three pieces make it symmetric.

`Table.player` is a back-reference to the hand being played, so the seats can
see you as a target. It is a reference rather than a copy of what they need to
know, because what a good target looks like is the seats' business and copying
it would spell the rule out twice.

`PhaseHand.skipped` is the flag on your side, consumed in `_end_turn` where your
turn would have been -- the same bargain a seat's own Skip makes, costing
exactly one turn however long it waited. Losing it means the table comes round
*twice* before you act, which is what a lost turn is. `turns_missed` counts them,
because the flag is gone the instant the turn is spent and a client that only
looks between moves would never see it.

**Which turn it costs is the next one, and reading the flag too early moves it.**
`_end_turn` checked `skipped` at the top, *before* letting the table play. But a
seat sets that flag while it plays, so the check was always a round behind: you
were handed the turn you had just been denied, played it, and the miss was
charged to the turn after. Reported from a real game as being skipped and
allowed to go again, which is exactly what it was. The table's turn is settled
first now, and then `while skipped` spends the turn that would have come next --
a loop rather than an `if`, because two seats can deny you in one round of the
table and each one costs a turn.

The paced walk has to agree, and it is the same rule arriving in pieces: the
denial lands somewhere inside the queue, so `step_opponent` spends the turn when
the queue empties and refills it. Both orders are pinned by one test that runs
paced and unpaced and compares who acted, in order.

`_deny_somebody` aims at whoever is closest to going out: down first, then
fewest cards held, everybody included. That is usually you, and denying the next
seat round the table instead would be the safe-looking choice and the wrong one.
Everything it reads is face up -- who is down, how many cards they hold -- so it
is not a seat looking at hands it cannot see. A mistake is the second-best
target rather than a random one, the same shape `_choose_discard` already uses,
so `discard_error` tunes it for free.

A seat throws its Skip as soon as it has one. It is the only card in hand that
does something on the way out, it is never part of a phase, and it costs fifteen
to be caught holding.

**The differential test would not have caught any of this.** Every recorded
trace ran with `skips_in_deck: 0`, so no seat ever held a Skip and the whole
policy -- including the coin flip inside it -- was invisible to the crosscheck
while passing it. Eight deny-mode traces with the box's four Skips now carry 17
denials between them.

**There is no draw budget.** The budget is the solo model's replacement for the
race to go out, and free play has the race — three seats at the table — so
keeping both would be a clock the box has never heard of. `max_draws` of zero
means unlimited, which only free play asks for: the `starting_draws` option
starts at 2, so Archipelago cannot reach it and no measured rate moves.

`draws_left` returns `None` rather than a large number, so a caller that
forgets the unlimited case fails loudly instead of quietly comparing against
something arbitrary.

Measured over 1200 autoplayed rounds with no budget: with three opponents a
round ends after a median of 3 draws and at most 15, because the race is a real
clock. With one opponent, 5 and 32. **With none it never ends at all** — which
is why free play seats three and does not offer a choice.

Taking the budget away exposed the other clock: this engine treated an empty
stock as a lost hand, which is a way to lose that is in no version of the
rules. The stock now refills from the discard, top card left face up, the rest
shuffled back. With a budget it is unreachable in practice — four players at
eight draws take 32 of about 60 cards — so it changes nothing about a seed.

The unlocks are recomputed from the scorecard rather than accumulated, so they
are right after a restore without ever having been saved, and replaying a
cleared phase cannot open two.

The run is kept in `localStorage`, so it survives a reload but lives only in
that browser: no server holds it, and clearing site data ends it. Every read
and write is wrapped, because storage can be absent, full, or refuse outright
in a private window, and none of those is a reason to stop playing. Free play
touches no socket at all — the test asserts that by making `login` and `check`
throw.

The store and the check list are hidden in free play. Both would otherwise list
things that can never be taken, and a check list where nothing is checkable is
worse than no list.

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

A card game has nothing to kill, so an incoming death is **a lost hand**: when
someone else dies your hand in progress fails on the spot. Between rounds you
have nothing to lose and an incoming death passes harmlessly -- inventing a
penalty a player cannot see coming would be worse than letting one through.

**Outgoing deaths go by round score**, not by losing. Every `score_threshold`
points (100–1000, default 500) sends one. It used to be every hand that ran out
of draws, which at the old four-draw default was most lost rounds -- a death
every two or three rounds, far harsher than anybody linked had signed up for.
Measured at about 32 points a round (a cleared round leaves ~6, a lost one ~60),
500 is a death every sixteen rounds or so. This also gave the round score a
purpose in a seed, which it had lacked: it was shown and affected nothing, and
the Score Reduction filler was dead weight. Now a reduction pushes the next
death further away.

The rules, the same in both clients (`score_mark_due` / `scoreMarkDue`):

- **A high-water mark, saved.** `score_marks` counts thresholds already
  handled and travels in the save payload, so a reconnect or a switch between
  clients never sends one twice. A reduction lowers the total under the mark,
  so the points have to be earned back before the next death.
- **At most one per round.** A round that jumps two thresholds at a low setting
  sends one, not a burst.
- **Absorbed, not returned.** A hand that an incoming death ended counts its
  points but sends nothing, or two linked players could bounce deaths at each
  other for as long as each loss crossed a line.
- **Old saves catch up.** A save without the count restores it at the current
  total's threshold, so a run already at 1200 points does not send a surprise
  death on its first round after the update.

The browser leaves a threshold owed while disconnected and sends it on the next
settled round; the Python client queues it and sends on reconnect.

The semantics live in the session (`kill_hand` / `killHand`), not in either
client, so the desktop and browser versions cannot disagree about what a death
does. Verified live in both directions and across both clients: a third client
sent a death and the browser lost its hand; the browser then lost a hand of its
own and the Python client, holding one open, lost that.

### Score traps, going-out points, and the other players' scores

Three more uses for the round score, built together.

**Score traps.** `score_traps` makes each `score_threshold` also set off one of
your own traps on your next hand: Lean Deal, then Wild Theft, in turn. It shares
DeathLink's threshold and its saved high-water mark, so one setting drives both
and they stack when both are on. A fired trap simply adds to that trap's count,
so it goes through exactly the code a received Lean Deal does; the count of
fired traps is saved, and which trap each was follows from the count. A hand an
incoming death ended sets off nothing, for the same reason it sends nothing.
Phase Lock is left out of the cycle: it waits for a later *lost* hand, which
would read as unrelated to the score that caused it.

**Going out earns card money.** Each round finished with an empty hand gives
one point to spend on one-use cards — derived from the scorecard, not saved, so
both clients agree by construction. Measured at six draws against three
opponents: going out is 21% of rounds, while "at or under ten points" was 45%,
which would have been nearly free money. Earned points are spent before AP
Points and never count toward a slot, so — tested exhaustively over earned
points, AP Points and purchase order — cards still can never take what an
unbought slot is owed.

**The other AP_10 players.** Each client publishes a small record (score,
rounds won, phases cleared) to its own Data Storage key, `phase10_score_<team>_<slot>`,
beside the private save, and watches everyone else's with `SetNotify`. The
browser shows them under the summary line; the Python client has `/scores`.
Records from other clients are untrusted input and checked field by field.

**Proved against a real server.** `tools/check_live_room.py` generates a
two-player seed, hosts it with `MultiServer.py`, plays both seats with the
browser client and reads the room with the Python client. Its first run caught
a bug no unit test could: the browser client saved *before* marking a threshold
handled, so after a reconnect the next round resent the death and refired the
trap. It also confirmed the two clients read each other's scores.

### The seats play your phase

`opponent_phase: match` (the default for a seed) seats the computer players on
the phase you picked, every round. `own` is the old behaviour: each starts on
Phase 1 and climbs as it clears. Free play is always `own`, because there the
seats climbing is the race; a seed from before the option reads as `own` too.

Why it is the default: in a seed you play phases out of order, so with `own`
the seats' phase drifts away from yours, and their phase moves your odds a lot.
Measured, your clear rate on Phase 1 is 78% with the seats on Phase 1 and 52%
with them on Phase 15 (runs let them shed and go out sooner, ending your
round). With `match`, a round's difficulty is the phase you chose and your
items; overall it lands close to the seats-on-Phase-1 column for most phases.

| you on | they on 1 | on 5 | **same** | on 15 |
|---|---|---|---|---|
| 1 | 78% | 76% | **78%** | 52% |
| 4 | 67% | 62% | **58%** | 47% |
| 10 | 21% | 17% | **20%** | 9% |
| 18 | 61% | 59% | **49%** | 44% |
| 20 | 42% | 38% | **39%** | 19% |

Matching seats do not climb (`advance_opponents` is a no-op), but their round
scores are still tallied.

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

It came back through a side door in v1.8.0. The options template carries a
`requires: version:` line, and Archipelago fills it with *its own* version --
so the template rendered by that same `main` checkout asked for 0.6.8, and a
0.6.7 Generate refused it: "required version of generator is at least 0.6.8,
however generator is of version 0.6.7". `tools/export_template.py` now writes
`minimum_ap_version` into that line, and refuses a template whose line says
anything else.

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
