// Replay the Python session's recorded behaviour against the JS port.
//
// The session decides which location IDs a finished hand is worth. Getting
// that wrong reports the wrong check, and nothing notices until a seed is half
// played -- so this compares against Python rather than against my own
// expectations of the port.
//
// Regenerate the fixtures with: python tools/export_session_fixtures.py

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { Phase10Session } from "../src/session.js";
import { Phase10Game } from "../src/game.js";
import {
  AP_POINT, LOCATION_NAME_TO_ID, MULLIGAN, PHASE_COUNT, SCORE_REDUCTION,
  SCORE_REDUCTION_VALUE, phaseUnlock, storeGate, storeLocationName,
} from "../src/data.js";

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = JSON.parse(readFileSync(join(here, "session_fixtures.json"), "utf8"));

let passed = 0;
const failures = [];

function check(name, actual, expected) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a === e) {
    passed += 1;
  } else {
    failures.push(`${name}\n    expected ${e}\n    actual   ${a}`);
  }
}

function session(slot, items) {
  const s = Phase10Session.fromSlotData(slot, new Phase10Game({ seed: 0 }));
  s.setItems(items);
  return s;
}

// -- config derivation -------------------------------------------------------
for (const c of fixtures.config) {
  const s = session(
    { goal: 0, starting_draws: c.starting_draws, checks_per_phase: 4 },
    c.items,
  );
  const cfg = s.config;
  check(
    `config draws=${c.starting_draws} items=[${c.items.join(",")}]`,
    {
      handSize: cfg.handSize,
      wildsInDeck: cfg.wildsInDeck,
      maxDraws: cfg.maxDraws,
      startingSkips: cfg.startingSkips,
    },
    c.config,
  );
}

// -- earned tiers ------------------------------------------------------------
for (const t of fixtures.tiers) {
  const s = session(
    { goal: 0, starting_draws: t.budget, checks_per_phase: t.checks_per_phase },
    [phaseUnlock(3)],
  );
  const hand = s.startHand(3);
  hand.state = t.state;
  hand.usedWildsInLayout = t.wilds;
  hand.drawsUsed = t.draws;
  check(
    `tiers checks=${t.checks_per_phase} ${t.state} wilds=${t.wilds} draws=${t.draws}/${t.budget}`,
    s.earnedTiers(hand),
    t.tiers,
  );
}

// -- full settle sequences ---------------------------------------------------
fixtures.sequences.forEach((script, index) => {
  const items = [];
  for (let p = 1; p <= PHASE_COUNT; p += 1) items.push(phaseUnlock(p));
  items.push("Phase Lock");
  const s = session(
    { goal: script.goal, starting_draws: 8, checks_per_phase: 4 },
    items,
  );

  script.steps.forEach((step, stepIndex) => {
    const hand = s.startHand(step.phase);
    hand.state = step.state;
    hand.usedWildsInLayout = 1;
    hand.drawsUsed = 5;
    hand.hand = [];
    const ids = s.finishHand(hand).slice().sort((a, b) => a - b);
    const label = `seq${index} step${stepIndex} phase ${step.phase} ${step.state}`;
    check(`${label} ids`, ids, step.ids);
    check(`${label} handsWon`, s.handsWon, step.handsWon);
    check(`${label} lockedPhase`, s.lockedPhase, step.lockedPhase);
    check(`${label} goalMet`, s.goalMet, step.goalMet);
  });
});

