/**
 * Phase definitions and the phase-satisfaction solver.
 *
 * A direct port of phase10/game/phases.py, kept deliberately close to the
 * original so the two can be read side by side. test/crosscheck.mjs runs both
 * over the same hands and requires identical verdicts.
 *
 * A phase is a tuple of groups. A group is one of:
 *     SET(n)    n cards of the same rank, colors irrelevant
 *     RUN(n)    n cards of consecutive ranks, colors irrelevant, no wraparound
 *     COLOR(n)  n cards of the same color, ranks irrelevant
 *
 * Wilds substitute for any card. Skips can never be part of a phase.
 */

import { COLORS, MAX_RANK, MIN_RANK, isNumber, isSkip, isWild } from "./cards.js";

/**
 * Official rules forbid completing a phase using only wild cards. The exact
 * reading varies by printing and by table, so it is a knob: the number of
 * natural (non-wild) cards each group must contain.
 */
export const DEFAULT_MIN_NATURALS_PER_GROUP = 1;

export const GROUP = { SET: "set", RUN: "run", COLOR: "color" };

// SET and COLOR can be anchored to a particular rank or color: SET(3, 7) is
// three 7s, COLOR(5, "green") is five green cards. null means "any", which is
// the free group the stock ten use.
//
// Anchoring is harder than it looks, and in the opposite direction to the
// intuition that a named target is simpler -- a free group lets you pivot to
// whichever rank or color the deal was kind about. Measured, five cards of a
// named color clears 49% where five of any one color clears 79%.
const SET = (size, rank = null) => ({ kind: GROUP.SET, size, rank, color: null });
const RUN = (size) => ({ kind: GROUP.RUN, size, rank: null, color: null });
const COLOR = (size, color = null) => ({ kind: GROUP.COLOR, size, rank: null, color });

/** The stock ten in printed order, then ten more ordered by measured rate. */
export const PHASES = {
  1: [SET(3), SET(3)],
  2: [SET(3), RUN(4)],
  3: [SET(4), RUN(4)],
  4: [RUN(7)],
  5: [RUN(8)],
  6: [RUN(9)],
  7: [SET(4), SET(4)],
  8: [COLOR(7)],
  9: [SET(5), SET(2)],
  10: [SET(5), SET(3)],

  // Measured at the same baseline as the stock ten (0 wilds, 8 draws, greedy
  // autoplayer), 600 trials, and ordered by that measurement. They fill a hole
  // the original ten left: nothing above 66%.
  11: [COLOR(5)],                 // 94%
  12: [SET(3), SET(2)],           // 91%
  13: [RUN(5), SET(2)],           // 79%
  14: [COLOR(6)],                 // 72%
  15: [RUN(4), RUN(4)],           // 62%
  16: [RUN(4), RUN(4), SET(2)],   // 57%
  17: [RUN(5), SET(3)],           // 49%
  18: [RUN(6), SET(3)],           // 29%
  19: [RUN(5), RUN(5)],           // 22%
  20: [SET(3), SET(3), SET(3)],   // 11%
};

/**
 * How many phases exist, and the hard ceiling on a phase's size: a phase can
 * never ask for more cards than a hand holds, so three sets of four (twelve
 * cards) is unclearable at any budget rather than merely hard.
 */
export const PHASE_COUNT = Object.keys(PHASES).length;
export const MAX_PHASE_CARDS = 10;

export function groupToString(g) {
  if (g.kind === GROUP.COLOR) {
    return g.color ? `${g.size} ${g.color} cards` : `${g.size} cards of one color`;
  }
  if (g.kind === GROUP.SET && g.rank !== null && g.rank !== undefined) {
    return `${g.size} ${g.rank}s`;
  }
  return `${g.kind === GROUP.SET ? "set" : "run"} of ${g.size}`;
}

export function phaseDescription(phase) {
  return PHASES[phase].map(groupToString).join(" + ");
}

export function phaseCardCount(spec) {
  return spec.reduce((n, g) => n + g.size, 0);
}

// ---------------------------------------------------------------------------
// Rank pool
//
// Python uses collections.Counter, whose subtraction DROPS non-positive
// counts. A plain Map would keep zeroes and change which ranks the candidate
// loop iterates, so subtract() reproduces the drop exactly.
// ---------------------------------------------------------------------------

function poolFromHand(hand) {
  // Insertion order follows first appearance in the hand, as Counter does.
  const pool = new Map();
  for (const c of hand) {
    if (isNumber(c)) pool.set(c.rank, (pool.get(c.rank) ?? 0) + 1);
  }
  return pool;
}

function poolGet(pool, rank) {
  return pool.get(rank) ?? 0;
}

function subtract(pool, used) {
  const out = new Map();
  for (const [rank, count] of pool) {
    const left = count - (used.get(rank) ?? 0);
    if (left > 0) out.set(rank, left);   // Counter drops <= 0
  }
  return out;
}

