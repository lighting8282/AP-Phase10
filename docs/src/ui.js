// DOM layer for the browser client.
//
// Same rule the Kivy tab follows: this reads session state and calls into the
// client, and holds no game state of its own. Anything it needed to remember
// would be a second copy of something the session already owns.

import { cardFilename } from "./cards.js";
import { HAND_STATE } from "./engine.js";
import { phaseDescription } from "./phases.js";
import { Phase10Client } from "./client.js";

const el = (id) => document.getElementById(id);

const app = new Phase10Client({
  onUpdate: () => render(),
  onLog: (line) => log(line),
});

function log(line) {
  const box = el("log");
  box.textContent += `${line}\n`;
  box.scrollTop = box.scrollHeight;
}

function cardButton(card, onClick) {
  const button = document.createElement("button");
  button.className = "card";
  const img = document.createElement("img");
  img.src = `assets/cards/${cardFilename(card)}`;
  img.alt = describe(card);
  button.title = img.alt;
  button.append(img);
  button.addEventListener("click", onClick);
  return button;
}

function describe(card) {
  if (card.kind === "wild") return "Wild";
  if (card.kind === "skip") return "Skip";
  return `${card.rank} ${card.color}`;
}

// -- actions -----------------------------------------------------------------
async function settle(hand) {
  await app.settle(hand);
}

function withHand(fn) {
  const hand = app.session.hand;
  if (!hand || hand.state !== HAND_STATE.IN_PROGRESS) {
    log("No hand in progress -- pick a phase first.");
    return;
  }
  try {
    fn(hand);
  } catch (err) {
    log(err.message);
    return;
  }
  if (hand.state !== HAND_STATE.IN_PROGRESS) settle(hand);
  else // Exposed deliberately: it is what the browser test harness drives, and it
// lets a player inspect their own state from the console. Read-only in
// practice -- every mutation still goes through the client.
globalThis.phase10 = app;

render();
}

const ACTIONS = {
  draw: () => withHand((hand) => hand.draw(false)),
  "draw-discard": () => withHand((hand) => hand.draw(true)),
  lay: () => withHand((hand) => hand.layDown()),
  skip: () => withHand((hand) => hand.playSkip()),
};

// -- rendering ---------------------------------------------------------------
function render() {
  const s = app.session;
  const hand = s.hand;

  el("summary").textContent =
    `Round ${s.game.roundNumber} - score ${s.totalScore} (lower is better) - ` +
    `won ${s.handsWon} - cleared ${s.clearedPhases.size}/10`;

  if (hand) {
    el("objective").textContent = `Phase ${hand.phase}: ${phaseDescription(hand.phase)}`;
    el("stats").textContent =
      `draws left ${hand.drawsLeft} - stock ${hand.stock.length} - ` +
      `discard ${hand.discardTop ? describe(hand.discardTop) : "none"} - ` +
      `skips in hand ${hand.skipsInHand}`;
  } else {
    const c = s.config;
    el("objective").textContent = "No round in progress -- pick a phase below.";
    el("stats").textContent =
      `deck: ${c.wildsInDeck} wilds - ${c.maxDraws} draws per hand - ` +
      `hand size ${c.handSize} - ${c.startingSkips} skip(s) per hand` +
      (s.lockedPhase ? ` - Phase Lock: replay ${s.lockedPhase}` : "");
  }

  renderHand(hand);
  renderDig(hand);
  renderPhases(s);

  for (const button of document.querySelectorAll("#actions button")) {
    button.disabled = !hand || hand.state !== HAND_STATE.IN_PROGRESS;
  }
  el("scorecard").textContent = s.game.scorecard().join("\n");
}

function renderHand(hand) {
  const box = el("hand");
  box.replaceChildren();
  if (!hand) return;
  hand.hand.forEach((card, index) => {
    box.append(cardButton(card, () => withHand((h) => h.discardCard(h.hand[index]))));
  });
}

function renderDig(hand) {
  const wrap = el("dig");
  const box = el("dig-cards");
  box.replaceChildren();
  if (!hand || !hand.digPending) {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;
  hand.digOptions.forEach((card, index) => {
    box.append(cardButton(card, () => withHand((h) => h.takeDug(index))));
  });
}

function renderPhases(session) {
  const box = el("phases");
  box.replaceChildren();
  const unlocked = session.unlockedPhases;
  for (let phase = 1; phase <= 10; phase += 1) {
    const button = document.createElement("button");
    button.textContent = String(phase);
    button.title = phaseDescription(phase);
    if (session.clearedPhases.has(phase)) button.classList.add("cleared");
    else if (unlocked.has(phase)) button.classList.add("open");
    button.disabled = !unlocked.has(phase) || Boolean(session.hand);
    button.addEventListener("click", () => app.startHand(phase));
    box.append(button);
  }
}

// -- wiring ------------------------------------------------------------------
for (const button of document.querySelectorAll("#actions button")) {
  button.addEventListener("click", () => ACTIONS[button.dataset.action]());
}

el("connect").addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = el("status");
  const button = el("connect-button");
  button.disabled = true;
  status.className = "";
  status.textContent = "connecting...";
  try {
    await app.connect(el("url").value.trim(), el("slot").value.trim(), el("password").value);
    status.className = "live";
    status.textContent = "connected";
  } catch (err) {
    status.className = "error";
    status.textContent = err.message || "connection failed";
    log(`Connection failed: ${err.message}`);
    button.disabled = false;
    return;
  }
  button.disabled = false;
});

// Exposed deliberately: it is what the browser test harness drives, and it
// lets a player inspect their own state from the console. Read-only in
// practice -- every mutation still goes through the client.
globalThis.phase10 = app;

render();
