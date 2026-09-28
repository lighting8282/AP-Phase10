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

import { SKIP, WILD, cardToString, isSkip, numberCard } from "../src/cards.js";
import { HAND_STATE, PhaseHand, Table, gameConfig, mulberry32 } from "../src/engine.js";
import { MID, buildOpponents } from "../src/opponents.js";
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


// -- no draw budget ---------------------------------------------------------
// The mirror of the block of the same name in tests/test_game.py. Free play
// takes the budget away entirely; Archipelago never asks for it, because the
// starting_draws option starts at 2.
{
  const bare = (maxDraws) =>
    new PhaseHand(1, gameConfig({ wildsInDeck: 0, maxDraws }),
      { random: mulberry32(9), table: new Table() });

  const free = bare(0);
  check(free.unlimitedDraws === true, "zero maxDraws is unlimited");
  check(free.drawsLeft === null, "and reports no number of draws left");

  const budgeted = bare(6);
  check(budgeted.unlimitedDraws === false, "a budget is not unlimited");
  eq(budgeted.drawsLeft, 6, "and still reports a number");

  // With a budget, twenty turns ends the hand. Without one it must not.
  const long = bare(0);
  for (let i = 0; i < 20 && long.state === HAND_STATE.IN_PROGRESS; i += 1) {
    long.draw();
    long.discardCard(long.hand[long.hand.length - 1]);
  }
  check(long.state === HAND_STATE.IN_PROGRESS, "no budget never runs out of road");
  eq(long.drawsUsed, 20, "and every draw was taken");

  // A drained stock comes back from the discard rather than losing the hand.
  const drained = bare(0);
  drained.discard.push(...drained.table.stock);
  drained.table.stock.length = 0;
  const top = drained.discard[drained.discard.length - 1];
  const before = drained.discard.length;
  drained.draw();
  check(drained.state === HAND_STATE.IN_PROGRESS, "an empty stock is refilled");
  eq(drained.discard.length, 1, "leaving just the face-up card");
  eq(drained.discard[0], top, "which is the one that was face up");
  eq(drained.table.stock.length, before - 2, "and the rest back in the stock");

  // The refill is not a promise of infinite cards.
  const spent = bare(0);
  spent.table.stock.length = 0;
  spent.discard.splice(0, spent.discard.length - 1);
  try { spent.draw(); } catch { /* expected */ }
  check(spent.state === HAND_STATE.FAILED, "nothing to shuffle back still fails");
}


// -- groups read in order ---------------------------------------------------
// The mirror of test_a_run_stays_in_rank_order in tests/test_phases.py. Both
// clients render meld.cards directly, so the order is the model's job.
{
  const h = new PhaseHand(4, gameConfig({ wildsInDeck: 0, maxDraws: 0 }),
    { random: mulberry32(1), table: new Table() });
  h.spec = [{ kind: "run", size: 4, rank: null, color: null }];
  h.hand = [numberCard(8, "yellow"), numberCard(9, "blue"), numberCard(10, "blue"),
    WILD, numberCard(6, "yellow"), numberCard(4, "yellow")];
  const option = h.layDownOptions().find((o) => o.description === "run 7-10, wild as 7");
  h.layDown(option);
  const meld = h.melds[0];
  eq(meld.cards.map(cardToString), ["W", "8Y", "9B", "10B"], "a run lays in rank order");
  h.hit(numberCard(6, "yellow"), meld);
  eq(meld.cards.map(cardToString), ["6Y", "W", "8Y", "9B", "10B"],
    "and a hit lands in its place, not on the end");

  // Not merely sorted to the front: a wild belongs in its own gap.
  const g = new PhaseHand(4, gameConfig({ wildsInDeck: 0, maxDraws: 0 }),
    { random: mulberry32(1), table: new Table() });
  g.spec = [{ kind: "run", size: 4, rank: null, color: null }];
  g.hand = [numberCard(8, "yellow"), WILD, numberCard(10, "blue"), numberCard(11, "blue")];
  g.layDown();
  eq(g.melds[0].cards.map(cardToString), ["8Y", "W", "10B", "11B"],
    "a wild sits in the gap it stands for");
}


// -- a Skip that denies a turn ----------------------------------------------
// The mirror of the block of the same name in tests/test_game.py. Free play
// plays the printed rule; a seed keeps the dig its clear rates were measured
// with, so the default must not move.
{
  const denyTable = (seed = 11, seats = 3) => {
    const cfg = gameConfig({ wildsInDeck: 8, maxDraws: 0, startingSkips: 2,
      skipMode: "deny" });
    const random = mulberry32(seed);
    const table = new Table();
    const hand = new PhaseHand(1, cfg, { random, table });
    if (seats) {
      table.seats = buildOpponents(seats, Array(seats).fill(1), cfg, random, MID);
      table.dealSeats(cfg.handSize);
    }
    return { hand, table };
  };

  eq(gameConfig({}).skipMode, "dig", "the default is still the dig");

  const denied = denyTable();
  const before = denied.hand.stock.length;
  const revealed = denied.hand.playSkip();
  eq(revealed, [], "denying reveals nothing");
  check(!denied.hand.digPending, "and leaves no dig to resolve");
  const event = denied.hand.events.find((e) => e.kind === "skip_denied");
  eq(event.detail.seat, denied.table.seats[0].name, "it names who lost the turn");
  check(denied.hand.discard.some(isSkip), "the Skip is spent onto the discard");
  check(before - denied.hand.stock.length < 4,
    "and the table takes less off the stock than a full round of turns");

  // A seat already denied is passed over, or a second Skip costs nothing.
  const pair = denyTable();
  pair.table.seats[0].skipped = true;
  eq(pair.table.nextActor().name, pair.table.seats[1].name, "a denied seat is passed over");

  const alone = denyTable(11, 0);
  let refused = false;
  try { alone.hand.playSkip(); } catch { refused = true; }
  check(refused, "a Skip with nobody to skip is refused");
}

