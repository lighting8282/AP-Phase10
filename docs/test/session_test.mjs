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
  MULLIGAN, SCORE_REDUCTION, SCORE_REDUCTION_VALUE, phaseUnlock,
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
  for (let p = 1; p <= 10; p += 1) items.push(phaseUnlock(p));
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

for (const line of failures) console.log(`  FAIL ${line}`);
console.log(`\n${passed} passed, ${failures.length} failed`);
process.exit(failures.length ? 1 : 0);
