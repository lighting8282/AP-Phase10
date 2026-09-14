// Names and IDs shared by the world and the clients.
//
// Mirrors phase10/data.py exactly. These tables decide which location a check
// lands on, so a divergence here would report the wrong check and nothing
// would notice until a seed was half played -- data_test.mjs diffs this file
// against the Python one rather than trusting that they were kept in step.

export const GAME_NAME = "AP_Phase10";

export const phaseUnlock = (phase) => `Phase ${phase} Unlocked`;
export const phaseClearEvent = (phase) => `Phase ${phase} Clear`;

export const WILD_CARD = "Wild Card";
export const EXTRA_DRAW = "Extra Draw";
export const HAND_SIZE_UPGRADE = "Hand Size Upgrade";
export const SKIP_CARD = "Skip Card";

export const PHASE_LOCK = "Phase Lock";
export const LEAN_DEAL = "Lean Deal";
export const WILD_THEFT = "Wild Theft";

export const TRAPS = [PHASE_LOCK, LEAN_DEAL, WILD_THEFT];
export const FILLERS = ["Mulligan", "Score Reduction"];

export const ITEM_NAME_TO_ID = (() => {
  const table = {};
  for (let p = 1; p <= 10; p += 1) table[phaseUnlock(p)] = p;
  table[WILD_CARD] = 20;
  table[EXTRA_DRAW] = 21;
  table[HAND_SIZE_UPGRADE] = 22;
  table[SKIP_CARD] = 23;
  table[PHASE_LOCK] = 30;
  table[LEAN_DEAL] = 31;
  table[WILD_THEFT] = 32;
  table["Mulligan"] = 40;
  table["Score Reduction"] = 41;
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
  for (let phase = 1; phase <= 10; phase += 1) {
    TIERS.forEach((tier, index) => {
      table[phaseLocationName(phase, tier)] = 100 + phase * 10 + index;
    });
  }
  // Phase checks occupy 110..203, so milestones start well clear of Phase 10
  // rather than colliding with it at 200.
  HANDS_WON_MILESTONES.forEach((n, index) => {
    table[milestoneLocationName(n)] = 300 + index;
  });
  return Object.freeze(table);
})();

/** Baseline deal, before any Archipelago item is applied. */
export const BASE_HAND_SIZE = 10;

/** Skips are granted into hand, never shuffled in, so this caps the item count. */
export const MAX_SKIPS = 4;