// -- paced opponents --------------------------------------------------------
// The browser client shows the seats moving one at a time, three seconds
// apart, so a paced hand queues their turns instead of playing them. What is
// tested here is that pacing is presentation only: the same deal, the same
// rolls and the same player moves have to reach the same table either way,
// because the seats decide what to do from the state they find.
{
  const cfg = gameConfig({ handSize: 10, maxDraws: 20 });

  /** One hand with three seats, dealt off a fixed seed. */
  const deal = (paced) => {
    const random = mulberry32(11);
    const table = new Table();
    table.seats = buildOpponents(3, [1, 2, 3], cfg, random, MID);
    return new PhaseHand(1, cfg, { random, table, paced });
  };

  /** Everything the player can see of the table, as text. */
  const snapshot = (hand) => JSON.stringify({
    state: hand.state,
    hand: hand.hand.length,
    stock: hand.stock.length,
    discard: hand.discard.length,
    seats: hand.table.seats.map((s) => ({
      hand: s.hand.length, laid: s.laidDown, out: s.wentOut, score: s.score,
    })),
  });

  /** Five turns of the dullest possible play: draw, throw what was drawn. */
  const playFive = (hand, afterTurn = () => {}) => {
    for (let i = 0; i < 5 && hand.state === HAND_STATE.IN_PROGRESS; i += 1) {
      hand.draw();
      hand.discardCard(hand.hand[hand.hand.length - 1]);
      afterTurn(hand);
    }
  };

  const straight = deal(false);
  const straightLog = [];
  playFive(straight, (h) => straightLog.push(...h.table.drainLog()));

  const walkedLog = [];
  const walked = deal(true);
  playFive(walked, (hand) => {
    // One seat at a time, the way the UI steps them.
    check(hand.turnPending || hand.state !== HAND_STATE.IN_PROGRESS,
      "a paced turn leaves the seats waiting");
    while (hand.turnPending) {
      const seat = hand.stepOpponent();
      if (seat === null) break;
      // Drained per seat, which is what lets the UI print a seat's lines
      // beside the pause they belong to.
      walkedLog.push(...hand.table.drainLog());
    }
  });

  eq(snapshot(walked), snapshot(straight), "pacing the seats changes no state");
  check(!walked.turnPending, "and leaves nothing owed once walked");
  // The narration is what the pauses are for; an empty feed would make the
  // wait pure delay. Draining it per seat has to yield what draining it once
  // at the end of the turn did, or the two clients tell different stories.
  eq(walkedLog, straightLog, "and says exactly what the unpaced table said");
  check(walkedLog.length > 0, "every stepped seat reports what it did");
  check(walkedLog.every(([who]) => ["Ada", "Bo", "Cy"].includes(who)),
    "each line names a seat");

  // A seat already out is not narrated again every turn.
  const quiet = deal(true);
  quiet.table.seats[0].wentOut = true;
  quiet.draw();
  quiet.discardCard(quiet.hand[quiet.hand.length - 1]);
  const first = quiet.stepOpponent();
  eq(quiet.table.drainLog(), [], "a seat that is already out says nothing");
  check(first === quiet.table.seats[0], "but it is still the seat that was stepped");

  // The regression this split could most easily cause. Consuming a Skip lives
  // in playSeat rather than in the endOfTurn loop precisely so the paced walk
  // cannot lose it -- a denied seat that quietly took its turn anyway is the
  // bug that is invisible on screen and changes who wins the round.
  const denied = deal(true);
  denied.table.seats[0].skipped = true;
  const heldBefore = denied.table.seats[0].hand.length;
  denied.draw();
  denied.discardCard(denied.hand[denied.hand.length - 1]);
  const skippedSeat = denied.stepOpponent();
  eq(denied.table.drainLog(), [["Ada", "misses a turn"]],
    "a denied seat misses its turn in the paced walk too");
  check(skippedSeat.skipped === false, "and the Skip is spent, not left armed");
  eq(skippedSeat.hand.length, heldBefore, "and the seat did not play");

  // finishOpponentTurns is the way out when pacing is interrupted.
  const rushed = deal(true);
  rushed.draw();
  rushed.discardCard(rushed.hand[rushed.hand.length - 1]);
  check(rushed.turnPending, "turns are owed before the rush");
  rushed.finishOpponentTurns();
  check(!rushed.turnPending, "and none after it");

  // A Mulligan redeals the table, so a turn owed by the old deal is dropped.
  const mulled = deal(true);
  mulled.pendingSeats = [...mulled.table.seats];
  mulled.redeal();
  check(!mulled.turnPending, "a Mulligan drops any turn still owed");
}

console.log(`\n${passed} passed, ${failures.length} failed`);
process.exit(failures.length ? 1 : 0);
