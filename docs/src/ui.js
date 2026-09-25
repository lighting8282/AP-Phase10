// DOM layer for the browser client.
//
// Same rule the Kivy tab follows: this reads session state and calls into the
// client, and holds no game state of its own. Anything it needed to remember
// would be a second copy of something the session already owns.

import { SKIP, WILD, cardFilename, isWild, points } from "./cards.js";

//: Faces used purely as icons in the stat panel.
const SKIP_FACE = SKIP;
const WILD_FACE = WILD;
import { HAND_STATE } from "./engine.js";
import {
  HANDS_WON_MILESTONES, LOCATION_NAME_TO_ID, TIERS, milestoneLocationName,
  phaseLocationName, storeGate, storeLocationName,
} from "./data.js";
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

// -- the stat panel ----------------------------------------------------------
// Counts you check every single turn. They live in their own column because
// reading them should not mean finding them again in a paragraph.

/** A stack of cards, for the stock. */
const ICON_STOCK = `<svg viewBox="0 0 24 24" aria-hidden="true">
  <rect x="3" y="6" width="12" height="16" rx="2"/>
  <rect x="6.5" y="3.5" width="12" height="16" rx="2"/>
</svg>`;

/** A card with an arrow coming off it, for draws left. */
const ICON_DRAW = `<svg viewBox="0 0 24 24" aria-hidden="true">
  <rect x="2.5" y="4" width="11" height="16" rx="2"/>
  <path d="M17 8v8m0 0l-3-3m3 3l3-3"/>
</svg>`;

function iconTile(icon, value, label, extra = "") {
  const tile = document.createElement("div");
  tile.className = `tile ${extra}`.trim();
  const art = document.createElement("div");
  art.className = "tile-icon";
  art.innerHTML = icon;
  const body = document.createElement("div");
  body.className = "tile-body";
  const v = document.createElement("span");
  v.className = "tile-value";
  v.textContent = String(value);
  const l = document.createElement("span");
  l.className = "tile-label";
  l.textContent = label;
  body.append(v, l);
  tile.append(art, body);
  return tile;
}

/** A tile whose icon is a real card face -- wilds, skips, the discard top. */
function cardTile(card, value, label, extra = "") {
  const art = card
    ? `<img src="assets/cards/${cardFilename(card)}" alt="${describe(card)}">`
    : `<img src="assets/cards/back.png" alt="">`;
  const tile = iconTile(art, value, label, `card ${extra}`.trim());
  if (card) tile.title = describe(card);
  return tile;
}

function renderStats(session, hand) {
  const box = el("stats");
  box.replaceChildren();

  if (hand) {
    box.append(iconTile(ICON_DRAW, hand.drawsLeft, "draws left",
      hand.drawsLeft === 0 ? "spent" : ""));
    box.append(iconTile(ICON_STOCK, hand.stock.length, "in the stock"));
    // The discard's icon is the card itself: what is on top is the whole
    // point of looking, and a generic pile symbol would say nothing.
    box.append(cardTile(hand.discardTop, hand.discardTop ? describe(hand.discardTop) : "empty",
      "on the discard", "wide"));
    box.append(cardTile(SKIP_FACE, hand.skipsInHand, "skips in hand"));
    box.append(cardTile(WILD_FACE, hand.config.wildsInDeck, "wilds in the deck"));
  } else {
    const c = session.config;
    box.append(iconTile(ICON_DRAW, c.maxDraws, "draws per hand"));
    box.append(iconTile(ICON_STOCK, c.handSize, "cards dealt"));
    box.append(cardTile(SKIP_FACE, c.startingSkips, "skips per hand"));
    box.append(cardTile(WILD_FACE, c.wildsInDeck, "wilds in the deck"));
  }

  if (session.lockedPhase) {
    const warn = document.createElement("div");
    warn.className = "tile locked";
    warn.textContent = `Phase Lock: replay ${session.lockedPhase}`;
    box.append(warn);
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
  } else {
    el("objective").textContent = "No round in progress -- pick a phase below.";
  }
  renderStats(s, hand);

  el("you-phase").textContent = hand ? `phase ${hand.phase}` : "";
  // Your own total in the same place as theirs: a scoreboard split across two
  // parts of the page is one you have to assemble before you can read it.
  el("you-score").textContent = `${s.totalScore} pts`;

  renderTable(s);
  renderMiddle(hand);
  renderOwnMelds(hand);
  renderHand(hand);
  renderDig(hand);
  renderPhases(s);
  renderStore(s);
  renderChecks(s);

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
  const box = el("table");
  const seats = session.seats;
  // Solo seeds have no table at all. An empty row collapses on its own, so
  // there is nothing to hide.
  box.replaceChildren();
  seats.forEach((seat, index) => {
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

    // The running total, the way the pad on the table works: what the seat
    // has been caught holding so far, lower being better as it is for you.
    // The phase says how it is doing this round; nothing said how the run had
    // gone, which is the half you play against.
    const score = document.createElement("span");
    score.className = "seat-score";
    score.textContent = `${session.opponentScores[index] ?? 0} pts`;
    score.title = "points it has been caught holding so far";
    who.append(score);

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
  });
}

