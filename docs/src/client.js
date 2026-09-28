// Archipelago wiring for the browser client.
//
// Mirrors phase10/client/context.py: the session holds the game, this holds
// the socket, the UI reads both. Deliberately free of DOM so the connection
// logic can be reasoned about on its own.
//
// The save/restore ordering is the same trap as in the Python client. The
// session is rebuilt from slot data on connect, so writing the scorecard back
// before the restore lands would overwrite a real one with that empty rebuild.
// Nothing is saved until restoreState is "done".

import { Client } from "../node_modules/archipelago.js/dist/index.js?v=8612bdea";

import { GAME_NAME, MULLIGAN, PHASE_COUNT, WILD_CARD, phaseUnlock }
  from "./data.js?v=8612bdea";
import { STOCK_SKIPS } from "./cards.js?v=8612bdea";
import { Phase10Game, roundToString } from "./game.js?v=8612bdea";
import { Phase10Session } from "./session.js?v=8612bdea";
import { describeMeldCards } from "./phases.js?v=8612bdea";

/**
 * The deck a free-play run is dealt, with no Archipelago to hand items out.
 *
 * The printed game rather than a sandbox: the full eight wilds, two Skips and
 * three Mulligans -- the last two because they are the parts of this world a
 * player who never touches Archipelago would otherwise never see. No Extra
 * Draws, because free play has no draw budget for them to extend.
 */
// No Skip Cards. Those are the Archipelago item, which puts a Skip in your
// hand at the start of every round -- a handout nobody else at the table gets,
// and not how the box deals. Free play shuffles the four Skips into the draw
// pile instead (`skips_in_deck` below) and everybody is dealt ten cards off
// the same deck.
const FREE_PLAY_DECK = [
  ...Array(8).fill(WILD_CARD),
  ...Array(3).fill(MULLIGAN),
];

/** Slot data for a run with no slot. Twenty phases, three opponents. */
const FREE_PLAY_SLOT = Object.freeze({
  goal: 0,
  // No budget: a round ends when somebody empties their hand, the way the
  // printed game does, rather than when a clock the box has never heard of
  // runs down.
  starting_draws: 0,
  // The printed rule: a Skip denies the next player a turn. Archipelago keeps
  // the dig, whose clear rates its access rules are built on.
  skip_mode: "deny",
  // The four Skips the box has, shuffled in, so a hand here is ten cards off
  // the same deck everybody else is dealt from. A seed leaves this at zero and
  // grants Skips as items: that is a judgement about what an item is worth,
  // and it was quietly deciding how the printed game deals.
  skips_in_deck: STOCK_SKIPS,
  checks_per_phase: 0,
  opponents: 3,
  death_link: false,
  store_slots: 0,
});

/** Where a free-play run is kept. Per browser, per device, and nowhere else. */
const FREE_PLAY_KEY = "ap10_free_play";

/**
 * How many phases a free-play run climbs.
 *
 * Ten is the game as it comes in the box. Twenty is those ten plus the ten
 * measured to fill the gap they leave -- nothing printed clears more than
 * about two thirds of the time, so every one of them is a fight. Archipelago
 * seeds are always the full twenty; this is a free-play choice only.
 */
export const FREE_PLAY_PHASE_COUNTS = Object.freeze([10, PHASE_COUNT]);

export class Phase10Client {
  constructor({
    onUpdate = () => {}, onLog = () => {}, onMessage = () => {}, paced = false,
  } = {}) {
    this.client = new Client();
    this.session = new Phase10Session();
    this.onUpdate = onUpdate;
    this.onLog = onLog;
    // Everything the room says: items sent and received, hints, joins,
    // chat. Without it the browser client can see its own game and
    // nothing of the multiworld it is part of.
    this.onMessage = onMessage;
    //: Hold the opponents' turns for the driver to walk one at a time. The DOM
    //: client sets it so the table can be watched; nothing headless wants it.
    this.paced = paced;

    this.connected = false;
    //: Playing with no server at all. Not the same as disconnected: a
    //: free-play run has its own items, its own saves, and no checks.
    this.offline = false;
    //: How far a run climbs. Only free play moves it; a seed is always the
    //: full set, because its locations exist for every phase.
    this.phaseCap = PHASE_COUNT;
    this.restoreState = "needed";
    this.goalSent = false;

    this.#listen();
  }

  /**
   * Subscribe to the socket. Called once, from the constructor.
   *
   * Deliberately NOT done in connect(). archipelago.js never drops a listener
   * on disconnect, so registering there stacks a fresh copy on every attempt:
   * reconnect twice and the room's chat arrives in triplicate. The handlers
   * read `this.session` at call time, so they survive the session being
   * rebuilt from slot data on each connect.
   */
  #listen() {
    this.client.items.on("itemsReceived", () => this.syncItems());
    this.client.messages.on("message", (text, nodes) => this.onMessage(text, nodes));

