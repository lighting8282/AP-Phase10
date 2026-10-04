// Names and IDs shared by the world and the clients.
//
// Mirrors phase10/data.py exactly. These tables decide which location a check
// lands on, so a divergence here would report the wrong check and nothing
// would notice until a seed was half played -- data_test.mjs diffs this file
// against the Python one rather than trusting that they were kept in step.

export const GAME_NAME = "AP_10";

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

/**
 * Spent in the store, which is the one place a check can be bought rather
 * than played for. Progression, not filler: it opens locations.
 */
export const AP_POINT = "AP Point";

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
  table[AP_POINT] = 72;
  return Object.freeze(table);
})();

/** Check tiers in unlock order; checksPerPhase takes a prefix of this list. */
/**
 * Ordered most earnable to least, because checksPerPhase takes a prefix:
 * lowering it has to drop the hardest tiers, not the easiest. Went Out is
 * last because solo it is 0% on eight of the twenty phases. See data.py for
 * the measurements.
 */
export const TIERS = Object.freeze(["Cleared", "Under Par", "No Wilds", "Went Out"]);

/**
 * Cumulative "just keep playing" checks. They gate on nothing, which is what
 * gives a seed a workable opening.
 */
export const HANDS_WON_MILESTONES = Object.freeze([1, 2, 3, 5, 8, 12, 16, 20, 25, 30]);

/**
 * What each store slot costs, cheapest first. Ascending on purpose: the gate
 * on slot i is the sum of the i cheapest prices, so whichever order the
 * player buys in, the logic the seed was generated under still holds.
 */
export const STORE_PRICES = Object.freeze([1, 1, 1, 1, 2, 2, 3, 3]);

/** The most slots `store_slots` will offer, and so the ladder's length. */
export const MAX_STORE_SLOTS = STORE_PRICES.length;

/** Points beyond the ladder's total. See data.py for why it is two. */
export const STORE_SLACK = 2;

/**
 * How the store's slots open, from `store_gating`. Sent as the word, and a
 * seed from before the option sends nothing and is a ladder -- which is what it
 * was generated as. See data.py for the invariant both shapes keep.
 */
export const STORE_LADDER = "ladder";
export const STORE_ALWAYS_OPEN = "always_open";
/** 1.5.0 only, kept so its seeds still play. See data.py. */
export const STORE_ALL_AT_ONCE = "all_at_once";
export const STORE_GATINGS = Object.freeze([STORE_LADDER, STORE_ALWAYS_OPEN, STORE_ALL_AT_ONCE]);

/** What an always-open slot costs, by the classification of the item in it. */
export const PRICE_TRAP_OR_FILLER = 1;
export const PRICE_USEFUL = 2;
export const PRICE_PROGRESSION = 3;

const sum = (prices) => prices.reduce((total, price) => total + price, 0);

/**
 * What the slots cost as far as generation can know. Always open, the worst
 * case: the real prices arrive in slot data, decided after fill.
 */
export const storePrices = (slots, gating = STORE_LADDER) => {
  if (gating === STORE_ALWAYS_OPEN) return Array(slots).fill(PRICE_PROGRESSION);
  if (gating === STORE_ALL_AT_ONCE) return Array(slots).fill(1);
  return STORE_PRICES.slice(0, slots);
};

/**
 * Points received before the *logic* counts a slot reachable -- the access
 * rule, not when a client sells it. On the ladder, the cheapest `slot` prices;
 * all at once, the whole store; always open, enough for any one slot. See
 * data.py for why always open is the exception.
 */
export const storeGate = (slot, slots = MAX_STORE_SLOTS, gating = STORE_LADDER) => {
  if (gating === STORE_ALWAYS_OPEN) return PRICE_PROGRESSION;
  if (gating === STORE_ALL_AT_ONCE) return sum(storePrices(slots, gating));
  return sum(STORE_PRICES.slice(0, slot));
};

/**
 * What the store sells that is not a check: a card, once, now. See data.py for
 * the pricing -- a Wild is the most useful card in the deck and the worst one
 * to be caught holding, and a Skip buys a turn off whoever is closest to out.
 */
export const BUFF_WILD = "One-Use Wild";
export const BUFF_SKIP = "One-Use Skip";
export const BUFF_PRICES = Object.freeze({ [BUFF_WILD]: 2, [BUFF_SKIP]: 1 });
export const BUFFS = Object.freeze([BUFF_WILD, BUFF_SKIP]);

export const buffPrice = (buff) => BUFF_PRICES[buff];

/** DeathLink by round score: every this many points sends one death. See data.py. */
export const MIN_SCORE_THRESHOLD = 100;
export const MAX_SCORE_THRESHOLD = 1000;
export const DEFAULT_SCORE_THRESHOLD = 500;

export const phaseLocationName = (phase, tier) => `Phase ${phase} - ${tier}`;
export const milestoneLocationName = (hands) => `Hands Won: ${hands}`;
export const storeLocationName = (slot) => `Store Slot ${slot}`;

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
  // The store gets its own block rather than extending the milestones', so
  // growing either list cannot reach the other.
  for (let slot = 1; slot <= MAX_STORE_SLOTS; slot += 1) {
    table[storeLocationName(slot)] = 500 + slot;
  }
  return Object.freeze(table);
})();

/** Baseline deal, before any Archipelago item is applied. */
export const BASE_HAND_SIZE = 10;

/** Skips are granted into hand, never shuffled in, so this caps the item count. */
export const MAX_SKIPS = 4;
