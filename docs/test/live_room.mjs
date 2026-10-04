// Two real browser clients against a real Archipelago server: score DeathLink,
// score traps, and each other's published scores. Needs a live room, so it is
// not part of `npm test`: tools/check_live_room.py generates one and runs this.
//
//     node docs/test/live_room.mjs ws://127.0.0.1:38281
import { Phase10Client } from "../src/client.js";
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const logs = { Alice: [], Bob: [] };
const make = (name) => new Phase10Client({ onLog: (l) => logs[name].push(l) });
const results = [];
const check = (what, ok, detail = "") => { results.push(ok); console.log(`${ok ? "  ok  " : "  FAIL"} ${what}${detail ? `  (${detail})` : ""}`); };

const url = process.argv[2] ?? "ws://127.0.0.1:38281";
const alice = make("Alice"), bob = make("Bob");
await alice.connect(url, "Alice");
await bob.connect(url, "Bob");
await wait(400);
check("both connected with score DeathLink and traps from slot data",
  alice.session.deathLink && alice.session.scoreTraps && alice.session.scoreThreshold === 100);
check("each sees the other as a rival, not started yet",
  alice.rivals.get(bob.client.players.self.slot)?.name === "Bob"
  && bob.rivals.get(alice.client.players.self.slot)?.record === null);

// Bob sits in a hand, so an incoming death has something to take.
const bobPhase = [...bob.session.unlockedPhases][0];
bob.startHand(bobPhase);
check("Bob has a hand in progress", bob.session.hand?.state === "in_progress");

// Alice loses rounds until her score passes 100.
const alicePhase = [...alice.session.unlockedPhases][0];
let rounds = 0;
while (alice.session.totalScore < 100 && rounds < 10) {
  const hand = alice.startHand(alicePhase);
  hand.markFailed("test");
  await alice.settle(hand);
  rounds += 1;
}
await wait(800);
check(`Alice passed 100 points in ${rounds} lost round(s)`, alice.session.totalScore >= 100,
  `score ${alice.session.totalScore}`);
check("Alice sent a DeathLink", logs.Alice.some((l) => l.startsWith("DeathLink sent")),
  logs.Alice.find((l) => l.startsWith("DeathLink sent")));
check("and a score trap is waiting for her next hand",
  alice.session.pending("Lean Deal") === 1, logs.Alice.find((l) => l.includes("will hit")));
check("Bob received it and lost his hand", logs.Bob.some((l) => l.startsWith("DeathLink from Alice")),
  logs.Bob.find((l) => l.startsWith("DeathLink")));
check("Bob's hand is over", !bob.session.hand || bob.session.hand.state !== "in_progress");
check("Bob sent nothing back", !logs.Bob.some((l) => l.startsWith("DeathLink sent")));
const seen = bob.rivals.get(alice.client.players.self.slot)?.record;
check("Bob sees Alice's score, live", seen?.score === alice.session.totalScore,
  JSON.stringify(seen));

// Alice's next hand is dealt short by the trap.
const normal = alice.session.config.handSize + 2;
const next = alice.startHand(alicePhase);
check("the trap hit Alice's next hand", next.hand.length === normal - 2,
  `${next.hand.length} cards instead of ${normal}`);
check("and it is spent", alice.session.pending("Lean Deal") === 0);

// Reconnect: the count is restored, nothing is resent.
const marks = alice.session.scoreMarks;
const sentBefore = logs.Alice.filter((l) => l.startsWith("DeathLink sent")).length;
alice.client.socket.disconnect();
await wait(300);
const again = make("Alice");
await again.connect(url, "Alice");
await wait(400);
check("after reconnecting, the mark count is restored", again.session.scoreMarks === marks,
  `${again.session.scoreMarks} vs ${marks}`);
// The real test: play a round after reconnecting, staying under the next mark.
const firedBefore = again.session.scoreTrapsFired;
const after = again.startHand(alicePhase);
after.hand.splice(1);  // one card left: a small loss, well short of 200
after.markFailed("test");
await again.settle(after);
await wait(500);
check("a round after reconnecting resends no death",
  logs.Alice.filter((l) => l.startsWith("DeathLink sent")).length === sentBefore,
  `score now ${again.session.totalScore}`);
check("and refires no trap", again.session.scoreTrapsFired === firedBefore);

console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
process.exit(results.every(Boolean) ? 0 : 1);
