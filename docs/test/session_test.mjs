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
import { phaseUnlock } from "../src/data.js";

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

for (const line of failures) console.log(`  FAIL ${line}`);
console.log(`\n${passed} passed, ${failures.length} failed`);
process.exit(failures.length ? 1 : 0);