function renderOwnMelds(hand) {
  const box = el("mine");
  box.replaceChildren();
  if (!hand) return;
  for (const meld of hand.melds) box.append(meldNode(meld));
}

/**
 * The middle of the table: the two piles, and what to do with them.
 *
 * The piles are the controls. A separate row of Draw / Take discard buttons
 * asked the player to look away from the card they were deciding about.
 */
function renderMiddle(hand) {
  const stock = el("stock-pile");
  const discard = el("discard-pile");
  const face = el("discard-face");
  const live = Boolean(hand) && hand.state === HAND_STATE.IN_PROGRESS;
  const drawn = live && hand.drewThisTurn;

  el("stock-count").textContent = hand ? String(hand.stock.length) : "";
  stock.disabled = !live || drawn || hand.digPending;

  const top = hand ? hand.discardTop : null;
  discard.classList.toggle("empty", !top);
  face.src = top ? `assets/cards/${cardFilename(top)}` : "assets/cards/back.png";
  face.alt = top ? describe(top) : "";
  discard.title = top ? describe(top) : "the discard pile is empty";
  discard.disabled = !live || drawn || !top || hand.digPending;

  el("prompt").textContent = promptFor(hand, live, drawn);
}

function promptFor(hand, live, drawn) {
  if (!hand) return "* Pick a phase below to start a round *";
  if (!live) return "* The round is over *";
  if (hand.digPending) return "* Keep one of the dug cards *";
  if (!drawn) return "* Draw or pick up a card *";
  return "* Play what you can, then discard a card *";
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

// -- the store ---------------------------------------------------------------
// The one place a check is bought rather than played for. A slot opens at a
// gate on points received and costs a price out of points unspent -- both, so
// that buying in any order stays inside the logic the seed was built on.

async function buy(slot) {
  try {
    await app.buySlot(slot);
  } catch (err) {
    log(err.message);
    return;
  }
  log(`Bought store slot ${slot}. ${app.session.pointsLeft} point(s) left.`);
  render();
}

function renderStore(session) {
  const box = el("store");
  const summary = el("store-summary");
  box.replaceChildren();

  // A seed with no store loses the whole section rather than keeping a
  // heading over an explanation of why there is nothing under it.
  const slots = session.storeSlots;
  el("store-wrap").hidden = !slots;
  if (!slots) return;

  summary.textContent =
    `${session.pointsLeft} unspent of ${session.points} AP Points received`;

  const done = checkedLocations(session);
  for (let slot = 1; slot <= slots; slot += 1) {
    const price = session.storePrice(slot);
    const bought = session.boughtSlots.has(slot)
      || done.has(LOCATION_NAME_TO_ID[storeLocationName(slot)]);
    if (bought) {
      box.append(checkPill(`✓ Slot ${slot}`, "done", `Store Slot ${slot} -- bought`));
      continue;
    }
    const refusal = session.canBuy(slot);
    const button = document.createElement("button");
    button.className = `chk buy ${refusal ? "locked" : "open"}`;
    button.textContent = `Slot ${slot} - ${price}`;
    button.title = refusal ?? `Buy Store Slot ${slot} for ${price} point(s)`;
    button.disabled = Boolean(refusal);
    button.addEventListener("click", () => buy(slot));
    box.append(button);
  }
}

// -- the check list ----------------------------------------------------------
// What a player asks between rounds is "what is left, and can I get it yet".
// Answering it used to mean counting phases against the tier table in the
// README, so this is that table with the seed's own state written onto it.

/**
 * The checks this seed actually has, from the server when connected.
 *
 * `checks_per_phase` is in slot data, so the tier prefix is known offline
 * too -- but the room knows for certain, and a list that disagrees with the
 * server about what exists is worse than no list.
 */
function seedLocations() {
  const all = app.client?.room?.allLocations;
  return Array.isArray(all) && all.length ? new Set(all) : null;
}

/**
 * Locations already checked.
 *
 * The session's own set is deliberately not persisted -- the server is the
 * authority -- so on a reconnect it is empty while the room still knows. Both
 * are merged: the session covers checks made this session before the room
 * echoes them back.
 */
function checkedLocations(session) {
  const ids = new Set(session.checkedLocations);
  for (const id of app.client?.room?.checkedLocations ?? []) ids.add(id);
  return ids;
}

function checkPill(label, state, title) {
  const pill = document.createElement("span");
  pill.className = `chk ${state}`;
  pill.textContent = label;
  pill.title = title;
  return pill;
}

function renderChecks(session) {
  const box = el("checks");
  const mile = el("milestones");
  box.replaceChildren();
  mile.replaceChildren();

  const inSeed = seedLocations();
  const done = checkedLocations(session);
  const tiers = TIERS.slice(0, session.checksPerPhase);
  const unlocked = session.unlockedPhases;
  const cleared = session.clearedPhases;

  // Exactly one cell per column per row, or the next row's label would flow
  // into whatever space the last one left.
  // Capped rather than fixed: four tiers at a fixed 7.5rem overflow a phone
  // sideways, and minmax lets them shrink to fit instead.
  box.style.gridTemplateColumns =
    `max-content repeat(${tiers.length}, minmax(0, 7.5rem))`;

  let have = 0;
  let total = 0;

  for (let phase = 1; phase <= PHASE_COUNT; phase += 1) {
    const label = document.createElement("span");
    label.className = "chk-row-label";
    label.textContent = `Phase ${phase}`;
    if (cleared.has(phase)) label.classList.add("cleared");
    else if (!unlocked.has(phase)) label.classList.add("locked");
    box.append(label);

    for (const tier of tiers) {
      const name = phaseLocationName(phase, tier);
      const id = LOCATION_NAME_TO_ID[name];
      if (inSeed && !inSeed.has(id)) {
        // Not in this seed at all: a blank keeps the grid aligned without
        // claiming there is something there to get.
        box.append(checkPill("", "absent", `${name} is not in this seed`));
        continue;
      }
      total += 1;
      let state;
      let why;
      if (done.has(id)) {
        state = "done";
        why = `${name} -- checked`;
        have += 1;
        box.append(checkPill(`✓ ${tier}`, state, why));
        continue;
      } else if (unlocked.has(phase)) {
        state = "open";
        why = `${name} -- playable now`;
      } else {
        state = "locked";
        why = `${name} -- needs Phase ${phase} Unlocked`;
      }
      box.append(checkPill(tier, state, why));
    }
  }

  // The store's own checks count toward the total: they are locations like
  // any other, and leaving them out would make "x of y" disagree with the
  // server.
  for (let slot = 1; slot <= session.storeSlots; slot += 1) {
    const id = LOCATION_NAME_TO_ID[storeLocationName(slot)];
    if (inSeed && !inSeed.has(id)) continue;
    total += 1;
    if (done.has(id)) have += 1;
  }

  // The milestones gate on nothing but playing, so their state is a distance
  // rather than a lock: how many more hands you have to win.
  for (const hands of HANDS_WON_MILESTONES) {
    const name = milestoneLocationName(hands);
    const id = LOCATION_NAME_TO_ID[name];
    if (inSeed && !inSeed.has(id)) continue;
    total += 1;
    let state;
    let why;
    if (done.has(id)) {
      state = "done";
      why = `${name} -- checked`;
      have += 1;
      mile.append(checkPill(`✓ ${hands}`, state, why));
      continue;
    }
    state = "open";
    why = `${name} -- ${hands - session.handsWon} more hand(s) to win`;
    mile.append(checkPill(String(hands), state, why));
  }

  el("checks-summary").textContent =
    `${have} of ${total} checked` + (inSeed ? "" : " (not connected -- from your options)");
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
// The piles carry the same data-action attributes the buttons do, so drawing
// from the table and drawing from a button are the one code path.
for (const button of document.querySelectorAll("#actions button, .pile")) {
  button.addEventListener("click", () => ACTIONS[button.dataset.action]());
}

/**
 * Show or fold away the connection form.
 *
 * Folded is the resting state after a successful connect: the header is
 * sticky, so whatever it holds costs that much of every screen for the whole
 * session. "Change" brings it back.
 */
function setConnectionFormOpen(open) {
  document.querySelector("header").classList.toggle("slim", !open);
  el("edit-connection").hidden = open;
  if (open) el("slot").focus();
}

el("edit-connection").addEventListener("click", () => setConnectionFormOpen(true));

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
    status.textContent = `connected as ${el("slot").value.trim()}`;
    // The form is used once. On a phone it was eating a fifth of the screen
    // for the rest of the session, permanently, above everything you play
    // with -- so it folds away and leaves the one line worth keeping.
    setConnectionFormOpen(false);
  } catch (err) {
    status.className = "error";
    status.textContent = err.message || "connection failed";
    setConnectionFormOpen(true);
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
