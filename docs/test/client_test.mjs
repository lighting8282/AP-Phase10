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

for (const line of failures) console.log(`  FAIL ${line}`);
console.log(`\n${passed} passed, ${failures.length} failed`);
process.exit(failures.length ? 1 : 0);
