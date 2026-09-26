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

import { Client } from "../node_modules/archipelago.js/dist/index.js";

import { EXTRA_DRAW, GAME_NAME, MULLIGAN, PHASE_COUNT, SKIP_CARD, WILD_CARD, phaseUnlock }
  from "./data.js";
import { Phase10Game, roundToString } from "./game.js";
import { Phase10Session } from "./session.js";

/**
 * The deck a free-play run is dealt, with no Archipelago to hand items out.
 *
 * Chosen to be the printed game rather than a sandbox: the full eight wilds,
 * and four Extra Draws on top of the four a hand starts with -- eight total,
 * which is the point past which more draws were measured to buy nothing. Two
 * Skips and three Mulligans because they are the parts of this world that a
 * player who never touches Archipelago would otherwise never see.
 */
const FREE_PLAY_DECK = [
  ...Array(8).fill(WILD_CARD),
  ...Array(4).fill(EXTRA_DRAW),
  ...Array(2).fill(SKIP_CARD),
  ...Array(3).fill(MULLIGAN),
];

/** Slot data for a run with no slot. Twenty phases, three opponents. */
const FREE_PLAY_SLOT = Object.freeze({
  goal: 0,
  starting_draws: 4,
  checks_per_phase: 0,
  opponents: 3,
  death_link: false,
  store_slots: 0,
});

/** Where a free-play run is kept. Per browser, per device, and nowhere else. */
const FREE_PLAY_KEY = "ap10_free_play";

export class Phase10Client {
  constructor({ onUpdate = () => {}, onLog = () => {}, onMessage = () => {} } = {}) {
    this.client = new Client();
    this.session = new Phase10Session();
    this.onUpdate = onUpdate;
    this.onLog = onLog;
    // Everything the room says: items sent and received, hints, joins,
    // chat. Without it the browser client can see its own game and
    // nothing of the multiworld it is part of.
    this.onMessage = onMessage;

    this.connected = false;
    //: Playing with no server at all. Not the same as disconnected: a
    //: free-play run has its own items, its own saves, and no checks.
    this.offline = false;
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
  async startFreePlay({ fresh = false } = {}) {
    this.connected = false;
    this.offline = true;
    this.goalSent = false;
    this.session = Phase10Session.fromSlotData(FREE_PLAY_SLOT, new Phase10Game());
    this.restoreState = "needed";

    if (fresh) this.#writeLocal(null);
    this.#restoreLocal();
    this.restoreState = "done";
    this.#grantFreePlayItems();
    this.onLog(
      fresh
        ? "New free-play run. Phase 1 is open; clear it to open the next."
        : "Free play -- no server. Phase 1 is open; clear it to open the next.",
    );
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
  #grantFreePlayItems() {
    const open = Math.min(this.session.clearedPhases.size + 1, PHASE_COUNT);
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
      else localStorage.setItem(FREE_PLAY_KEY, JSON.stringify(payload));
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
    const hand = this.session.startHand(phase);
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
  async settle(hand, { sendDeath = true } = {}) {
    const died = hand.state === "failed";
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
