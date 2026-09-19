// Names and IDs shared by the world and the clients.
//
// Mirrors phase10/data.py exactly. These tables decide which location a check
// lands on, so a divergence here would report the wrong check and nothing
// would notice until a seed was half played -- data_test.mjs diffs this file
// against the Python one rather than trusting that they were kept in step.

export const GAME_NAME = "AP_Phase10";

/** How many phases the world ships. Mirrors PHASE_COUNT in data.py. */
export const PHASE_COUNT = 20;

/** The lowest non-unlock item ID. Phase unlocks must stay clear of it. */
export const FIRST_FIXED_ITEM_ID = 50;

export const phaseUnlock = (phase) => `Phase ${phase} Unlocked`;
export const phaseClearEvent = (phase) => `Phase ${phase} Clear`;

export const WILD_CARD = "Wild Card";
export const EXTRA_DRAW = "Extra Draw";
export const HAND_SIZE_UPGRADE = "Hand Size Upgrade";
export const SKIP_CARD = "Skip Card";

export const PHASE_LOCK = "Phase Lock";
export const LEAN_DEAL = "Lean Deal";
export const WILD_THEFT = "Wild Theft";

export const MULLIGAN = "Mulligan";
export const SCORE_REDUCTION = "Score Reduction";

export const TRAPS = [PHASE_LOCK, LEAN_DEAL, WILD_THEFT];
export const FILLERS = [MULLIGAN, SCORE_REDUCTION];

/**
 * Points a single Score Reduction takes off the running total. Twenty-five is
 * the deck's own largest penalty -- what a Wild left in hand costs you -- so
 * one of these is worth exactly the worst card you can be caught holding.
 */
export const SCORE_REDUCTION_VALUE = 25;

export const ITEM_NAME_TO_ID = (() => {
  const table = {};
  for (let p = 1; p <= PHASE_COUNT; p += 1) table[phaseUnlock(p)] = p;
  // Phase unlocks own 1..PHASE_COUNT, so everything else starts above any
  // phase count this world will plausibly reach. At twenty phases, "Phase 20
  // Unlocked" and "Wild Card" both wanted ID 20.
  table[WILD_CARD] = 50;
  table[EXTRA_DRAW] = 51;
  table[HAND_SIZE_UPGRADE] = 52;
  table[SKIP_CARD] = 53;
  table[PHASE_LOCK] = 60;
  table[LEAN_DEAL] = 61;
  table[WILD_THEFT] = 62;
  table[MULLIGAN] = 70;
  table[SCORE_REDUCTION] = 71;
  return Object.freeze(table);
})();

/** Check tiers in unlock order; checksPerPhase takes a prefix of this list. */
export const TIERS = Object.freeze(["Cleared", "Went Out", "No Wilds", "Under Par"]);

/**
 * Cumulative "just keep playing" checks. They gate on nothing, which is what
 * gives a seed a workable opening.
 */
export const HANDS_WON_MILESTONES = Object.freeze([1, 2, 3, 5, 8, 12, 16, 20, 25, 30]);

export const phaseLocationName = (phase, tier) => `Phase ${phase} - ${tier}`;
export const milestoneLocationName = (hands) => `Hands Won: ${hands}`;

export const LOCATION_NAME_TO_ID = (() => {
  const table = {};
  for (let phase = 1; phase <= PHASE_COUNT; phase += 1) {
    TIERS.forEach((tier, index) => {
      table[phaseLocationName(phase, tier)] = 100 + phase * 10 + index;
    });
  }
  // Phase checks reach 100 + PHASE_COUNT * 10 + 3, which at twenty phases is
  // 303 -- head on into milestones that used to start at 300. Moved to 400,
  // which clears any phase count up to 29.
  HANDS_WON_MILESTONES.forEach((n, index) => {
    table[milestoneLocationName(n)] = 400 + index;
  });
  return Object.freeze(table);
})();

/** Baseline deal, before any Archipelago item is applied. */
export const BASE_HAND_SIZE = 10;

/** Skips are granted into hand, never shuffled in, so this caps the item count. */
export const MAX_SKIPS = 4;
