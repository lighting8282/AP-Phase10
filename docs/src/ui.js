// DOM layer for the browser client.
//
// Same rule the Kivy tab follows: this reads session state and calls into the
// client, and holds no game state of its own. Anything it needed to remember
// would be a second copy of something the session already owns.

import { SKIP, WILD, cardFilename, isSkip, isWild, points } from "./cards.js?v=3de9109e";

//: Faces used purely as icons in the stat panel.
const SKIP_FACE = SKIP;
const WILD_FACE = WILD;
import { HAND_STATE } from "./engine.js?v=3de9109e";
import {
  HANDS_WON_MILESTONES, LOCATION_NAME_TO_ID, TIERS, milestoneLocationName,
  phaseLocationName, storeGate, storeLocationName,
} from "./data.js?v=3de9109e";
import { PHASE_COUNT, meldName, phaseDescription } from "./phases.js?v=3de9109e";
import { Phase10Client } from "./client.js?v=3de9109e";

const el = (id) => document.getElementById(id);

const app = new Phase10Client({
  onUpdate: () => render(),
  onLog: (line) => log(line),
  onMessage: (text, nodes) => logMessage(text, nodes),
  //: The opponents move one at a time here, slowly enough to be watched.
  paced: true,
});

/**
 * How long one seat's turn is left on screen.
 *
 * The three seats used to play the instant you discarded: the table simply
 * arrived in a new state, and the log explained it all at once afterwards. A
 * pause per seat is what makes those readable, and it is the only reason this
 * exists -- the engine plays the turn in no time.
 */
const OPPONENT_TURN_MS = 3000;

/**
 * How much of that pause the player wants.
 *
 * Three seconds a seat is right the first time you watch a table play and
 * long by the tenth round, and which of those you are in is not something the
 * page can know. So it is a setting, and `Off` is one of the options: somebody
 * who has read enough tables is entitled to have the turn simply happen.
 *
 * Divisors rather than milliseconds, so the one number that says how long a
 * turn is readable for stays in one place.
 */
const SPEEDS = [
  { label: "1x", times: 1, says: "normal" },
  { label: "2x", times: 2, says: "twice as fast" },
  { label: "4x", times: 4, says: "four times as fast" },
  { label: "Off", times: 0, says: "no pause at all" },
];
const SPEED_KEY = "ap10_table_speed";
//: How long the pause is checked against while it runs, so a change made
//: during one takes effect in it rather than in the next.
const SPEED_TICK_MS = 100;

let speedIndex = 0;

//: Walking the opponents' turns. The table is mid-move while this is set, so
//: everything the player could touch is held shut until it clears.
let pacing = false;
//: The seat whose turn is being shown, so the table can say whose it is.
let activeSeat = null;
//: A Skip the player has asked to throw away, held until they say it twice.
//: Cleared by any move that lands, so it never survives the turn it was armed
//: on. By identity, not index: a draw renumbers the hand.
let armedSkip = null;
//: Whether the seat being shown is about to miss its turn rather than take
//: one. Decided before the turn happens, because afterwards the flag that said
//: so has been consumed.
let activeMissed = false;
//: Every card added to a group since your last move, and who added it. Cards
//: are the key, a seat index (or "you") the value, so a group can say both
//: that it grew and who grew it.
//:
//: It holds the whole of the table's turn rather than one seat's, and clears
//: when you next act. Per seat it lasted about three seconds -- the mark was
//: gone before anybody looked at it, which is the same as not marking at all.
//: Cleared on your move rather than by a timer, so you have exactly as long as
//: you want to read the table.
let justHit = new Map();
//: Whether the walk now running is one you are sitting out. The flag on the
//: hand is consumed the moment the turn is lost, so by the time anything is
//: drawn it is already false; this is read off turnsMissed instead.
let missingTurn = false;
//: turnsMissed as it stood before the move just made, so a rise in it can be
//: told from a count that was already there.
let missedBefore = 0;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Wait out one seat's turn at whatever speed is currently set.
 *
 * In slices rather than one sleep, because the moment somebody wants this
 * faster is the moment they are sat watching a pause -- and a single timer
 * started at the old speed would make them sit through that one first. Each
 * slice re-reads the setting, so turning it up shortens the pause already
 * running, and `Off` ends it on the spot.
 */
async function pauseForTurn() {
  let waited = 0;
  for (;;) {
    const { times } = SPEEDS[speedIndex];
    if (times === 0 || waited >= OPPONENT_TURN_MS / times) return;
    await sleep(SPEED_TICK_MS);
    waited += SPEED_TICK_MS;
  }
}

//: Rooms can be chatty and this feed never scrolls away on its own.
const MAX_LOG_LINES = 300;

