/**
 * Tests for the game/scorecard layer.
 *
 * Not a differential test -- game.js carries no rules, so there is nothing for
 * the solver fixtures to compare against. What matters here is scoring by the
 * printed rules and, especially, that loadPayload refuses anything it does not
 * fully recognise: that payload arrives over the network from AP Data Storage,
 * and half-loading it would overwrite a real scorecard with garbage.
 *
 *     node docs/test/game_test.mjs
 */

import { SKIP, WILD, numberCard } from "../src/cards.js";
import { HAND_STATE, gameConfig, mulberry32 } from "../src/engine.js";
import { Phase10Game, SAVE_VERSION, roundToString } from "../src/game.js";

let passed = 0;
const failures = [];

function check(condition, message) {
  if (condition) {
    passed++;
    console.log(`  ok   ${message}`);
  } else {
    failures.push(message);
    console.log(`  FAIL ${message}`);
  }
}

function eq(a, b, message) {
  check(JSON.stringify(a) === JSON.stringify(b), `${message} (got ${JSON.stringify(a)})`);
}

// -- scoring ----------------------------------------------------------------

const game = new Phase10Game({ random: mulberry32(7) });
eq(game.roundNumber, 1, "a fresh game is on round 1");
eq(game.totalScore, 0, "a fresh game has scored nothing");
eq(game.bestRound, null, "a fresh game has no best round");

// Drive a hand to each terminal state by hand, so scoring is checked directly.
const config = gameConfig({ handSize: 10, maxDraws: 20 });

const laid = game.startRound(1, config);
laid.hand = [numberCard(5, "red"), WILD, SKIP];   // 5 + 25 + 15
laid.state = HAND_STATE.PHASE_LAID;
const r1 = game.finishRound();
eq(r1.score, 45, "a cleared hand scores the cards left over");
eq(r1.number, 1, "the first result is round 1");

const out = game.startRound(2, config);
out.hand = [];
out.state = HAND_STATE.WENT_OUT;
const r2 = game.finishRound();
eq(r2.score, 0, "going out scores zero");

const failed = game.startRound(3, config);
failed.hand = [numberCard(12, "blue"), numberCard(3, "green")];   // 10 + 5
failed.state = HAND_STATE.FAILED;
const r3 = game.finishRound();
eq(r3.score, 15, "a failed hand scores the whole hand");

eq(game.totalScore, 60, "total score accumulates across rounds");
eq(game.roundsWon, 2, "only cleared rounds count as won");
eq([...game.clearedPhases].sort(), [1, 2], "cleared phases exclude the failed one");
eq(game.bestRound.phase, 2, "best round is the lowest score");
eq(game.historyFor(1).length, 1, "history filters by phase");
eq(game.roundNumber, 4, "round number follows the count of finished rounds");

check(roundToString(r2).includes("went out"), "roundToString labels going out");
check(roundToString(r3).includes("failed"), "roundToString labels a failure");

// -- guards -----------------------------------------------------------------

game.startRound(4, config);
let threw = false;
try { game.startRound(5, config); } catch { threw = true; }
check(threw, "cannot start a round while one is in progress");

threw = false;
try { game.finishRound(); } catch { threw = true; }
check(threw, "cannot finish a round that is still in progress");
game.hand = null;

// -- persistence ------------------------------------------------------------

const payload = game.toPayload();
eq(payload.version, SAVE_VERSION, "payload carries the save version");
eq(payload.rounds.length, 3, "payload carries every finished round");

const restored = new Phase10Game();
check(restored.loadPayload(payload), "a good payload loads");
eq(restored.totalScore, 60, "score survives the round trip");
eq(restored.roundsWon, 2, "wins survive the round trip");
eq(restored.rounds.length, 3, "every round survives the round trip");

// Everything below arrives from the network and must be refused whole.
const rejects = [
  [null, "null"],
  [undefined, "undefined"],
  ["not an object", "a string"],
  [42, "a number"],
  [[], "an array"],
  [{}, "an empty object"],
  [{ version: SAVE_VERSION + 1, rounds: [] }, "a future save version"],
  [{ version: SAVE_VERSION }, "a payload with no rounds"],
  [{ version: SAVE_VERSION, rounds: "nope" }, "rounds that are not a list"],
  [{ version: SAVE_VERSION, rounds: [null] }, "a null round"],
  [{ version: SAVE_VERSION, rounds: [{ number: 1 }] }, "a round missing fields"],
  [
    { version: SAVE_VERSION, rounds: [{ ...payload.rounds[0], state: "bogus" }] },
    "a round with an unknown state",
  ],
  [
    { version: SAVE_VERSION, rounds: [{ ...payload.rounds[0], score: "lots" }] },
    "a round with a non-numeric score",
  ],
  [
    { version: SAVE_VERSION, rounds: [{ ...payload.rounds[0], score: 1.5 }] },
    "a round with a fractional score",
  ],
];

for (const [bad, label] of rejects) {
  const target = new Phase10Game();
  target.loadPayload(payload);                   // start from a real scorecard
  const took = target.loadPayload(bad);
  check(!took, `rejects ${label}`);
  check(target.rounds.length === 3, `keeps the existing scorecard after ${label}`);
}

// -- scorecard --------------------------------------------------------------

eq(new Phase10Game().scorecard(), ["No rounds played yet."], "empty scorecard says so");
const card = game.scorecard();
check(card.at(-2).includes("3 rounds"), "scorecard reports the round count");
check(card.at(-1).startsWith("best:"), "scorecard ends with the best round");

const many = new Phase10Game();
many.loadPayload({
  version: SAVE_VERSION,
  rounds: Array.from({ length: 14 }, (_, i) => ({ ...payload.rounds[0], number: i + 1 })),
});
check(many.scorecard(10)[0].includes("4 earlier round(s)"), "scorecard elides old rounds");

// Not "r2". The mirror of test_scorecard_names_the_round_in_full in
// tests/test_game.py: both ports print this line to their own client, so the
// wording is shared and pinned on both sides.
{
  const rounds = game.scorecard().filter((l) => l.startsWith("round"));
  eq(rounds.length, 3, "every round is named in full");
  // Defaulted rather than indexed blind: when the prefix is wrong the filter
  // comes back empty, and a crash here would take the rest of the suite with
  // it instead of reporting the one failure.
  check((rounds[1] ?? "").startsWith("round 2   phase "), "the round number is spelled out");
}

console.log(`\n${passed} passed, ${failures.length} failed`);
process.exit(failures.length ? 1 : 0);
