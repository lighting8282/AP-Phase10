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

import { COLORS, MAX_RANK, MIN_RANK, isNumber, isWild } from "./cards.js";

/**
 * Official rules forbid completing a phase using only wild cards. The exact
 * reading varies by printing and by table, so it is a knob: the number of
 * natural (non-wild) cards each group must contain.
 */
export const DEFAULT_MIN_NATURALS_PER_GROUP = 1;

export const GROUP = { SET: "set", RUN: "run", COLOR: "color" };

const SET = (size) => ({ kind: GROUP.SET, size });
const RUN = (size) => ({ kind: GROUP.RUN, size });
const COLOR = (size) => ({ kind: GROUP.COLOR, size });

/** The ten stock phases, in printed order. */
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
};

export function groupToString(g) {
  if (g.kind === GROUP.COLOR) return `${g.size} cards of one color`;
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
  if (minNat <= 0 && wilds >= n) yield [new Map(), n];
  for (const [rank, avail] of pool) {
    const lo = Math.max(minNat, 1, n - wilds);
    const hi = Math.min(avail, n);
    for (let k = lo; k <= hi; k++) {
      yield [new Map([[rank, k]]), n - k];
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
        yield [used, wildAt.size];
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
  for (const [used, usedWilds] of candidates(head, pool, wilds, minNat)) {
    const sub = search(tail, subtract(pool, used), wilds - usedWilds, minNat);
    if (sub !== null) return [[used, usedWilds], ...sub];
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
  for (const color of COLORS) {
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

export function canComplete(hand, phase, minNaturalsPerGroup = DEFAULT_MIN_NATURALS_PER_GROUP) {
  return solvePhase(hand, PHASES[phase], minNaturalsPerGroup) !== null;
}