/** All k-combinations of `items`, in itertools.combinations order. */
function* combinations(items, k) {
  const n = items.length;
  if (k > n) return;
  const idx = Array.from({ length: k }, (_, i) => i);
  yield idx.map((i) => items[i]);
  if (k === 0) return;
  for (;;) {
    let i = k - 1;
    while (i >= 0 && idx[i] === i + n - k) i--;
    if (i < 0) return;
    idx[i]++;
    for (let j = i + 1; j < k; j++) idx[j] = idx[j - 1] + 1;
    yield idx.map((m) => items[m]);
  }
}

// ---------------------------------------------------------------------------
// Candidate generation
// ---------------------------------------------------------------------------

function* setCandidates(spec, pool, wilds, minNat) {
  const n = spec.size;
  // A group built purely from wilds has no rank to anchor on, so the per-rank
  // loop below (which starts at k >= 1) can never emit it. Emit it once here.
  if (minNat <= 0 && wilds >= n) yield [new Map(), n, ["set", null]];
  // An anchored SET may only be built from its own rank, so the pool it may
  // draw on is that one entry -- including when the hand holds none of it,
  // which is what makes anchoring hard.
  const ranks = spec.rank !== null && spec.rank !== undefined
    ? [[spec.rank, pool.get(spec.rank) ?? 0]]
    : [...pool];
  for (const [rank, avail] of ranks) {
    const lo = Math.max(minNat, 1, n - wilds);
    const hi = Math.min(avail, n);
    for (let k = lo; k <= hi; k++) {
      yield [new Map([[rank, k]]), n - k, ["set", rank]];
    }
  }
}

function* runCandidates(spec, pool, wilds, minNat) {
  const n = spec.size;
  if (n > MAX_RANK) return;
  for (let start = MIN_RANK; start <= MAX_RANK - n + 1; start++) {
    const ranks = Array.from({ length: n }, (_, i) => start + i);
    const forced = [];
    const optional = [];
    ranks.forEach((r, i) => (poolGet(pool, r) === 0 ? forced : optional).push(i));
    if (forced.length > wilds) continue;

    for (let extraN = 0; extraN <= optional.length; extraN++) {
      if (forced.length + extraN > wilds) break;
      if (n - (forced.length + extraN) < minNat) continue;
      for (const extra of combinations(optional, extraN)) {
        const wildAt = new Set([...forced, ...extra]);
        const used = new Map();
        ranks.forEach((r, i) => {
          if (!wildAt.has(i)) used.set(r, (used.get(r) ?? 0) + 1);
        });
        yield [used, wildAt.size, ["run", start]];
      }
    }
  }
}

function* candidates(spec, pool, wilds, minNat) {
  if (spec.kind === GROUP.SET) yield* setCandidates(spec, pool, wilds, minNat);
  else if (spec.kind === GROUP.RUN) yield* runCandidates(spec, pool, wilds, minNat);
  else throw new Error(`${spec.kind} is solved separately`);
}

function search(specs, pool, wilds, minNat) {
  if (specs.length === 0) return [];
  const [head, ...tail] = specs;
  for (const [used, usedWilds, meaning] of candidates(head, pool, wilds, minNat)) {
    const sub = search(tail, subtract(pool, used), wilds - usedWilds, minNat);
    if (sub !== null) return [[used, usedWilds, meaning], ...sub];
  }
  return null;
}

/** Turn a rank-level plan back into concrete cards taken from the hand. */
function materialize(hand, plans) {
  const byRank = new Map();
  const wildStack = [];
  for (const card of hand) {
    if (isWild(card)) wildStack.push(card);
    else if (isNumber(card)) {
      if (!byRank.has(card.rank)) byRank.set(card.rank, []);
      byRank.get(card.rank).push(card);
    }
  }
  const layout = [];
  for (const [used, usedWilds] of plans) {
    const group = [];
    for (const [rank, count] of used) {
      for (let i = 0; i < count; i++) group.push(byRank.get(rank).pop());
    }
    for (let i = 0; i < usedWilds; i++) group.push(wildStack.pop());
    layout.push(group);
  }
  return layout;
}

function solveColor(hand, spec, minNat) {
  const n = spec.size;
  const wilds = hand.filter(isWild);
  // Anchored: one color to try, not the best of four.
  const palette = spec.color ? [spec.color] : COLORS;
  for (const color of palette) {
    const naturals = hand.filter((c) => isNumber(c) && c.color === color);
    const k = Math.min(naturals.length, n);
    const needWild = n - k;
    if (k < minNat || needWild > wilds.length) continue;
    return [[...naturals.slice(0, k), ...wilds.slice(0, needWild)]];
  }
  return null;
}

/**
 * Return a concrete lay-down for `spec` from `hand`, or null if impossible.
 * Skips are ignored entirely -- they can never be part of a phase.
 */