function appendLine(node) {
  const box = el("log");
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  // Only the newest line is marked: with the feed scrolled up, "what just
  // happened" is otherwise indistinguishable from what happened ten turns ago.
  for (const stale of box.querySelectorAll(".line.latest")) stale.classList.remove("latest");
  node.classList.add("latest");
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
    // null is "no budget", which is free play. A number here would be a
    // lie, and a large one would look like a countdown that never moves.
    box.append(hand.drawsLeft === null
      ? iconTile(ICON_DRAW, "∞", "draws -- no limit")
      : iconTile(ICON_DRAW, hand.drawsLeft, "draws left",
        hand.drawsLeft === 0 ? "spent" : ""));
    box.append(iconTile(ICON_STOCK, hand.stock.length, "in the stock"));
    // The discard's icon is the card itself: what is on top is the whole
    // point of looking, and a generic pile symbol would say nothing.
    box.append(cardTile(hand.discardTop, hand.discardTop ? describe(hand.discardTop) : "empty",
      "on the discard", "wide"));
    box.append(cardTile(SKIP_FACE, hand.skipsInHand,
      session.skipMode === "deny" ? "skips - deny a turn" : "skips in hand"));
    box.append(cardTile(WILD_FACE, hand.config.wildsInDeck, "wilds in the deck"));
  } else {
    const c = session.config;
    box.append(c.maxDraws <= 0
      ? iconTile(ICON_DRAW, "∞", "draws -- no limit")
      : iconTile(ICON_DRAW, c.maxDraws, "draws per hand"));
    box.append(iconTile(ICON_STOCK, c.handSize, "cards dealt"));
    // Two ways a Skip reaches you, and the tile has to say which. Free play
    // shuffles them into the deck like the box does, so "skips per hand" in
    // front of a zero would read as a game with no Skips in it at all.
    box.append(c.skipsInDeck
      ? cardTile(SKIP_FACE, c.skipsInDeck, "skips in the deck")
      : cardTile(SKIP_FACE, c.startingSkips, "skips per hand"));
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
  if (pacing || !hand || hand.state !== HAND_STATE.IN_PROGRESS) return;
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
  // Yours is marked the same way theirs is, and added to what the table did
  // rather than replacing it. Hitting is the one move whose result lands
  // somewhere other than your own hand, so it is the hardest to see you made.
  justHit.set(playable[0], "you");
  log(`You play ${describe(playable[0])} onto the table.`);
  reportTable();
  afterPlayerAction(hand);
}

/**
 * Read out what the seats did since anybody last looked.
 *
 * Drained rather than replayed, so a redraw cannot print the same turn twice.
 */
function reportTable() {
  const table = app.session.table;
  if (!table) return;
  for (const [who, what] of table.drainLog()) log(`${who} ${what}`);
}

/**
 * Walk the opponents' turns, one seat at a time.
 *
 * The engine has not moved them yet -- a paced hand queues them and hands them
 * over here. Each pass names the seat, waits, plays it and then drains what it
 * said, so a player who looks away for a second can read back what happened
 * rather than guessing from a table that changed all at once.
 *
 * The log is drained per seat rather than once at the end, which is the whole
 * point: the lines have to arrive beside the pause they belong to.
 *
 * Every pass re-checks that this hand is still the one being played. The walk
 * spans real seconds, and starting a new free-play run is possible throughout
 * them -- so without the check the seats of an abandoned hand would play on,
 * write into the new run's log and settle a round it never had.
 */
async function runOpponentTurns(hand) {
  if (pacing) return;
  const current = () => app.session.hand === hand;
  // The table is about to move, so the last round of marks has been seen.
  // Cleared here rather than on your own move: a hit and the discard that
  // follows it are one turn, and clearing on the discard would erase the mark
  // on the card you had just played, in the same breath as playing it.
  justHit.clear();
  pacing = true;
  try {
    while (hand.turnPending && current()) {
      // Whose turn it is, before anything of theirs moves.
      [activeSeat] = hand.pendingSeats;
      // Read now: playSeat consumes the flag, so after the turn there is no
      // way left to tell a seat that missed from one that played.
      activeMissed = activeSeat.skipped;
      render();
      // What each group held before the turn, so what it gains can be marked.
      // Per meld rather than one flat set: a group that did not exist before is
      // a lay-down, and marking all six of its cards as hits would say the
      // wrong thing.
      const before = new Map(
        hand.table.allMelds().map((meld) => [meld, new Set(meld.cards)]),
      );
      await pauseForTurn();
      if (!current()) break;
      const seat = hand.stepOpponent();
      if (seat === null) break;
      activeSeat = seat;
      // Added to, not added by: a seat can hit onto anybody's group, so what
      // is recorded is who played the card rather than whose group it landed
      // in. Accumulated across the walk, so a card Ada played is still marked
      // when Cy has finished playing.
      const who = hand.table.seats.indexOf(seat);
      for (const meld of hand.table.allMelds()) {
        const had = before.get(meld);
        if (!had) continue;
        for (const card of meld.cards) if (!had.has(card)) justHit.set(card, who);
      }
      // A turn a Skip took off you is spent inside this walk, at the end of the
      // round the Skip was thrown in -- not before it started. So the banner
      // lights up here rather than up front, and it stays lit for the second
      // pass, which is otherwise the seats going round twice for no reason.
      missingTurn = hand.turnsMissed > missedBefore;
      reportTable();
      render();
    }
  } finally {
    pacing = false;
    activeSeat = null;
    activeMissed = false;
    missingTurn = false;
  }
  render();
  if (current() && hand.state !== HAND_STATE.IN_PROGRESS) await settle(hand);
}

