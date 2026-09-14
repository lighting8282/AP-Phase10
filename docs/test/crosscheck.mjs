/**
 * Differential test: the JS solver must agree with the Python one.
 *
 * fixtures.json holds the reference engine's verdict for every hand, phase and
 * min-naturals setting. This runs the port over the same inputs and fails on
 * any disagreement.
 *
 * It also independently validates every layout the port returns. Matching
 * verdicts only proves the two agree on "possible"; checking the layout proves
 * the port is not saying yes while handing back cards that do not form the
 * phase. The validator deliberately shares no code with the solver.
 *
 *     node docs/test/crosscheck.mjs
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { MAX_RANK, MIN_RANK, cardFromString, cardToString, isNumber, isSkip, isWild }
  from "../src/cards.js";
import { GROUP, PHASES, solvePhase } from "../src/phases.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(readFileSync(join(HERE, "fixtures.json"), "utf8"));

// ---------------------------------------------------------------------------
// Independent validation -- no solver internals used.
// ---------------------------------------------------------------------------

function multisetContains(hand, used) {
  const counts = new Map();
  for (const c of hand) {
    const k = cardToString(c);
    counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  for (const c of used) {
    const k = cardToString(c);
    const n = counts.get(k) ?? 0;
    if (n === 0) return false;
    counts.set(k, n - 1);
  }
  return true;
}

function runIsPossible(ranks, wilds, n) {
  // A run cannot repeat a rank.
  if (new Set(ranks).size !== ranks.length) return false;
  if (ranks.length + wilds !== n) return false;
  if (ranks.length === 0) return n <= MAX_RANK - MIN_RANK + 1;
  const lo = Math.min(...ranks);
  const hi = Math.max(...ranks);
  if (hi - lo + 1 > n) return false;
  // Some window [s, s+n-1] must cover every natural and stay inside 1..12.
  const first = Math.max(MIN_RANK, hi - n + 1);
  const last = Math.min(lo, MAX_RANK - n + 1);
  return first <= last;
}

function validateLayout(hand, spec, layout, minNat) {
  if (layout.length !== spec.length) return "group count differs from the spec";
  const flat = layout.flat();
  if (flat.some(isSkip)) return "a Skip was used in a phase";
  if (!multisetContains(hand, flat)) return "used cards that are not in the hand";

  for (let i = 0; i < spec.length; i++) {
    const g = spec[i];
    const group = layout[i];
    if (group.length !== g.size) return `group ${i} has ${group.length} cards, want ${g.size}`;
    const naturals = group.filter(isNumber);
    const wilds = group.filter(isWild).length;
    if (naturals.length + wilds !== group.length) return `group ${i} holds a non-card`;
    if (naturals.length < minNat) {
      return `group ${i} has ${naturals.length} naturals, want >= ${minNat}`;
    }
    if (g.kind === GROUP.SET) {
      if (new Set(naturals.map((c) => c.rank)).size > 1) return `group ${i} is not one rank`;
    } else if (g.kind === GROUP.RUN) {
      if (!runIsPossible(naturals.map((c) => c.rank), wilds, g.size)) {
        return `group ${i} cannot form a run of ${g.size}`;
      }
    } else if (g.kind === GROUP.COLOR) {
      if (new Set(naturals.map((c) => c.color)).size > 1) return `group ${i} is not one color`;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------

let checked = 0;
let mismatches = 0;
let invalid = 0;
const examples = [];

for (const testCase of fixtures.cases) {
  const hand = testCase.hand.map(cardFromString);
  for (const minNatKey of Object.keys(testCase.verdicts)) {
    const minNat = Number(minNatKey);
    const expected = testCase.verdicts[minNatKey];

    for (let i = 0; i < fixtures.phases.length; i++) {
      const phase = fixtures.phases[i];
      const want = expected[i];

      let layout = null;
      let threw = null;
      try {
        layout = solvePhase(hand, PHASES[phase], minNat);
      } catch (e) {
        threw = e;
      }
      checked++;

      if (threw) {
        mismatches++;
        if (examples.length < 10) {
          examples.push(`phase ${phase} minNat=${minNat} threw ${threw.message} on ${testCase.hand.join(" ")}`);
        }
        continue;
      }

      const got = layout !== null;
      if (got !== want) {
        mismatches++;
        if (examples.length < 10) {
          examples.push(
            `phase ${phase} minNat=${minNat}: python=${want} js=${got}  hand: ${testCase.hand.join(" ")}`
          );
        }
        continue;
      }

      if (layout !== null) {
        const problem = validateLayout(hand, PHASES[phase], layout, minNat);
        if (problem) {
          invalid++;
          if (examples.length < 10) {
            examples.push(
              `phase ${phase} minNat=${minNat}: layout invalid (${problem})  hand: ${testCase.hand.join(" ")}`
            );
          }
        }
      }
    }
  }
}

console.log(`checked   ${checked} verdicts across ${fixtures.cases.length} hands`);
console.log(`mismatch  ${mismatches}`);
console.log(`invalid   ${invalid} layout(s) accepted by the port but not independently valid`);
if (examples.length) {
  console.log("\nfirst failures:");
  for (const e of examples) console.log("  " + e);
}
if (mismatches === 0 && invalid === 0) {
  console.log("\nPASS - the JS port agrees with the Python engine on every verdict");
  process.exit(0);
}
console.log("\nFAIL");
process.exit(1);