// -- payload round trip ------------------------------------------------------
{
  const before = session({ goal: 0, starting_draws: 8, checks_per_phase: 4 },
    [phaseUnlock(2), phaseUnlock(7)]);
  for (const phase of [2, 7, 2]) {
    const hand = before.startHand(phase);
    hand.state = "phase_laid";
    hand.usedWildsInLayout = 0;
    hand.drawsUsed = 2;
    hand.hand = [];
    before.finishHand(hand);
  }
  const after = session({ goal: 0, starting_draws: 8, checks_per_phase: 4 }, []);
  check("payload restores", after.loadPayload(before.toPayload()), true);
  check("payload restores score", after.totalScore, before.totalScore);
  check("payload restores wins", after.handsWon, before.handsWon);
  check("payload restores cleared", [...after.clearedPhases].sort(), [...before.clearedPhases].sort());
  check("payload survives JSON", (() => {
    const fresh = session({ goal: 0, starting_draws: 8, checks_per_phase: 4 }, []);
    return fresh.loadPayload(JSON.parse(JSON.stringify(before.toPayload()))) && fresh.totalScore;
  })(), before.totalScore);
  check("checked locations are not stored", "checked_locations" in before.toPayload(), false);
}

// -- death link ---------------------------------------------------------------
{
  check("death link off by default", session({}, []).deathLink, false);
  check("death link read from slot data",
    session({ death_link: true }, []).deathLink, true);

  const s = session({ death_link: true }, [phaseUnlock(1)]);
  check("a death between rounds costs nothing", s.killHand(), null);

  const hand = s.startHand(1);
  const killed = s.killHand();
  check("a death fails the hand in progress", killed === hand, true);
  check("the killed hand is failed", hand.state, "failed");
  check("a killed hand awards nothing", s.finishHand(hand), []);
  check("a killed hand is still a round played", s.game.rounds.length, 1);
  check("a killed hand is not a win", s.handsWon, 0);

  const done = session({ death_link: true }, [phaseUnlock(2)]);
  const laid = done.startHand(2);
  laid.state = "phase_laid";
  check("a death cannot re-fail a finished hand", done.killHand(), null);
  check("the finished hand keeps its state", laid.state, "phase_laid");
}

// -- fillers -----------------------------------------------------------------
// Mirrors TestMulligan / TestScoreReduction on the Python side.
{
  const opened = (copies) => {
    const s = session({}, [...Array(copies).fill(MULLIGAN), phaseUnlock(1)]);
    s.startHand(1);
    return s;
  };

  const none = session({}, [phaseUnlock(1)]);
  none.startHand(1);
  check("no Mulligans without the item", none.mulligansLeft, 0);
  check("and it says so", none.canMulligan(), "No Mulligans left.");

  const one = opened(1);
  const before = one.hand.hand.map((c) => `${c.kind}${c.rank}${c.color}`);
  check("a Mulligan is available on an untouched deal", one.canMulligan(), null);
  const drawsBefore = one.hand.drawsLeft;
  one.useMulligan();
  const after = one.hand.hand.map((c) => `${c.kind}${c.rank}${c.color}`);
  check("the hand is replaced", after.join() !== before.join(), true);
  check("it costs no draw", one.hand.drawsLeft, drawsBefore);
  check("the deal is full", one.hand.hand.length, one.config.handSize);
  check("the discard is reset to one", one.hand.discard.length, 1);
  // The opponents hold cards off the same deck, so counting only what the
  // player can see loses thirty of them.
  const seated = one.seats.reduce((n, seat) => n + seat.hand.length, 0);
  check(
    "the deck is conserved",
    one.hand.hand.length + seated + one.hand.discard.length + one.hand.stock.length,
    96 + one.config.wildsInDeck,
  );
  check("and it is spent", one.mulligansLeft, 0);

  const drawn = opened(1);
  drawn.hand.draw();
  check(
    "refused after the first draw",
    drawn.canMulligan(),
    "A Mulligan only works before your first draw.",
  );
  let threw = false;
  try {
    drawn.useMulligan();
  } catch {
    threw = true;
  }
  check("using it anyway throws", threw, true);
  check("a refusal does not spend it", drawn.mulligansLeft, 1);

  const idle = session({}, [MULLIGAN]);
  check("refused between rounds", idle.canMulligan(), "No hand in progress.");

  // Persistence: the count has to survive a reconnect or it is free forever.
  const saved = opened(2);
  saved.useMulligan();
  saved.game.hand = null;
  const restored = session({}, [MULLIGAN, MULLIGAN]);
  check("the payload loads", restored.loadPayload(saved.toPayload()), true);
  check("spent Mulligans survive a reconnect", restored.mulligansLeft, 1);

  const legacy = saved.toPayload();
  delete legacy.mulligans_used;
  const old = session({}, [MULLIGAN, MULLIGAN]);
  check("a save from before Mulligans worked still loads", old.loadPayload(legacy), true);
  check("and restores as none spent", old.mulligansLeft, 2);
}