/**
 * Hand the turn over: let the table play if it is owed a turn, otherwise
 * settle a round that has just ended.
 */
function afterPlayerAction(hand) {
  // Any move that lands disarms the Skip: the second click has to be the very
  // next thing you do, or it is not a confirmation of anything.
  armedSkip = null;
  // A turn already gone before the walk starts -- which is only the unpaced
  // path, since a seat throws its Skip during the walk. runOpponentTurns keeps
  // this up to date from there.
  missingTurn = hand.turnsMissed > missedBefore;
  render();
  if (hand.turnPending) {
    runOpponentTurns(hand);
    return;
  }
  missingTurn = false;
  if (hand.state !== HAND_STATE.IN_PROGRESS) settle(hand);
}

function withHand(fn) {
  // Mid-pause the table is part-way through its turn, so a click now would
  // play out of order. The controls are disabled as well; this is the guard for
  // anything that reaches here another way.
  if (pacing) return;
  const hand = app.session.hand;
  if (!hand || hand.state !== HAND_STATE.IN_PROGRESS) {
    log("No hand in progress -- pick a phase first.");
    return;
  }
  // Read before the move, because a turn taken off you is lost and counted
  // inside it -- afterwards there is nothing left to compare against.
  missedBefore = hand.turnsMissed;
  try {
    fn(hand);
  } catch (err) {
    log(err.message);
    reportTable();
    return;
  }
  reportTable();
  afterPlayerAction(hand);
}

function mulligan() {
  if (pacing) return;
  const refusal = app.session.canMulligan();
  if (refusal) {
    log(refusal);
    return;
  }
  app.session.useMulligan();
  log(`Mulligan spent -- fresh hand. ${app.session.mulligansLeft} left.`);
  render();
}

/**
 * Lay the phase down, asking what the wilds are when it matters.
 *
 * One option means there is nothing to ask: the wild can only be one thing,
 * or there is no wild at all. More than one and the choice is real -- a run of
 * 4 from `W 4 5 6` is 3-4-5-6 or 4-5-6-7, and those take different cards
 * afterwards -- so the player picks instead of the solver.
 */
function layDown() {
  const hand = app.session.hand;
  if (!hand || hand.state !== HAND_STATE.IN_PROGRESS) {
    log("No hand in progress -- pick a phase first.");
    return;
  }
  const options = hand.layDownOptions();
  if (!options.length) {
    log(`Phase ${hand.phase} is not satisfiable from your hand yet.`);
    return;
  }
  if (options.length === 1) {
    withHand((h) => h.layDown(options[0]));
    return;
  }
  renderLayChoice(options);
}

function renderLayChoice(options) {
  const box = el("lay-options");
  box.replaceChildren();
  for (const option of options) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = option.description;
    button.addEventListener("click", () => {
      el("lay-choice").hidden = true;
      withHand((h) => h.layDown(option));
    });
    box.append(button);
  }
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "cancel";
  cancel.textContent = "Not yet";
  cancel.addEventListener("click", () => {
    el("lay-choice").hidden = true;
    render();
  });
  box.append(cancel);
  el("lay-choice").hidden = false;
  el("lay-choice").scrollIntoView({ block: "nearest" });
}

const ACTIONS = {
  draw: () => withHand((hand) => hand.draw(false)),
  "draw-discard": () => withHand((hand) => hand.draw(true)),
  lay: () => layDown(),
  skip: () => withHand((hand) => hand.playSkip()),
  mulligan: () => mulligan(),
};

