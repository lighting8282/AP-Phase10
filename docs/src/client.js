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

import { GAME_NAME } from "./data.js";
import { Phase10Game, roundToString } from "./game.js";
import { Phase10Session } from "./session.js";

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
    this.restoreState = "needed";
    this.goalSent = false;
  }

  get saveKey() {
    const self = this.client.players.self;
    return `phase10_game_${self?.team ?? 0}_${self?.slot ?? 0}`;
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

    this.session = Phase10Session.fromSlotData(slotData, new Phase10Game());
    this.goalSent = false;
    this.restoreState = "needed";
    this.connected = true;

    this.client.items.on("itemsReceived", () => this.syncItems());
    this.client.messages.on("message", (text, nodes) => this.onMessage(text, nodes));

    if (this.session.deathLink) {
      this.client.deathLink.enableDeathLink();
      this.client.deathLink.on("deathReceived", (source, _time, cause) => {
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
    }
    this.client.socket.on("disconnected", () => {
      this.connected = false;
      this.onLog("Disconnected.");
      this.onUpdate();
    });

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
    if (!this.connected || this.restoreState !== "done") return;
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

  /** Finish a hand: report its checks, save, and trip the goal if it is met. */
  async settle(hand, { sendDeath = true } = {}) {
    const died = hand.state === "failed";
    const fresh = this.session.finishHand(hand);
    const result = this.session.lastResult;
    if (result) this.onLog(roundToString(result));

    if (fresh.length && this.connected) {
      this.client.check(...fresh);
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
