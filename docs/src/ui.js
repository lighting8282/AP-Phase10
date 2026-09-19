// DOM layer for the browser client.
//
// Same rule the Kivy tab follows: this reads session state and calls into the
// client, and holds no game state of its own. Anything it needed to remember
// would be a second copy of something the session already owns.

import { cardFilename, isWild, points } from "./cards.js";
import { HAND_STATE } from "./engine.js";
import { PHASE_COUNT, phaseDescription } from "./phases.js";
import { Phase10Client } from "./client.js";

const el = (id) => document.getElementById(id);

const app = new Phase10Client({
  onUpdate: () => render(),
  onLog: (line) => log(line),
  onMessage: (text, nodes) => logMessage(text, nodes),
});

//: Rooms can be chatty and this feed never scrolls away on its own.
const MAX_LOG_LINES = 300;

function appendLine(node) {
  const box = el("log");
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.append(node);
  while (box.childElementCount > MAX_LOG_LINES) box.firstElementChild.remove();
  // Only follow the feed if the reader was already at the bottom; yanking the
  // scroll while somebody is reading back is worse than missing a line.
  if (atBottom) box.scrollTop = box.scrollHeight;
}

function log(line) {
  const div = document.createElement("div");
  div.className = "line local";
  div.textContent = line;
  appendLine(div);
}

/**
 * Render one room message from its nodes.
 *
 * The plain text is right there in `text`, but the nodes carry what a player
 * actually scans for -- whether the item that moved was progression or a trap,
 * and whether the player named was them.
 */
function logMessage(text, nodes) {
  const line = document.createElement("div");
  line.className = "line";

  if (!nodes || !nodes.length) {
    line.textContent = text;
    appendLine(line);
    return;
  }

  for (const node of nodes) {
    const span = document.createElement("span");
    span.textContent = node.text;
    span.className = classForNode(node);
    line.append(span);
  }
  appendLine(line);
}

function classForNode(node) {
  switch (node.type) {
    case "item": {
      const item = node.item;
      if (!item) return "n-useful";
      if (item.progression) return "n-progression";
      if (item.trap) return "n-trap";
      if (item.useful) return "n-useful";
      return "n-filler";
    }
    case "location":
      return "n-location";
    case "player": {
      const self = app.client?.players?.self;
      const isSelf = self && node.player && node.player.slot === self.slot;
      return isSelf ? "n-player self" : "n-player";
    }
    case "entrance":
      return "n-entrance";
    case "color":
      return `c-${node.color}`;
    default:
      return "";
  }
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
  const last = hand.events[hand.events.length - 1];
  if (last && last.kind === "hand_failed" && last.detail.opponent) {
    log(`${last.detail.opponent} went out -- your round ends here.`);
  }
  await app.settle(hand);
}

/**
 * Play onto a group on the table.
 *
 * Naturals before wilds, then the most expensive card, because a wild is worth
 * keeping and points in hand are what a lost round costs you.
 */
function hitMeld(meld) {
  const hand = app.session.hand;
  if (!hand || hand.state !== HAND_STATE.IN_PROGRESS) return;
  if (!hand.laid) {
    log("Lay your own phase down before hitting.");
    return;
  }
  const playable = hand.hand
    .filter((c) => meld.accepts(c))
    .sort((a, b) => (isWild(a) - isWild(b)) || (points(b) - points(a)));
  if (!playable.length) {
    log("Nothing in your hand fits that group.");
    return;
  }
  try {
    hand.hit(playable[0], meld);
  } catch (err) {
    log(err.message);
    return;
  }
  log(`Played ${describe(playable[0])} onto the table.`);
  if (hand.state !== HAND_STATE.IN_PROGRESS) settle(hand);
  render();
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
  render();
}

function mulligan() {
  const refusal = app.session.canMulligan();
  if (refusal) {
    log(refusal);
    return;
  }
  app.session.useMulligan();
  log(`Mulligan spent -- fresh hand. ${app.session.mulligansLeft} left.`);
  render();
}

const ACTIONS = {
  draw: () => withHand((hand) => hand.draw(false)),
  "draw-discard": () => withHand((hand) => hand.draw(true)),
  lay: () => withHand((hand) => hand.layDown()),
  skip: () => withHand((hand) => hand.playSkip()),
  mulligan: () => mulligan(),
};

