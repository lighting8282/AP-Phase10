/**
 * Differential test for the turn loop.
 *
 * crosscheck.mjs covers the solver -- which hands can lay a phase down. This
 * covers everything around it: draw ordering, what a Skip dig does to the
 * stock, when a hand fails for running out of road, what the score ends up as.
 *
 * engine_traces.json holds the Python engine playing 240 scripted games. The
 * port replays the same deal and the same actions and must land on an
 * identical state after every single one.
 *
 *     node docs/test/crosscheck_engine.mjs
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { cardFromString, cardToString } from "../src/cards.js";
import { HAND_STATE, PhaseHand, gameConfig } from "../src/engine.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const { traces } = JSON.parse(readFileSync(join(HERE, "engine_traces.json"), "utf8"));

/** Mirrors snapshot() in tools/export_engine_traces.py, key for key. */
function snapshot(hand) {
  return {
    hand: hand.hand.map(cardToString),
    discard_top: hand.discardTop ? cardToString(hand.discardTop) : null,
    discard_len: hand.discard.length,
    stock_len: hand.stock.length,
    draws_used: hand.drawsUsed,
    draws_left: hand.drawsLeft,
    state: hand.state,
    drew_this_turn: hand.drewThisTurn,
    dig_options: hand.digOptions ? hand.digOptions.map(cardToString) : null,
    skips_played: hand.skipsPlayed,
    skips_in_hand: hand.skipsInHand,
    can_lay_down: hand.canLayDown(),
    used_wilds_in_layout: hand.usedWildsInLayout,
    events: hand.events.map((e) => ({ kind: e.kind, detail: e.detail })),
  };
}

/** First field that differs, so a failure names the cause instead of dumping. */
function firstDifference(want, got) {
  for (const key of Object.keys(want)) {
    const a = JSON.stringify(want[key]);
    const b = JSON.stringify(got[key]);
    if (a !== b) return `${key}: python=${a} js=${b}`;
  }
  return null;
}

let tracesChecked = 0;
let actionsChecked = 0;
let failures = 0;
const examples = [];

function note(msg) {
  failures++;
  if (examples.length < 8) examples.push(msg);
}

for (const [t, trace] of traces.entries()) {
  const config = gameConfig(trace.config);
  const deck = trace.deck.map(cardFromString);

  let hand;
  try {
    hand = new PhaseHand(trace.phase, config, { deck });
  } catch (e) {
    note(`trace ${t} phase ${trace.phase}: constructor threw ${e.message}`);
    continue;
  }
  tracesChecked++;

  const initialDiff = firstDifference(trace.initial, snapshot(hand));
  if (initialDiff) {
    note(`trace ${t} phase ${trace.phase} initial deal -> ${initialDiff}`);
    continue;
  }

  let broke = false;
  for (const [i, step] of trace.steps.entries()) {
    try {
      switch (step.action) {
        case "draw":
          hand.draw(step.from_discard);
          break;
        case "discard":
          hand.discardCard(cardFromString(step.card));
          break;
        case "play_skip":
          hand.playSkip();
          break;
        case "take_dug":
          hand.takeDug(step.index);
          break;
        case "lay_down":
          hand.layDown();
          break;
        case "mark_failed":
          hand.markFailed(step.reason);
          break;
        default:
          throw new Error(`unknown action ${step.action}`);
      }
    } catch (e) {
      note(`trace ${t} phase ${trace.phase} step ${i} (${step.action}) threw: ${e.message}`);
      broke = true;
      break;
    }
    actionsChecked++;

    const diff = firstDifference(step.after, snapshot(hand));
    if (diff) {
      note(`trace ${t} phase ${trace.phase} step ${i} (${step.action}) -> ${diff}`);
      broke = true;
      break;
    }
  }
  if (broke) continue;
}

const states = new Map();
for (const trace of traces) {
  const last = trace.steps.length ? trace.steps.at(-1).after.state : trace.initial.state;
  states.set(last, (states.get(last) ?? 0) + 1);
}

console.log(`replayed  ${tracesChecked}/${traces.length} traces`);
console.log(`actions   ${actionsChecked} compared, state checked after every one`);
console.log(`outcomes  ${[...states].map(([k, v]) => `${k}=${v}`).join("  ")}`);
console.log(`failures  ${failures}`);
if (examples.length) {
  console.log("\nfirst failures:");
  for (const e of examples) console.log("  " + e);
}
if (failures === 0) {
  console.log("\nPASS - the port reaches identical state after every action");
  process.exit(0);
}
console.log("\nFAIL");
process.exit(1);