export function solvePhase(hand, spec, minNaturalsPerGroup = DEFAULT_MIN_NATURALS_PER_GROUP) {
  const kinds = new Set(spec.map((g) => g.kind));
  if (kinds.has(GROUP.COLOR)) {
    if (kinds.size !== 1 || spec.length !== 1) {
      throw new Error(
        "COLOR groups are only supported as a phase's sole group. " +
          "Mixing COLOR with SET/RUN needs joint rank+color search."
      );
    }
    return solveColor(hand, spec[0], minNaturalsPerGroup);
  }
  const wilds = hand.filter(isWild).length;
  const plans = search(spec, poolFromHand(hand), wilds, minNaturalsPerGroup);
  if (plans === null) return null;
  return materialize(hand, plans);
}

/**
 * A group on the table, and what it means.
 *
 * Port of phases.py's Meld. `cards` is what you can see; `kind` plus
 * rank/color/lo/hi is what a hit has to satisfy. A run remembers the span it
 * occupies, because deriving that afterwards is ambiguous -- a lone 5 with two
 * wilds could be 3-4-5, 4-5-6 or 5-6-7.
 */
export class Meld {
  constructor(spec, cards, kind, { rank = null, color = null, lo = null, hi = null } = {}) {
    this.spec = spec;
    this.cards = cards;
    this.kind = kind;
    this.rank = rank;
    this.color = color;
    this.lo = lo;
    this.hi = hi;
  }

  get length() {
    return this.cards.length;
  }

  [Symbol.iterator]() {
    return this.cards[Symbol.iterator]();
  }

  /** Can this card be laid onto this group? */
  accepts(card) {
    if (isSkip(card)) return false; // a Skip is never part of a phase
    if (isWild(card)) {
      // A wild fits anywhere except a run already pinned to both ends of the
      // deck, where there is no rank left for it to stand in for.
      return this.kind !== GROUP.RUN || this._openEnds().length > 0;
    }
    if (this.kind === GROUP.SET) return this.rank === null || card.rank === this.rank;
    if (this.kind === GROUP.COLOR) return this.color === null || card.color === this.color;
    return this._openEnds().includes(card.rank);
  }

  _openEnds() {
    const ends = [];
    if (this.lo !== null && this.lo > MIN_RANK) ends.push(this.lo - 1);
    if (this.hi !== null && this.hi < MAX_RANK) ends.push(this.hi + 1);
    return ends;
  }

  /** Lay `card` on, widening a run's span. Callers check accepts() first. */
  add(card) {
    if (this.kind === GROUP.RUN) {
      let target;
      if (isWild(card)) {
        // Spend the wild on whichever end is still open, low first --
        // arbitrary, but it has to pick one or the span is a lie.
        const ends = this._openEnds().sort((a, b) => a - b);
        target = ends.length ? ends[0] : null;
      } else {
        target = card.rank;
      }
      if (target !== null && target !== undefined) {
        if (this.lo === null || target < this.lo) this.lo = target;
        if (this.hi === null || target > this.hi) this.hi = target;
      }
    }
    this.cards.push(card);
  }
}

/**
 * Like solvePhase, but the groups remember what they are.
 *
 * Kept beside solvePhase rather than replacing it: everything that only needs
 * "which cards leave my hand" still gets a plain list of lists, and the two
 * cannot drift, because the layout is built out of these melds.
 */
export function solveMelds(hand, spec, minNaturalsPerGroup = DEFAULT_MIN_NATURALS_PER_GROUP) {
  const kinds = new Set(spec.map((g) => g.kind));
  if (kinds.has(GROUP.COLOR)) {
    if (kinds.size !== 1 || spec.length !== 1) {
      throw new Error(
        "COLOR groups are only supported as a phase's sole group. " +
          "Mixing COLOR with SET/RUN needs joint rank+color search."
      );
    }
    const groups = solveColor(hand, spec[0], minNaturalsPerGroup);
    if (groups === null) return null;
    const natural = groups[0].find((c) => isNumber(c));
    const color = spec[0].color ?? (natural ? natural.color : null);
    return [new Meld(spec[0], [...groups[0]], GROUP.COLOR, { color })];
  }

  const wilds = hand.filter(isWild).length;
  const plans = search(spec, poolFromHand(hand), wilds, minNaturalsPerGroup);
  if (plans === null) return null;

  const groups = materialize(hand, plans);
  return spec.map((groupSpec, i) => {
    const [kind, value] = plans[i][2];
    if (kind === "set") {
      return new Meld(groupSpec, [...groups[i]], GROUP.SET, { rank: value });
    }
    return new Meld(groupSpec, [...groups[i]], GROUP.RUN,
      { lo: value, hi: value + groupSpec.size - 1 });
  });
}

export function canComplete(hand, phase, minNaturalsPerGroup = DEFAULT_MIN_NATURALS_PER_GROUP) {
  return solvePhase(hand, PHASES[phase], minNaturalsPerGroup) !== null;
}
