// Socket wiring for the browser client.
//
// The bug this exists for: archipelago.js does not drop listeners when a
// socket closes, so registering them inside connect() stacks a fresh copy on
// every attempt. Two reconnects and every line the room says is printed three
// times -- which looks exactly like the server sending duplicate items, and is
// not. Nothing else in the suite touches connect(), so without this the
// listeners could quietly drift back into it.

import { Phase10Client } from "../src/client.js";
import { PHASE_COUNT } from "../src/data.js";

let passed = 0;
const failures = [];

function check(name, actual, expected) {
  if (JSON.stringify(actual) === JSON.stringify(expected)) passed += 1;
  else failures.push(`${name}\n    expected ${JSON.stringify(expected)}\n    actual   ${JSON.stringify(actual)}`);
}

/** Stub out everything connect() needs from the network. */
function offline(app, slotData = {}) {
  app.client.login = async () => slotData;
  Object.defineProperty(app.client.items, "received", { get: () => [], configurable: true });
  app.client.storage.fetch = async () => null;
  app.client.storage.prepare = () => ({ replace: () => ({ commit: async () => {} }) });
}

const packet = { cmd: "PrintJSON", data: [{ text: "one line, one packet" }] };

// -- one connect -------------------------------------------------------------
{
  let lines = 0;
  const app = new Phase10Client({ onMessage: () => { lines += 1; } });
  offline(app);
  await app.connect("localhost:38281", "Tester");

  app.client.socket.emit("printJSON", [packet]);
  check("one connect logs a room message once", lines, 1);
}

// -- reconnects --------------------------------------------------------------
{
  let lines = 0;
  const app = new Phase10Client({ onMessage: () => { lines += 1; } });
  offline(app);
  for (let i = 0; i < 3; i += 1) await app.connect("localhost:38281", "Tester");

  app.client.socket.emit("printJSON", [packet]);
  check("three connects still log it once", lines, 1);
}

// Items are resent in full on every connect, so a stacked itemsReceived
// listener re-tallies rather than double-counting -- but it still fires the
// re-render N times, and it is the same registration bug.
{
  let renders = 0;
  const app = new Phase10Client({ onUpdate: () => { renders += 1; } });
  offline(app);
  for (let i = 0; i < 3; i += 1) await app.connect("localhost:38281", "Tester");

  renders = 0;
  app.client.items.emit("itemsReceived", [[], 0]);
  check("three connects redraw once per item batch", renders, 1);
}

// -- free play ---------------------------------------------------------------
// The mode for someone who has never heard of Archipelago: no socket is
// touched at all, so none of it is stubbed here. What matters is that the run
// is playable, that the phases open one at a time, and that nothing tries to
// reach a server.
{
  const logs = [];
  const app = new Phase10Client({ onLog: (line) => logs.push(line) });
  // Any call on the socket would throw, which is the point: free play must
  // not reach for one.
  app.client.login = () => { throw new Error("free play must not log in"); };
  app.client.check = () => { throw new Error("free play must not send checks"); };

  await app.startFreePlay({ fresh: true });
  check("free play is offline", app.offline, true);
  check("and not connected", app.connected, false);
  check("phase 1 is open", [...app.session.unlockedPhases], [1]);
  check("with the full deck of wilds", app.session.count("Wild Card"), 8);
  // No budget at all: a free-play round ends when somebody empties their hand,
  // the way the printed game does.
  check("no draw budget", app.session.config.maxDraws, 0);
  const free = app.startHand(1);
  check("which the hand reports as unlimited", free.unlimitedDraws, true);
  check("and as no number of draws left", free.drawsLeft, null);
  // Drawing past what would have been the budget must not end anything.
  for (let i = 0; i < 12; i += 1) {
    if (!free.drewThisTurn) free.draw(false);
    if (free.hand.length) free.discardCard(free.hand[free.hand.length - 1]);
    if (free.state !== "in_progress") break;
  }
  check("twelve draws in, still no budget failure",
    free.events.some((e) => e.detail?.reason === "out_of_draws"), false);

  // Three opponents is what makes the round end at all: with none, and no
  // budget, nothing would ever stop it.
  check("three opponents", app.session.opponents, 3);
  check("no store", app.session.storeSlots, 0);

  // Clearing a phase opens the next one, which is how the printed game goes.
  await app.startFreePlay({ fresh: true });
  const hand = app.startHand(1);
  hand.layDown = () => {};
  hand.state = "went_out";
  await app.settle(hand);
  check("clearing phase 1 opens phase 2", [...app.session.unlockedPhases].sort((a, b) => a - b), [1, 2]);
  check("and says so", logs.some((l) => l.includes("Phase 2 is open")), true);

  // Saving must not throw where there is no localStorage, which is Node, and
  // is also a private window.
  check("a round was recorded", app.session.game.rounds.length, 1);
}

// -- ten phases or twenty ----------------------------------------------------
// Free play only. An Archipelago seed is always the full set, because its
// locations exist for every phase.
{
  const app = new Phase10Client({});
  app.client.login = () => { throw new Error("free play must not log in"); };

  await app.startFreePlay({ fresh: true, phases: 10 });
  check("a ten-phase run caps at ten", app.phaseCap, 10);

  // Clearing ten must not open an eleventh.
  for (let phase = 1; phase <= 10; phase += 1) {
    const hand = app.startHand(phase);
    hand.state = "went_out";
    await app.settle(hand);
  }
  check("ten cleared", app.session.clearedPhases.size, 10);
  check("and nothing beyond it opens", Math.max(...app.session.unlockedPhases), 10);

  const twenty = new Phase10Client({});
  await twenty.startFreePlay({ fresh: true, phases: 20 });
  check("twenty is the other choice", twenty.phaseCap, 20);

  const bad = new Phase10Client({});
  await bad.startFreePlay({ fresh: true, phases: 13 });
  check("anything else falls back to the full set", bad.phaseCap, PHASE_COUNT);

  const seed = new Phase10Client({});
  check("a seed is not capped at all", seed.phaseCap, PHASE_COUNT);
}

// -- what was on the table when the round ended ------------------------------
// The seat panels show this until the next round starts, and the round ends
// the instant somebody goes out -- which is exactly when you want to read it.
{
  const logs = [];
  const app = new Phase10Client({ onLog: (line) => logs.push(line) });
  await app.startFreePlay({ fresh: true });

  const hand = app.startHand(1);
  const seats = app.session.seats;
  check("there are seats to report on", seats.length, 3);
  // Put something down on one of them, so there is something to describe.
  const opponent = seats[0];
  opponent.hand = [];
  opponent.laidDown = true;
  hand.markFailed("test");
  await app.settle(hand);

  const reported = logs.filter((line) => line.startsWith(`  ${opponent.name}`));
  check("every seat is reported", logs.filter((l) => l.startsWith("  ")).length, 3);
  check("including the one that emptied its hand", reported.length, 1);
  // Defaulted rather than indexed blind: with no report at all the filter
  // comes back empty, and a crash here would hide the one real failure.
  check("and it says what it had down", (reported[0] ?? "").includes("nothing down"), true);
}

for (const line of failures) console.log(`  FAIL ${line}`);
console.log(`\n${passed} passed, ${failures.length} failed`);
process.exit(failures.length ? 1 : 0);
