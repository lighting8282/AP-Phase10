// Replay Python's recorded opponent turns through the JS port.
//
// Both clients read the same seed. If the two opponent modules disagree about
// who went out and when, the desktop and browser clients disagree about
// whether you lost the round -- off identical slot data. Nothing else catches
// that, so this compares turn by turn rather than trusting the port.
//
// Regenerate with: python tools/export_opponent_traces.py

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { gameConfig, Table } from "../src/engine.js";
import { buildOpponents, opponentSkill } from "../src/opponents.js";

const here = dirname(fileURLToPath(import.meta.url));
const traces = JSON.parse(readFileSync(join(here, "opponent_traces.json"), "utf8"));

let checks = 0;
const failures = [];

function same(name, actual, expected) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a === e) checks += 1;
  else failures.push(`${name}\n    python ${e}\n    js     ${a}`);
}

for (const [index, trace] of traces.entries()) {
  const cfg = gameConfig({ handSize: trace.hand_size, maxDraws: 99 });

  // The same coin flips Python used, in the same order.
  let cursor = 0;
  const random = () => trace.rolls[cursor++];

  const table = new Table();
  table.seats = buildOpponents(
    trace.phases.length, trace.phases, cfg, random,
    opponentSkill("t", trace.awareness, trace.error),
  );
  const deck = trace.deck.map((c) => ({ ...c }));
  table.reset(deck.slice(1), [deck[0]]);
  table.dealSeats(trace.hand_size);

  for (const [turn, expected] of trace.turns.entries()) {
    const winner = table.endOfTurn();
    const tag = `trace ${index} turn ${turn}`;
    same(`${tag} seats`, table.seats.map((s) => ({
      hand: s.hand.length, laid: s.laidDown, out: s.wentOut, score: s.score,
    })), expected.seats);
    same(`${tag} discard top`, table.discardTop ?? null, expected.discard_top);
    same(`${tag} stock`, table.stock.length, expected.stock);
    same(`${tag} winner`, winner ? winner.name : null, expected.winner);
    if (expected.winner !== null) break;
  }
}

for (const line of failures.slice(0, 8)) console.log(`  FAIL ${line}`);
console.log(`\n${checks} checks passed, ${failures.length} failed`);
process.exit(failures.length ? 1 : 0);
