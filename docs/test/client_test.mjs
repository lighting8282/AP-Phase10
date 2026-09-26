// Socket wiring for the browser client.
//
// The bug this exists for: archipelago.js does not drop listeners when a
// socket closes, so registering them inside connect() stacks a fresh copy on
// every attempt. Two reconnects and every line the room says is printed three
// times -- which looks exactly like the server sending duplicate items, and is
// not. Nothing else in the suite touches connect(), so without this the
// listeners could quietly drift back into it.

import { Phase10Client } from "../src/client.js";

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

for (const line of failures) console.log(`  FAIL ${line}`);
console.log(`\n${passed} passed, ${failures.length} failed`);
process.exit(failures.length ? 1 : 0);