// -- rendering ---------------------------------------------------------------
function render() {
  const s = app.session;
  const hand = s.hand;

  el("summary").textContent =
    `Round ${s.game.roundNumber} - score ${s.totalScore} (lower is better) - ` +
    `won ${s.handsWon} - cleared ${s.clearedPhases.size}/${PHASE_COUNT}` +
    (s.scoreReduction ? ` - ${s.scoreReduction} reduced` : "");

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

  renderTable(s);
  renderOwnMelds(hand);
  renderHand(hand);
  renderDig(hand);
  renderPhases(s);

  for (const button of document.querySelectorAll("#actions button")) {
    button.disabled = !hand || hand.state !== HAND_STATE.IN_PROGRESS;
  }
  // Narrower than the rest: a Mulligan needs a copy in hand and an untouched
  // deal, so it stays disabled even mid-hand.
  const mull = el("mulligan-button");
  mull.disabled = s.canMulligan() !== null;
  mull.textContent = s.mulligansLeft ? `Mulligan (${s.mulligansLeft})` : "Mulligan";
  // The scorecard reports what each round actually cost; reductions get their
  // own line rather than being folded in, so the history stays honest.
  const lines = s.game.scorecard();
  if (s.scoreReduction) {
    lines.push(`  Score Reduction  -${s.scoreReduction} -> ${s.totalScore} points`);
  }
  el("scorecard").textContent = lines.join("\n");
}

/** One group on the table. A button when you could play onto it. */
function meldNode(meld) {
  const hand = app.session.hand;
  const live = Boolean(hand) && hand.state === HAND_STATE.IN_PROGRESS
    && hand.laid && hand.hand.some((c) => meld.accepts(c));

  const node = document.createElement(live ? "button" : "div");
  node.className = live ? "meld live" : "meld";
  if (live) {
    node.title = "Play a card onto this group";
    node.addEventListener("click", () => hitMeld(meld));
  }
  for (const card of meld.cards) {
    const img = document.createElement("img");
    img.src = `assets/cards/${cardFilename(card)}`;
    img.alt = describe(card);
    node.append(img);
  }
  return node;
}

function renderTable(session) {
  const wrap = el("table-wrap");
  const box = el("table");
  const seats = session.seats;
  box.replaceChildren();
  if (!seats.length) {
    // Solo seeds have no table at all, so the whole block goes away rather
    // than leaving an empty heading behind.
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;
  for (const seat of seats) {
    const div = document.createElement("div");
    div.className = "seat";
    if (seat.wentOut) div.classList.add("out");
    else if (seat.laidDown) div.classList.add("laid");

    const who = document.createElement("div");
    who.className = "who";
    who.append(document.createTextNode(`${seat.name} `));
    const tag = document.createElement("span");
    tag.className = "seat-phase";
    tag.textContent = `phase ${seat.phase}`;
    tag.title = phaseDescription(seat.phase);
    who.append(tag);

    const what = document.createElement("div");
    what.className = "what";
    if (seat.wentOut) what.textContent = "went out";
    else if (seat.laidDown) what.textContent = `down - ${seat.hand.length} left to shed`;
    else what.textContent = `building - ${seat.hand.length} cards`;

    div.append(who, what);

    // Their hand, face down. A count is information; a row of backs is the
    // table, and it reads at a glance how close somebody is to going out.
    if (seat.hand.length) {
      const back = document.createElement("div");
      back.className = "seat-hand";
      for (let i = 0; i < seat.hand.length; i += 1) {
        const img = document.createElement("img");
        img.src = "assets/cards/back.png";
        img.alt = "";
        back.append(img);
      }
      div.append(back);
    }

    // What they have on the table, face up and grouped -- and clickable once
    // you are down and holding something that fits.
    if (seat.melds && seat.melds.length) {
      const melds = document.createElement("div");
      melds.className = "melds";
      for (const meld of seat.melds) {
        melds.append(meldNode(meld));
      }
      div.append(melds);
    }

    box.append(div);
  }
}

function renderOwnMelds(hand) {
  const wrap = el("mine-wrap");
  const box = el("mine");
  box.replaceChildren();
  if (!hand || !hand.melds.length) {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;
  for (const meld of hand.melds) box.append(meldNode(meld));
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
  for (let phase = 1; phase <= PHASE_COUNT; phase += 1) {
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