// -- rendering ---------------------------------------------------------------
function render() {
  const s = app.session;
  const hand = s.hand;

  const won = s.runOver ? s.runWinner : null;
  el("summary").textContent = won
    // A finished run is not a round count any more. The line that mattered
    // while it ran is the wrong thing to keep reading once it is decided.
    ? `${won.name === "You" ? "You won" : `${won.name} won`} - ${won.score} pts - `
      + `${s.game.rounds.length} rounds - cleared ${s.clearedPhases.size}/${s.phaseCap}`
    : `Round ${s.game.roundNumber} - score ${s.totalScore} (lower is better) - `
      + `won ${s.handsWon} - cleared ${s.clearedPhases.size}/${app.phaseCap}`
      + (s.scoreReduction ? ` - ${s.scoreReduction} reduced` : "");

  if (hand) {
    el("objective").textContent = `Phase ${hand.phase}: ${phaseDescription(hand.phase)}`;
  } else if (won) {
    el("objective").textContent = won.name === "You"
      ? `You finished phase ${s.phaseCap} on the lowest score. Start a new run below.`
      : `${won.name} finished phase ${s.phaseCap} first. Start a new run below.`;
  } else {
    el("objective").textContent = "No round in progress -- pick a phase below.";
  }
  renderStats(s, hand);

  // Your turn is marked the same way theirs is, on the same badge, so "whose
  // turn is it" is one question with one answer rather than two halves.
  const yourTurn = Boolean(hand) && hand.state === HAND_STATE.IN_PROGRESS && !pacing;
  document.querySelector(".you.seat").classList.toggle("turn", yourTurn);
  // Every seat says whether it is playing or sitting out; yours said nothing,
  // so a turn taken off you looked like the table going round twice.
  el("you-what").textContent = !hand ? ""
    : missingTurn ? "missing a turn"
      : yourTurn ? "your turn"
        : pacing ? "waiting"
          : "";
  el("you-phase").textContent = hand ? `phase ${hand.phase}` : "";
  // Your own total in the same place as theirs: a scoreboard split across two
  // parts of the page is one you have to assemble before you can read it.
  el("you-score").textContent = `${s.totalScore} pts`;
  // What you are building, beside the cards you are building it from.
  el("you-needs").textContent = hand ? phaseDescription(hand.phase) : "";

  renderTable(s);
  renderMiddle(hand);
  renderOwnMelds(hand);
  renderHand(hand);
  renderDig(hand);
  renderDeny(hand);
  renderPhases(s);
  if (!hand || hand.laid || hand.state !== HAND_STATE.IN_PROGRESS) {
    el("lay-choice").hidden = true;
  }
  renderPhaseHelp(s);
  renderStore(s);
  renderChecks(s);

  for (const button of document.querySelectorAll("#actions button")) {
    button.disabled = pacing || !hand || hand.state !== HAND_STATE.IN_PROGRESS;
  }
  // The button is the dig, and only a seed digs. Where a Skip denies a turn it
  // is played by being discarded, so there is no separate move to offer and a
  // button here could only compete with the card itself.
  const skip = el("skip-button");
  skip.hidden = s.skipMode === "deny";
  skip.title = "Look at the top three of the stock and keep one";
  // A dig is a turn of its own, so it is only there before you draw, only with
  // a Skip to spend, and only with a stock to dig into. Left enabled it was a
  // button whose whole function was to explain, afterwards, that it could not
  // be pressed.
  if (!skip.disabled) {
    skip.disabled = !hand.skipsInHand || hand.drewThisTurn
      || hand.digPending || hand.stock.length === 0;
  }

  // Narrower than the rest: a Mulligan needs a copy in hand and an untouched
  // deal, so it stays disabled even mid-hand.

  const mull = el("mulligan-button");
  mull.disabled = pacing || s.canMulligan() !== null;
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
/** Who played a card, as a name: a seat index, or "you". */
function whoPlayed(who) {
  return who === "you" ? "you" : app.session.seatName(who);
}

function meldNode(meld) {
  const hand = app.session.hand;
  const live = Boolean(hand) && hand.state === HAND_STATE.IN_PROGRESS && !pacing
    && hand.laid && hand.hand.some((c) => meld.accepts(c));

  const node = document.createElement(live ? "button" : "div");
  node.className = live ? "meld live" : "meld";
  if (live) {
    node.title = `Play a card onto this ${meldName(meld)}`;
    node.addEventListener("click", () => hitMeld(meld));
  }

  // What the group is, over the cards in it. Two groups of three at this size
  // are six cards in a row: the outline alone never said where one ended, and
  // "set of 11s" is the half you need to know whether your spare 11 fits.
  const name = document.createElement("span");
  name.className = "meld-name";
  name.textContent = meldName(meld);
  node.append(name);

  const row = document.createElement("span");
  row.className = "meld-cards";
  const added = [];
  for (const card of meld.cards) {
    const img = document.createElement("img");
    img.src = `assets/cards/${cardFilename(card)}`;
    img.alt = describe(card);
    // Cards played onto this group since the table last started moving, ringed
    // in the colour of whoever played them. A group that grew by one between
    // two redraws is otherwise a group that looks the same, and the colour
    // answers "who" without reading the log on the far side of the page.
    if (justHit.has(card)) {
      const who = justHit.get(card);
      img.classList.add("hit", who === "you" ? "by-you" : `by-${who + 1}`);
      img.alt = `${describe(card)} -- just played by ${whoPlayed(who)}`;
      added.push(who);
    }
    row.append(img);
  }
  node.append(row);

  // Said as well as shown. Colour alone would leave the one thing you most
  // need to notice resting on telling four similar rings apart.
  if (added.length) {
    const grew = document.createElement("span");
    grew.className = "meld-grew";
    const names = [...new Set(added.map(whoPlayed))];
    grew.textContent = `+${added.length} ${names.join(" & ")}`;
    name.append(" ", grew);
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
    // Whose turn it is, said where the turn is happening rather than only in
    // the log: the log is on the other side of the page.
    if (seat === activeSeat) div.classList.add("turn");

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

    const needs = document.createElement("div");
    needs.className = "needs";
    needs.textContent = phaseDescription(seat.phase);

    const what = document.createElement("div");
    what.className = "what";
    if (seat === activeSeat && !seat.wentOut) {
      // A seat denied a turn is sitting it out, not playing it. Saying
      // "playing..." for three seconds and then "misses a turn" in the log was
      // the table contradicting itself.
      what.textContent = activeMissed ? "misses a turn" : "playing...";
    } else if (seat.wentOut) what.textContent = "went out";
    else if (seat.laidDown) what.textContent = `down - ${seat.hand.length} left to shed`;
    else what.textContent = `building - ${seat.hand.length} cards`;

    div.append(who, needs, what);

    // Where its cards went. A seat goes out with eight of the ten it was
    // dealt showing, and the two that are missing are on the discard pile
    // under everything thrown since -- which is not somewhere you can count.
    // The sum is spelled out rather than implied, because the question it
    // answers is arithmetic.
    const tally = document.createElement("div");
    tally.className = "tally";
    // The hand's own config, not the session's: an item arriving mid-round
    // changes what the next deal will be, not what this one was.
    const dealt = session.hand?.config?.handSize ?? 0;
    tally.textContent = `${dealt} dealt + ${seat.drew} drawn = `
      + `${seat.placed} down + ${seat.hand.length} held + ${seat.threw} thrown`;
    // Wrong is worse than absent: if this ever stops adding up, say nothing
    // rather than print a sum that does not.
    if (dealt + seat.drew === seat.placed + seat.hand.length + seat.threw) {
      div.append(tally);
    }

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
  const live = Boolean(hand) && hand.state === HAND_STATE.IN_PROGRESS && !pacing;
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
  // Said first: while the table is moving, nothing else on this line is true.
  if (pacing) {
    const who = activeSeat ? `${activeSeat.name} is playing` : "the table is playing";
    return missingTurn ? `* ${who} -- you are missing a turn *` : `* ${who} *`;
  }
  // A finished run has no phase to pick, so inviting one is an instruction
  // that cannot be followed.
  if (app.session.runOver) return "* The run is over -- start a new one below *";
  if (!hand) return "* Pick a phase below to start a round *";
  if (!live) return "* The round is over *";
  if (hand.digPending) return "* Keep one of the dug cards *";
  if (hand.denyPending) return "* Say who misses their turn *";
  if (!drawn) return "* Draw or pick up a card *";
  return "* Play what you can, then discard a card *";
}

/** Whether a Skip is played by being discarded, rather than dug with. */
const skipDenies = () => app.session.skipMode === "deny";

/**
 * Click a card in your hand.
 *
 * What a Skip does depends on the seed, and so does what the click means.
 *
 * Denying, the printed rule: the Skip *is* the discard, so clicking it throws
 * it and then asks who loses a turn. Nothing to warn about -- that is the card
 * doing its job, and it is the click a player wants.
 *
 * Digging, an Archipelago seed: the dig is a whole turn and so only happens
 * before you draw. After the draw the only thing left to do with a Skip is
 * throw it away for nothing, fifteen points with it, which is almost never
 * what the click meant -- so there it takes a second click.
 */
function playFromHand(index) {
  const hand = app.session.hand;
  if (pacing || !hand || hand.state !== HAND_STATE.IN_PROGRESS) return;
  const card = hand.hand[index];

  if (isSkip(card) && !skipDenies()) {
    if (!hand.drewThisTurn) {
      withHand((h) => h.playSkip());
      return;
    }
    if (armedSkip !== card) {
      armedSkip = card;
      log("A Skip digs three cards down the stock -- click it again to throw it away.");
      render();
      return;
    }
  }
  withHand((h) => h.discardCard(h.hand[index]));
}

function renderHand(hand) {
  const box = el("hand");
  box.replaceChildren();
  if (!hand) return;
  const denies = skipDenies();
  hand.hand.forEach((card, index) => {
    const button = cardButton(card, () => playFromHand(index));
    // Your cards are not playable while the table is mid-turn.
    button.disabled = pacing || hand.denyPending;
    if (isSkip(card)) {
      if (denies) {
        // Always the good click here: throwing it is how it is played, and
        // you choose who loses the turn afterwards.
        button.classList.add("playable");
        button.title = hand.drewThisTurn
          ? "Discard it and choose who misses their turn"
          : "Draw first, then discard this to make somebody miss a turn";
      } else if (!hand.drewThisTurn) {
        button.classList.add("playable");
        button.title = "Dig: look three cards down the stock and keep one";
      } else if (card === armedSkip) {
        button.classList.add("armed");
        button.title = "Click again to throw this Skip away";
      } else {
        button.title = "A Skip is for digging -- clicking it twice throws it away";
      }
    }
    box.append(button);
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

/**
 * Pick who loses a turn, after a Skip has been discarded.
 *
 * The choice is the player's, which is the printed rule and the reason a Skip
 * is worth holding: the seat about to go out is rarely the seat whose turn
 * comes next. Each button says what that seat is doing, because "deny Ada" is
 * not a decision until you know Ada is one card from going out.
 */
function renderDeny(hand) {
  const wrap = el("deny");
  const box = el("deny-seats");
  box.replaceChildren();
  if (!hand || !hand.denyPending) {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;
  hand.pendingDeny.forEach((seat, index) => {
    const button = document.createElement("button");
    button.className = "deny-seat";
    const name = document.createElement("strong");
    name.textContent = seat.name;
    const what = document.createElement("span");
    what.textContent = seat.laidDown
      ? ` - down, ${seat.hand.length} left to shed`
      : ` - building, ${seat.hand.length} cards`;
    button.append(name, what);
    button.addEventListener("click", () => withHand((h) => {
      const target = h.denySeat(index);
      log(`${target.name} will miss a turn.`);
    }));
    box.append(button);
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

/**
 * Free play has no server, so it has no checks and no store.
 *
 * Both panels would otherwise sit there listing things that can never be
 * taken -- a check list where nothing is checkable is worse than no list.
 */
function apPanelsVisible() {
  return !app.offline;
}

function renderStore(session) {
  const box = el("store");
  const summary = el("store-summary");
  box.replaceChildren();

  // A seed with no store loses the whole section rather than keeping a
  // heading over an explanation of why there is nothing under it.
  const slots = session.storeSlots;
  el("store-wrap").hidden = !slots || !apPanelsVisible();
  if (el("store-wrap").hidden) return;

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

  el("checks-wrap").hidden = !apPanelsVisible();
  if (!apPanelsVisible()) return;

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

/**
 * Every phase and what it needs, without hovering anything.
 *
 * The phase buttons carry a `title`, which is invisible on a touch screen --
 * so on a phone there was no way at all to find out what phase 14 wanted
 * before committing to it. Collapsed by default because it is twenty rows;
 * the open/closed choice is remembered per browser.
 */
const PHASE_HELP_KEY = "ap10_phase_help_open";
const RULES_KEY = "ap10_rules_open";

function renderPhaseHelp(session) {
  const box = el("phase-help-list");
  box.replaceChildren();
  const unlocked = session.unlockedPhases;
  const playing = session.hand ? session.hand.phase : null;

  for (let phase = 1; phase <= app.phaseCap; phase += 1) {
    const state = phase === playing ? "now"
      : session.clearedPhases.has(phase) ? "done"
      : unlocked.has(phase) ? "open" : "";
    const n = document.createElement("span");
    n.className = `ph-n ${state}`.trim();
    n.textContent = `${phase}.`;
    const w = document.createElement("span");
    w.className = `ph-w ${state}`.trim();
    w.textContent = phaseDescription(phase);
    // The state is a colour, so it needs saying as well as showing.
    const why = phase === playing ? " -- playing now"
      : session.clearedPhases.has(phase) ? " -- cleared"
      : unlocked.has(phase) ? " -- open" : " -- locked";
    n.title = `Phase ${phase}${why}`;
    w.title = n.title;
    box.append(n, w);
  }
}

function renderPhases(session) {
  const box = el("phases");
  box.replaceChildren();
  const unlocked = session.unlockedPhases;
  // The run's own length: a ten-phase free-play run should not show ten
  // buttons that can never light up.
  for (let phase = 1; phase <= app.phaseCap; phase += 1) {
    const button = document.createElement("button");
    button.textContent = String(phase);
    button.title = phaseDescription(phase);
    if (session.clearedPhases.has(phase)) button.classList.add("cleared");
    else if (unlocked.has(phase)) button.classList.add("open");
    button.disabled = !unlocked.has(phase) || Boolean(session.hand) || session.runOver;
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

{
  const rules = el("how-to-play");
  try {
    // Open the first time: somebody who has just clicked "Just play" is
    // exactly who needs it, and they have no way to know it is there.
    rules.open = localStorage.getItem(RULES_KEY) !== "0";
  } catch {
    rules.open = false;
  }
  rules.addEventListener("toggle", () => {
    try {
      localStorage.setItem(RULES_KEY, rules.open ? "1" : "0");
    } catch {
      /* nothing to do about it */
    }
  });
}

{
  const help = el("phase-help");
  try {
    help.open = localStorage.getItem(PHASE_HELP_KEY) === "1";
  } catch {
    /* a private window is not a reason to fail to draw the page */
  }
  help.addEventListener("toggle", () => {
    try {
      localStorage.setItem(PHASE_HELP_KEY, help.open ? "1" : "0");
    } catch {
      /* nothing to do about it */
    }
  });
}

// How fast the table plays. A cycle rather than a menu: the tap that wants it
// is made mid-pause, with a turn running, and picking from a list is three
// interactions where this is one. The button never goes dark with the rest of
// the controls -- being able to speed the table up while it is the table's
// turn is the entire point of it.
{
  const button = el("speed");
  const show = () => {
    const { label, says } = SPEEDS[speedIndex];
    button.textContent = `Speed ${label}`;
    button.setAttribute("aria-label", `Table speed: ${says}. Press to change.`);
  };
  try {
    const saved = SPEEDS.findIndex((s) => s.label === localStorage.getItem(SPEED_KEY));
    if (saved >= 0) speedIndex = saved;
  } catch {
    /* a private window is not a reason to fail to draw the page */
  }
  button.addEventListener("click", () => {
    speedIndex = (speedIndex + 1) % SPEEDS.length;
    show();
    try {
      // Stored by name rather than by position, so reordering or adding a
      // speed later cannot silently turn somebody's saved choice into a
      // different one.
      localStorage.setItem(SPEED_KEY, SPEEDS[speedIndex].label);
    } catch {
      /* nothing to do about it */
    }
  });
  show();
}

// -- free play ---------------------------------------------------------------
async function startFreePlay(fresh, phases = null) {
  const status = el("status");
  await app.startFreePlay({ fresh, phases });
  status.className = "free";
  status.textContent = "free play - no server";
  setConnectionFormOpen(false);
  el("free-play-controls").hidden = false;
  for (const button of document.querySelectorAll("#free-play-controls .new-run")) {
    button.classList.toggle("current", Number(button.dataset.phases) === app.phaseCap);
  }
  render();
}

el("free-play").addEventListener("click", () => startFreePlay(false));
for (const button of document.querySelectorAll("#free-play-controls .new-run")) {
  button.addEventListener("click", () => {
    // Deliberately confirmed: it throws away a scorecard that only exists
    // here, with nothing on a server to restore it from.
    if (!globalThis.confirm?.("Start a new run? The current scorecard is lost.")) return;
    startFreePlay(true, Number(button.dataset.phases));
  });
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
    status.textContent = `connected as ${el("slot").value.trim()}`;
    // Connecting after a free-play run takes its controls away with it.
    el("free-play-controls").hidden = true;
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

// -- the tutorial ------------------------------------------------------------
// Six steps that point at the page rather than describing it. Everything it
// highlights is a real element, so it cannot drift out of date the way a
// screenshot in a README does -- if a step's element is not on screen, the
// step is skipped rather than pointing at nothing.

const TUTORIAL = [
  {
    target: ".felt",
    title: "This is the table",
    text: "Three computer players sit across from you, and you are at the "
      + "bottom. Everyone is racing to empty their hand.",
  },
  {
    target: "#you-needs",
    title: "What you are building",
    text: "Your phase is written above your cards -- \u201cset of 3 + set of "
      + "3\u201d means two groups of three matching numbers. Colours do not "
      + "matter for a set.",
  },
  {
    target: "#stock-pile",
    title: "Start your turn by drawing",
    text: "Click the face-down pile to draw the top card, or the face-up one "
      + "to take what somebody threw away.",
  },
  {
    target: '#actions button[data-action="lay"]',
    title: "Lay your phase down",
    text: "The moment your hand contains the whole phase, put it on the table. "
      + "If a wild could stand for more than one card, you choose which.",
  },
  {
    target: "#table",
    title: "Then play onto anything",
    text: "Once your own phase is down you can add spare cards to any group on "
      + "the table, including theirs. A run takes either end; a set takes its "
      + "own number.",
  },
  {
    target: "#speed",
    title: "And set how fast they play",
    text: "The three of them take their turns one at a time so you can see "
      + "what each one did. Press this to run them faster, or to drop the "
      + "pause altogether -- it works while they are playing, too.",
  },
  {
    target: "#hand",
    title: "End your turn by discarding",
    text: "Click any card in your hand to throw it. Shed your last card and "
      + "you have gone out -- the round ends and everyone else counts what "
      + "they are still holding.",
  },
  {
    target: "#phases",
    title: "Then pick the next phase",
    text: "They open one at a time as you clear them. The two "
      + "links underneath say what each phase needs and how everything works.",
  },
];

//: Elements that draw nothing of their own, so the dimming would show through
//: them if they were merely lifted above it.
const TUT_SOLID = new Set(["#you-needs", "#hand", "#phases", "#table"]);

let tutorialAt = 0;
let tutorialSteps = [];

function tutorialTarget(step) {
  const node = document.querySelector(step.target);
  if (!node) return null;
  const box = node.getBoundingClientRect();
  // Zero-sized means hidden or empty -- an empty table before a round starts,
  // for instance. Nothing to point at, so the step does not run.
  return box.width > 0 && box.height > 0 ? node : null;
}

function clearTutorialHighlight() {
  for (const node of document.querySelectorAll(".tut-lit")) {
    node.classList.remove("tut-lit", "tut-solid");
  }
}

function placeTutorialBox(node) {
  const box = el("tutorial-box");
  const target = node.getBoundingClientRect();
  const width = box.offsetWidth;
  const height = box.offsetHeight;
  const margin = 12;

  // Below the element if it fits, above if it does not -- and then clamped to
  // both edges, not just the bottom one. Clamping only the bottom put the box
  // at top: -1411 on a phone, where the element it points at can be far above
  // the fold at the moment it is measured.
  let top = target.bottom + margin;
  if (top + height > window.innerHeight - margin) top = target.top - height - margin;
  top = Math.max(margin, Math.min(top, window.innerHeight - height - margin));

  let left = target.left + target.width / 2 - width / 2;
  left = Math.max(margin, Math.min(left, window.innerWidth - width - margin));

  box.style.top = `${Math.round(top)}px`;
  box.style.left = `${Math.round(left)}px`;
}

function showTutorialStep(index) {
  tutorialAt = Math.max(0, Math.min(index, tutorialSteps.length - 1));
  const step = tutorialSteps[tutorialAt];
  clearTutorialHighlight();

  const node = tutorialTarget(step);
  if (node) {
    node.classList.add("tut-lit");
    if (TUT_SOLID.has(step.target)) node.classList.add("tut-solid");
    // Instant, not smooth: the box is placed from the element's position, and
    // a scroll still in flight is a position that is about to be wrong.
    node.scrollIntoView({ block: "center", behavior: "auto" });
  }

  el("tutorial-step").textContent = `${tutorialAt + 1} of ${tutorialSteps.length}`;
  el("tutorial-title").textContent = step.title;
  el("tutorial-text").textContent = step.text;
  el("tutorial-back").disabled = tutorialAt === 0;
  el("tutorial-next").textContent =
    tutorialAt === tutorialSteps.length - 1 ? "Finish" : "Next";

  // Placed straight away, because requestAnimationFrame does not fire in a
  // background tab and a box that waits for a frame that never comes stays in
  // the corner. The extra frame is for the case where the text has just
  // changed the box's height.
  if (node) {
    placeTutorialBox(node);
    requestAnimationFrame(() => placeTutorialBox(node));
  }
}

function startTutorial() {
  tutorialSteps = TUTORIAL.filter((step) => tutorialTarget(step));
  if (!tutorialSteps.length) {
    log("Nothing to show yet -- start a round first.");
    return;
  }
  el("tutorial").hidden = false;
  showTutorialStep(0);
}

function endTutorial() {
  clearTutorialHighlight();
  el("tutorial").hidden = true;
}

el("start-tutorial").addEventListener("click", () => startTutorial());
el("tutorial-next").addEventListener("click", () => {
  if (tutorialAt === tutorialSteps.length - 1) endTutorial();
  else showTutorialStep(tutorialAt + 1);
});
el("tutorial-back").addEventListener("click", () => showTutorialStep(tutorialAt - 1));
el("tutorial-done").addEventListener("click", () => endTutorial());
// Clicking the dimmed page closes it, but clicking the box must not.
el("tutorial").addEventListener("click", (event) => {
  if (event.target === el("tutorial")) endTutorial();
});
document.addEventListener("keydown", (event) => {
  if (el("tutorial").hidden) return;
  if (event.key === "Escape") endTutorial();
  if (event.key === "ArrowRight") showTutorialStep(tutorialAt + 1);
  if (event.key === "ArrowLeft") showTutorialStep(tutorialAt - 1);
});
window.addEventListener("resize", () => {
  if (el("tutorial").hidden) return;
  const node = document.querySelector(".tut-lit");
  if (node) placeTutorialBox(node);
});

// Exposed deliberately: it is what the browser test harness drives, and it
// lets a player inspect their own state from the console. Read-only in
// practice -- every mutation still goes through the client.
globalThis.phase10 = app;

render();