    this.client.deathLink.on("deathReceived", (source, _time, cause) => {
      // Registered unconditionally, so it must check the option itself -- the
      // session it was registered against is not the one being played.
      if (!this.session.deathLink) return;
      this.onLog(`DeathLink from ${source}${cause ? `: ${cause}` : ""}`);
      const hand = this.session.killHand();
      if (!hand) {
        this.onLog("No hand in progress, so nothing to lose.");
        return;
      }
      // sendDeath false: settling this must not bounce a death back at
      // whoever killed us.
      this.settle(hand, { sendDeath: false });
    });

    this.client.socket.on("disconnected", () => {
      this.connected = false;
      this.onLog("Disconnected.");
      this.onUpdate();
    });
  }

  get saveKey() {
    const self = this.client.players.self;
    return `phase10_game_${self?.team ?? 0}_${self?.slot ?? 0}`;
  }

  // -- free play -----------------------------------------------------------

  /**
   * Start a run with no server, no slot and no login.
   *
   * The phases open one at a time as they are cleared, which is how the
   * printed game is played -- Archipelago's out-of-order unlocking is the
   * thing being replaced here, so restoring it as "everything at once" would
   * miss the point. Nothing is checked and nothing is sent; the run lives in
   * this browser.
   */
  async startFreePlay({ fresh = false, phases = null } = {}) {
    this.connected = false;
    this.offline = true;
    this.goalSent = false;
    if (phases) this.phaseCap = this.#validCap(phases);
    this.session = Phase10Session.fromSlotData(FREE_PLAY_SLOT, new Phase10Game());
    this.restoreState = "needed";

    if (fresh) this.#writeLocal(null);
    this.#restoreLocal();
    this.restoreState = "done";
    this.#grantFreePlayItems();
    this.onLog(`${fresh ? "New free-play run." : "Free play -- no server."} `
      + this.#whereYouAre());
    this.onUpdate();
    return this.session;
  }

  /**
   * Hand out the free-play deck, plus one phase unlock per phase cleared.
   *
   * Recomputed from the scorecard rather than accumulated, so it is right
   * after a restore without the unlocks having been saved -- and a replayed
   * phase cannot open two.
   */
  #validCap(phases) {
    const wanted = Number(phases);
    return FREE_PLAY_PHASE_COUNTS.includes(wanted) ? wanted : PHASE_COUNT;
  }

  /**
   * The phase a free-play run is up to: one past however many it has cleared.
   *
   * The one place that is decided, so the unlocks handed out and the line that
   * says where you are cannot disagree -- that line used to say "phase 1" to
   * somebody who had cleared three and reloaded the page.
   */
  #openPhase() {
    return Math.min(this.session.clearedPhases.size + 1, this.phaseCap);
  }

  /** Where a run stands, for the line printed when it opens. */
  #whereYouAre() {
    if (this.session.clearedPhases.size >= this.phaseCap) {
      return `All ${this.phaseCap} phases cleared -- start a new run when you like.`;
    }
    return `Phase ${this.#openPhase()} is open; clear it to open the next.`;
  }

  #grantFreePlayItems() {
    const open = this.#openPhase();
    const items = [...FREE_PLAY_DECK];
    for (let phase = 1; phase <= open; phase += 1) items.push(phaseUnlock(phase));
    this.session.setItems(items);
  }

  #writeLocal(payload) {
    // Storage can be absent, full, or refuse outright in a private window, and
    // none of those is a reason to stop playing.
    try {
      if (typeof localStorage === "undefined") return;
      if (payload === null) localStorage.removeItem(FREE_PLAY_KEY);
      else localStorage.setItem(FREE_PLAY_KEY,
        JSON.stringify({ ...payload, phase_cap: this.phaseCap }));
    } catch {
      /* not worth telling the player about */
    }
  }

  #restoreLocal() {
    let stored = null;
    try {
      if (typeof localStorage === "undefined") return;
      const raw = localStorage.getItem(FREE_PLAY_KEY);
      stored = raw === null ? null : JSON.parse(raw);
    } catch {
      return;
    }
    if (stored === null) return;
    // Written by this client, so a missing cap is a run from before the choice
    // existed -- which was always the full twenty.
    this.phaseCap = this.#validCap(stored.phase_cap ?? PHASE_COUNT);
    if (this.session.loadPayload(stored)) {
      const game = this.session.game;
      this.onLog(`Restored ${game.rounds.length} round(s), ${game.totalScore} points.`);
    } else {
      this.onLog("The saved run could not be read; starting a fresh one.");
    }
  }

  // -- connection ----------------------------------------------------------
  async connect(url, slotName, password = "") {
    // Omit the key entirely when there is no password. archipelago.js spreads
    // these over its defaults, so passing `password: undefined` overwrites the
    // default empty string and the login hangs until it times out -- ten
    // seconds of looking like the server is down. `|| undefined` is exactly
    // the idiom to reach for here, and exactly the wrong one.
    const options = {};
    if (password) options.password = password;

    const slotData = await this.client.login(url, slotName, GAME_NAME, options);
    // A connect after free play must not leave the local-save path armed.
    this.offline = false;

    this.session = Phase10Session.fromSlotData(slotData, new Phase10Game());
    this.goalSent = false;
    this.restoreState = "needed";
    this.connected = true;

    // Listeners are already attached (see #listen). Only the tag has to be
    // set, and only when this slot asked for it.
    if (this.session.deathLink) {
      this.client.deathLink.enableDeathLink();
    }

    this.syncItems();
    await this.restore();
    this.onLog(`Connected as ${slotName}.`);
    this.onUpdate();
    return slotData;
  }

  /**
   * Re-tally received items. Archipelago resends the full list, so this is a
   * wholesale replace rather than an increment, which makes it safe to call
   * again on reconnect.
   */
  syncItems() {
    const before = this.session.unlockedPhases;
    this.session.setItems(this.client.items.received.map((item) => item.name));
    for (const phase of this.session.unlockedPhases) {
      if (!before.has(phase)) this.onLog(`Phase ${phase} unlocked.`);
    }
    this.onUpdate();
  }

  // -- persistence ---------------------------------------------------------
  async restore() {
    this.restoreState = "requested";
    try {
      const stored = await this.client.storage.fetch(this.saveKey);
      if (this.session.loadPayload(stored)) {
        const game = this.session.game;
        this.onLog(`Restored ${game.rounds.length} round(s), ${game.totalScore} points.`);
      } else if (stored !== null && stored !== undefined) {
        this.onLog("Stored scorecard could not be read; starting a fresh one.");
      }
    } catch (err) {
      // A scorecard that will not load is not a reason to refuse to play.
      this.onLog(`Could not read the stored scorecard: ${err.message}`);
    }
    this.restoreState = "done";
    this.onUpdate();
  }

  async save() {
    if (this.restoreState !== "done") return;
    if (this.offline) {
      this.#writeLocal(this.session.toPayload());
      return;
    }
    if (!this.connected) return;
    try {
      await this.client.storage
        .prepare(this.saveKey, {})
        .replace(this.session.toPayload())
        .commit();
    } catch (err) {
      this.onLog(`Could not save the scorecard: ${err.message}`);
    }
  }

  // -- play ----------------------------------------------------------------
  startHand(phase) {
    const refusal = this.session.canPlay(phase);
    if (refusal) {
      this.onLog(refusal);
      return null;
    }
    const hand = this.session.startHand(phase, { paced: this.paced });
    this.onUpdate();
    return hand;
  }

  /**
   * Buy a store slot: report the check and save what was spent.
   *
   * No goal test, unlike settling a hand: the goal is phases cleared, and no
   * amount of buying clears one.
   */
  async buySlot(slot) {
    const id = this.session.buySlot(slot);
    if (this.connected) this.client.check(id);
    await this.save();
    this.onUpdate();
    return id;
  }

  /** Finish a hand: report its checks, save, and trip the goal if it is met. */
  /**
   * What every seat had on the table, written down before the table goes.
   *
   * The seat panels show this until the next round starts, and the round ends
   * the instant somebody goes out -- which is exactly when you want to look at
   * it. The log keeps.
   */
  #reportFinalTable() {
    const seats = this.session.seats;
    if (!seats.length) return;
    for (const seat of seats) {
      const what = seat.melds.length
        ? seat.melds.map(describeMeldCards).join("  +  ")
        : "nothing down";
      const held = seat.wentOut ? "went out" : `held ${seat.hand.length}`;
      this.onLog(`  ${seat.name} (${held}): ${what}`);
    }
  }

  async settle(hand, { sendDeath = true } = {}) {
    const died = hand.state === "failed";
    this.#reportFinalTable();
    const fresh = this.session.finishHand(hand);
    const result = this.session.lastResult;
    if (result) this.onLog(roundToString(result));

    if (fresh.length && this.connected) {
      this.client.check(...fresh);
    }
    if (this.offline) {
      const before = this.session.unlockedPhases.size;
      this.#grantFreePlayItems();
      const after = this.session.unlockedPhases.size;
      if (after > before) this.onLog(`Phase ${after} is open.`);
    }
    await this.save();

    if (died && sendDeath && this.session.deathLink && this.connected) {
      this.client.deathLink.sendDeathLink(
        this.client.players.self?.name ?? "A player",
        "ran out of draws",
      );
    }

    if (this.session.goalMet && !this.goalSent && this.connected) {
      this.client.goal();
      this.goalSent = true;
      this.onLog("Goal complete.");
    }
    this.onUpdate();
    return fresh;
  }
}