{
  // A lost round worth exactly 80: low number cards are five each.
  const scored = (points, reductions) => {
    const items = Array(reductions).fill(SCORE_REDUCTION);
    const s = session({}, [...items, phaseUnlock(1)]);
    const hand = s.startHand(1);
    hand.state = "failed";
    hand.hand = Array(points / 5).fill({ kind: "number", rank: 5, color: "red" });
    s.finishHand(hand);
    return s;
  };

  const plain = scored(80, 0);
  check("the round really is worth 80", plain.game.totalScore, 80);
  check("no reduction leaves it alone", plain.totalScore, 80);

  const cut = scored(80, 2);
  check("each copy takes off its value", cut.scoreReduction, 2 * SCORE_REDUCTION_VALUE);
  check("the reported score drops", cut.totalScore, 80 - 2 * SCORE_REDUCTION_VALUE);
  check("the scorecard keeps the real cost", cut.game.totalScore, 80);

  check("floored at zero", scored(10, 4).totalScore, 0);
}

// -- what the seats are caught holding ---------------------------------------
// The mirror of test_session.py's block of the same name. The numbers are the
// ones the Python suite pins, so a port that drifts here shows up as a
// different score rather than as a crash.
{
  const seated = (opponents) => {
    const s = Phase10Session.fromSlotData(
      { goal: 0, starting_draws: 4, checks_per_phase: 4, opponents },
      new Phase10Game({ seed: 0 }),
    );
    s.setItems([phaseUnlock(1)]);
    return s;
  };

  const s = seated(3);
  const hand = s.startHand(1);
  s.seats[0].hand = [
    { kind: "number", rank: 12, color: "red" },
    { kind: "number", rank: 5, color: "blue" },
  ];
  s.seats[1].hand = [];
  hand.markFailed("test");
  s.finishHand(hand);
  check("a seat scores what it is caught holding", s.opponentScores[0], 15);
  check("and going out scores nothing", s.opponentScores[1], 0);

  const run = seated(1);
  for (let i = 0; i < 2; i += 1) {
    const h = run.startHand(1);
    run.seats[0].hand = [{ kind: "number", rank: 3, color: "green" }];
    h.markFailed("test");
    run.finishHand(h);
  }
  check("seat scores accumulate across rounds", run.opponentScores, [10]);

  const fresh = seated(1);
  check("they survive a reconnect", fresh.loadPayload(run.toPayload()), true);
  check("with the same totals", fresh.opponentScores, run.opponentScores);

  const older = run.toPayload();
  delete older.opponent_scores;
  const legacy = seated(1);
  check("a save without them still loads", legacy.loadPayload(older), true);
  check("and starts them at zero", legacy.opponentScores, [0]);

  // The cap was hardcoded to 10 and stayed there when the phases went to 20.
  const top = seated(1);
  top._opponentPhases = [PHASE_COUNT - 1];
  const climbing = top.startHand(1);
  top.seats[0].laidDown = true;
  climbing.markFailed("test");
  top.finishHand(climbing);
  check("a seat below the last phase still climbs", top.opponentPhases, [PHASE_COUNT]);

  const capped = seated(1);
  capped._opponentPhases = [PHASE_COUNT];
  const last = capped.startHand(1);
  capped.seats[0].laidDown = true;
  last.markFailed("test");
  capped.finishHand(last);
  check("and stops at the last one", capped.opponentPhases, [PHASE_COUNT]);
}

