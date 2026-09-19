/**
 * Headless solo Phase 10 engine.
 *
 * A direct port of phase10/game/engine.py. Pure -- no DOM, no Archipelago, no
 * I/O. A client drives it turn by turn and reads `events` to decide which
 * locations to check.
 *
 * Solo play replaces the multiplayer race-to-go-out with pressure from the
 * draw pile: you get a bounded number of draws to lay your phase down. Skips
 * have no opponent to skip, so they dig instead -- play one to see the top of
 * the stock and keep a card of your choice.
 */

import {
  SKIP,
  WILD,
  buildDeck,
  cardToString,
  handScore,
  isSkip,
  isWild,
  numberCard,
  COLORS,
} from "./cards.js";
import { GROUP, PHASES, phaseCardCount, solvePhase } from "./phases.js";

/** How deep into the stock a played Skip lets you look. */
export const SKIP_DIG_DEPTH = 3;

export const HAND_STATE = {
  IN_PROGRESS: "in_progress",
  PHASE_LAID: "phase_laid",
  WENT_OUT: "went_out",
  FAILED: "failed",
};

/** Everything Archipelago items are allowed to move. */
export function gameConfig(overrides = {}) {
  return {
    handSize: 10,          // "Hand Size +1" items
    wildsInDeck: 8,        // "Wild Card" items
    maxDraws: 20,          // "Extra Draw" items
    startingSkips: 0,      // "Skip Card" items
    // Skips shuffled into the draw pile, for fidelity to the physical deck.
    // Measured as a straight loss -- they turn up 0.34 times per hand, too
    // rarely to repay the density they cost every other draw -- so Archipelago
    // grants Skips via startingSkips instead and leaves this at zero.
    skipsInDeck: 0,
    minNaturalsPerGroup: 1,
    allowDiscardDraw: true,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Randomness
//
// Deliberately NOT an attempt to mirror Python's Mersenne Twister. The engines
// are compared as pure functions over a given deck, so deck order never needs
// to agree -- see docs/test/crosscheck.mjs.
// ---------------------------------------------------------------------------

/** Small deterministic PRNG, so a seed reproduces a session for debugging. */
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function shuffledDeck(random, wilds, skips) {
  const deck = buildDeck(wilds, skips);
  for (let i = deck.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [deck[i], deck[j]] = [deck[j], deck[i]];
  }
  return deck;
}

// ---------------------------------------------------------------------------

function sameCard(a, b) {
  return a.kind === b.kind && a.rank === b.rank && a.color === b.color;
}

/**
 * Remove one card equal to `card`. Python's list.remove() deletes the first
 * VALUE-equal element (Card is a frozen dataclass); JS objects compare by
 * reference, so identity removal would silently miss an equal-but-distinct
 * card and corrupt the hand.
 */
function removeCard(cards, card) {
  const i = cards.findIndex((c) => sameCard(c, card));
  if (i === -1) throw new Error(`${cardToString(card)} is not in hand`);
  cards.splice(i, 1);
  return card;
}

/** One round: a single attempt at a single phase. */
export class PhaseHand {
  /**
   * @param {object} [opts]
   * @param {Function} [opts.random] RNG in [0,1); defaults to Math.random.
   * @param {Array}    [opts.deck]   Pre-built deck, bypassing the shuffle.
   *                                 Used by the differential tests so both
   *                                 engines can be replayed over one deal.
   * @param {Array}    [opts.spec]   Override the phase spec.
   */
  constructor(phase, config, opts = {}) {
    this.phase = phase;
    this.spec = opts.spec ?? PHASES[phase];
    this.config = config;

    // Kept so a Mulligan can shuffle again. A fixed `deck` is honoured for the
    // opening deal only -- a redeal past it has nothing recorded to deal, so
    // the trace exporter does not emit redeals into the differential fixtures.
    this._random = opts.random ?? Math.random;
    this._deal(opts.deck);

    this.drawsUsed = 0;
    this.state = HAND_STATE.IN_PROGRESS;
    this.layout = null;
    this.events = [];
    this.drewThisTurn = false;
    this.usedWildsInLayout = 0;
    this.skipsPlayed = 0;
    this.digOptions = null;
  }

  /**
   * Shuffle and deal. Shared by the opening deal and a Mulligan, so the two
   * cannot drift into dealing subtly different tables.
   */
  _deal(fixedDeck = null) {
    const deck = fixedDeck
      ? fixedDeck.map((c) => ({ ...c }))
      : shuffledDeck(this._random, this.config.wildsInDeck, this.config.skipsInDeck);

    this.hand = deck.slice(0, this.config.handSize);
    // Granted Skips are dealt on top of the hand rather than out of it, so
    // holding them costs no room to build the phase in.
    for (let i = 0; i < this.config.startingSkips; i++) this.hand.push({ ...SKIP });

    const rest = deck.slice(this.config.handSize);
    this.discard = rest.length ? [rest[0]] : [];
    this.stock = rest.slice(1);
  }

  /**
   * Throw the opening hand back and deal a fresh one -- a Mulligan.
   *
   * Deliberately restricted to before the first draw. A reroll available at
   * any point is a far stronger item than a bad-opening insurance policy, and
   * it would invalidate the measured clear rates the access rules are built
   * on. Costs no draw: the point is to undo a dead deal, not to pay for it out
   * of the same budget the deal already ruined.
   */
  redeal() {
    if (this.state !== HAND_STATE.IN_PROGRESS) throw new Error(`hand is ${this.state}`);
    if (this.drawsUsed || this.drewThisTurn) {
      throw new Error("a Mulligan only works before your first draw");
    }
    if (this.digPending) throw new Error("finish the dig first");
    if (this.skipsPlayed) throw new Error("a Mulligan only works before you play a Skip");
    this._deal();
    this._emit("redeal", { hand: this.hand.length });
  }

  // -- queries --------------------------------------------------------------
  get drawsLeft() {
    return Math.max(0, this.config.maxDraws - this.drawsUsed);
  }

  get discardTop() {
    return this.discard.length ? this.discard[this.discard.length - 1] : null;
  }

  get digPending() {
    return this.digOptions !== null;
  }

  get skipsInHand() {
    return this.hand.filter(isSkip).length;
  }

  solution() {
    return solvePhase(this.hand, this.spec, this.config.minNaturalsPerGroup);
  }

  canLayDown() {
    return this.solution() !== null;
  }

  // -- actions --------------------------------------------------------------
  draw(fromDiscard = false) {
    if (this.state !== HAND_STATE.IN_PROGRESS) throw new Error(`hand is ${this.state}`);
    if (this.drewThisTurn) throw new Error("already drew this turn; discard first");

    let card;
    if (fromDiscard) {
      if (!this.config.allowDiscardDraw || !this.discard.length) {
        throw new Error("cannot draw from discard");
      }
      card = this.discard.pop();
    } else {
      if (!this.stock.length) {
        this.markFailed("stock_empty");
        throw new Error("stock is empty");
      }
      card = this.stock.shift();
    }
    this.hand.push(card);
    this.drawsUsed += 1;
    this.drewThisTurn = true;
    return card;
  }

  discardCard(card) {
    if (this.state !== HAND_STATE.IN_PROGRESS) throw new Error(`hand is ${this.state}`);
    if (!this.drewThisTurn) throw new Error("must draw before discarding");
    removeCard(this.hand, card);
    this.discard.push(card);
    this.drewThisTurn = false;
    this._failIfOutOfRoad();
  }

  /**
   * Spend a Skip to look at the top of the stock.
   *
   * The Skip becomes this turn's discard, so no separate discard follows --
   * that is what keeps hand size stable and lets the Skip shed itself. The dig
   * costs no draw. Resolve the reveal with takeDug.
   */
  playSkip() {
    if (this.state !== HAND_STATE.IN_PROGRESS) throw new Error(`hand is ${this.state}`);
    if (this.digOptions !== null) throw new Error("finish the current dig first");
    if (this.drewThisTurn) throw new Error("already drew this turn; discard first");
    const skip = this.hand.find(isSkip);
    if (!skip) throw new Error("no Skip in hand");
    if (!this.stock.length) throw new Error("stock is empty");

    removeCard(this.hand, skip);
    this.discard.push(skip);
    const depth = Math.min(SKIP_DIG_DEPTH, this.stock.length);
    this.digOptions = this.stock.slice(0, depth);
    this.stock.splice(0, depth);
    return [...this.digOptions];
  }

  /** Keep one revealed card; the rest go to the bottom of the stock. */
  takeDug(index) {
    if (this.digOptions === null) throw new Error("no dig in progress");
    if (!(index >= 0 && index < this.digOptions.length)) {
      throw new RangeError(`pick 0..${this.digOptions.length - 1}`);
    }
    const [chosen] = this.digOptions.splice(index, 1);
    this.hand.push(chosen);
    this.stock.push(...this.digOptions);
    this.digOptions = null;

    // A dig deliberately does NOT spend a draw. Charging for it made Skips a
    // net loss in simulation (-1% to -7% across every phase): you burn a draw
    // finding the Skip and another using it, and a choice of three does not
    // pay for two turns.
    this.skipsPlayed += 1;
    this.drewThisTurn = false;
    this._emit("skip_dug", { card: cardToString(chosen) });
    this._failIfOutOfRoad();
    return chosen;
  }

  _failIfOutOfRoad() {
    // A budget that just ran out is only a loss if the phase is not already
    // satisfiable -- otherwise the player is entitled to lay it down.
    if (
      this.state === HAND_STATE.IN_PROGRESS &&
      this.drawsLeft === 0 &&
      !this.canLayDown()
    ) {
      this.markFailed("out_of_draws");
    }
  }

  layDown() {
    const layout = this.solution();
    if (layout === null) throw new Error(`phase ${this.phase} not satisfiable from hand`);
    this.layout = layout;
    this.usedWildsInLayout = layout.flat().filter(isWild).length;
    for (const group of layout) {
      for (const card of group) removeCard(this.hand, card);
    }
    this.state = HAND_STATE.PHASE_LAID;
    this._emit("phase_completed", {
      draws_used: this.drawsUsed,
      wilds_used: this.usedWildsInLayout,
    });
    if (!this.hand.length) {
      this.state = HAND_STATE.WENT_OUT;
      this._emit("went_out", { draws_used: this.drawsUsed });
    }
    return layout;
  }

  // -- bookkeeping ----------------------------------------------------------
  /**
   * End the hand as a loss. Public because a driver that runs the turn loop
   * itself (the client, the autoplayer) has to be able to call it.
   */
  markFailed(reason) {
    this.state = HAND_STATE.FAILED;
    this._emit("hand_failed", { reason, score: handScore(this.hand) });
  }

  _emit(kind, detail = {}) {
    this.events.push({ kind, phase: this.phase, detail });
  }
}

// ---------------------------------------------------------------------------
// cards_short -- the autoplayer heuristic and difficulty probe
// ---------------------------------------------------------------------------

/**
 * Deficits past this are indistinguishable for heuristic purposes, so the
 * search stops there rather than proving exactly how bad a hopeless hand is.
 */
export const SHORT_CAP = 5;

/**
 * Collapse a hand to only what `spec` can actually discriminate on. SET and
 * RUN ignore color; COLOR ignores rank. Projecting onto the relevant axis makes
 * the cache hit constantly across discard candidates.
 */
function canonical(hand, spec) {
  const wilds = hand.filter(isWild).length;
  if (spec.some((g) => g.kind === GROUP.COLOR)) {
    const colors = hand.filter((c) => c.kind === "number").map((c) => c.color).sort();
    return `c|${colors.join(",")}|${wilds}`;
  }
  const ranks = hand
    .filter((c) => c.kind === "number")
    .map((c) => c.rank)
    .sort((a, b) => a - b);
  return `r|${ranks.join(",")}|${wilds}`;
}

function rebuild(key) {
  const [tag, values, wilds] = key.split("|");
  const parts = values === "" ? [] : values.split(",");
  const cards =
    tag === "r"
      ? parts.map((r) => numberCard(Number(r), COLORS[0]))
      : parts.map((c) => numberCard(1, c));
  for (let i = 0; i < Number(wilds); i++) cards.push({ ...WILD });
  return cards;
}

/** All ways to remove `deficit` cards across the groups of `spec`. */
function* reductions(spec, deficit) {
  if (spec.length === 1) {
    if (deficit <= spec[0].size) yield [deficit];
    return;
  }
  for (let first = 0; first <= Math.min(deficit, spec[0].size); first++) {
    for (const rest of reductions(spec.slice(1), deficit - first)) {
      yield [first, ...rest];
    }
  }
}

// Stands in for Python's @lru_cache(maxsize=300_000).
const SHORT_CACHE = new Map();
const SHORT_CACHE_MAX = 300000;

function cardsShortCached(key, spec, minNat, cap, specKey) {
  const memoKey = `${key}|${specKey}|${minNat}|${cap}`;
  const hit = SHORT_CACHE.get(memoKey);
  if (hit !== undefined) return hit;

  const hand = rebuild(key);
  const limit = Math.min(cap, phaseCardCount(spec));
  let answer = limit + 1;

  outer: for (let deficit = 0; deficit <= limit; deficit++) {
    for (const reduction of reductions(spec, deficit)) {
      const shrunk = spec
        .map((g, i) => ({ kind: g.kind, size: g.size - reduction[i] }))
        .filter((g) => g.size > 0);
      if (shrunk.length === 0) {
        answer = deficit;
        break outer;
      }
      if (solvePhase(hand, shrunk, minNat) !== null) {
        answer = deficit;
        break outer;
      }
    }
  }

  if (SHORT_CACHE.size >= SHORT_CACHE_MAX) SHORT_CACHE.clear();
  SHORT_CACHE.set(memoKey, answer);
  return answer;
}

/**
 * How many more useful cards this hand needs to satisfy `spec`.
 *
 * Computed by shrinking the phase until it becomes solvable. A relaxation used
 * as the autoplayer heuristic and as a difficulty probe -- not an exact edit
 * distance. Values above `cap` are reported as cap + 1.
 */
export function cardsShort(hand, spec, minNat = 1, cap = SHORT_CAP) {
  const specKey = spec.map((g) => `${g.kind}${g.size}`).join("+");
  return cardsShortCached(canonical(hand, spec), spec, minNat, cap, specKey);
}
