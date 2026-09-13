# phase10_ap

Headless Phase 10 engine for Archipelago. No UI, no AP imports yet — the engine
is pure so rules can be tested and tuned before any client exists.

Scaffolded to match `Archipelago/worlds/apquest/`, which is the reference for a
game that ships *inside* an apworld (Python game + CommonClient in one process,
no mod loader, no IPC).

## Layout

    phase10/cards.py             card model, deck construction, scoring
    phase10/phases.py            phase specs + the solver
    phase10/engine.py            solo hand: deal, draw, discard, lay down
    phase10/autoplay.py          greedy autoplayer (for difficulty measurement)
    phase10/play_in_console.py   headless runner and difficulty sweeps
    tests/test_phases.py         18 tests, no dependencies

## Run

    python tests/test_phases.py
    python -m phase10.play_in_console --phase 6
    python -m phase10.play_in_console --sweep --trials 200 --max-draws 8
    python -m phase10.play_in_console --draws --trials 200

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

Baseline `max_draws` 8, stock wilds:

- phases 1, 2, 4 — no requirement
- phases 3, 5, 6, 8 — 1 Extra Draw *or* 2 Wild Cards
- phases 7, 9, 10 — 2 Extra Draws *or* 4 Wild Cards

## Open design questions

- **Skips have no solo meaning.** With no opponent to skip, a Skip is 15 points
  of dead weight, which makes "Skip Card" a trap rather than a reward. Either
  cut it as an item or give Skips a solo use (e.g. play one to burn stock and
  dig). Currently they are dead weight, faithful to the card.
- **All-wild groups.** Official rules forbid completing a phase entirely with
  wilds, but printings vary. Exposed as `min_naturals_per_group`, default 1.
- **COLOR groups only solve as a phase's sole group** (fine for the stock ten).
  Mixing COLOR with SET/RUN raises `NotImplementedError` rather than silently
  answering wrong — needs joint rank+color search if Masters phases get added.

## Not built yet

AP world (items/locations/rules/regions/options), client, UI, going-out bonus
checks, multi-hand game loop with scoring.