// -- the store ---------------------------------------------------------------
// The mirror of TestStore in phase10/test/test_session.py. Two numbers: a slot
// opens at a gate on points received, and costs a price out of points unspent.
{
  const store = (slots, points) => {
    const s = Phase10Session.fromSlotData(
      { goal: 0, starting_draws: 4, checks_per_phase: 4, store_slots: slots },
      new Phase10Game({ seed: 0 }),
    );
    s.setItems(Array(points).fill(AP_POINT));
    return s;
  };
  const POINTS = 10;   // store_points(6): the ladder's 8 plus 2 slack

  check("no points buys nothing", store(6, 0).canBuy(1).includes("opens at 1"), true);

  // Guarded rather than chained: a buy that throws would take the whole suite
  // down and hide every check after it, which is the opposite of what a
  // failure should do.
  const one = store(6, 1);
  check("one point opens the first slot", one.canBuy(1), null);
  if (one.canBuy(1) === null) {
    check("buying returns its id", one.buySlot(1), LOCATION_NAME_TO_ID[storeLocationName(1)]);
    check("and spends the point", one.pointsLeft, 0);
  }

  const twice = store(6, 4);
  if (twice.canBuy(1) === null) twice.buySlot(1);
  check("a slot cannot be bought twice", (twice.canBuy(1) ?? "").includes("already bought"), true);

  // Spending does not close a slot the gate had already opened.
  const gated = store(6, storeGate(2));
  if (gated.canBuy(1) === null) gated.buySlot(1);
  check("the gate is on points received, not points left", gated.canBuy(2), null);

  // The invariant the ladder exists for, over every point count and order.
  const orders = [];
  const permute = (rest, acc) => {
    if (!rest.length) { orders.push(acc); return; }
    rest.forEach((v, i) => permute([...rest.slice(0, i), ...rest.slice(i + 1)], [...acc, v]));
  };
  permute([1, 2, 3, 4, 5, 6], []);
  let stranded = null;
  for (let points = 0; points <= POINTS && !stranded; points += 1) {
    for (const order of orders) {
      const s = store(6, points);
      for (const slot of order) {
        const refusal = s.canBuy(slot);
        if (refusal === null) s.buySlot(slot);
        else if (refusal.includes("costs")) { stranded = `${points}: ${refusal}`; break; }
      }
      if (stranded) break;
    }
  }
  check("an open slot is always affordable, in any order", stranded, null);

  const full = store(6, POINTS);
  for (const slot of [6, 5, 4, 3, 2, 1]) {
    if (full.canBuy(slot) === null) full.buySlot(slot);
  }
  check("a full purse buys every slot dearest-first", full.boughtSlots.size, 6);

  check("no store refuses", store(0, 10).canBuy(1), "This seed has no store.");
  check("a slot past the end refuses", (store(4, 10).canBuy(5) ?? "").includes("slots 1 to 4"), true);

  const saved = store(6, POINTS);
  if (saved.canBuy(1) === null) saved.buySlot(1);
  if (saved.canBuy(5) === null) saved.buySlot(5);
  const fresh = store(6, POINTS);
  check("purchases survive a reconnect", fresh.loadPayload(saved.toPayload()), true);
  check("with the same slots", [...fresh.boughtSlots].sort(), [1, 5]);
  check("and the same balance", fresh.pointsLeft, saved.pointsLeft);

  const older = saved.toPayload();
  delete older.bought_slots;
  const legacy = store(6, POINTS);
  check("a save without purchases still loads", legacy.loadPayload(older), true);
  check("with nothing bought", legacy.boughtSlots.size, 0);
}

for (const line of failures) console.log(`  FAIL ${line}`);
console.log(`\n${passed} passed, ${failures.length} failed`);
process.exit(failures.length ? 1 : 0);
