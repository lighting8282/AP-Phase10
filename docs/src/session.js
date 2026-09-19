// The bridge between engine state and Archipelago.
//
// Port of phase10/client/session.py. Pure: no sockets, no DOM. That is what
// makes the interesting parts testable -- how received items become a config,
// and which location IDs a finished hand is worth.
//
// Two Python behaviours easy to lose in a port, both pinned by session_test:
//   * Counter[name] is 0 for absent keys, never undefined, so arithmetic on a
//     missing item must not produce NaN.
//   * earnedTiers is computed BEFORE finishRound, because finishing the round
//     takes the hand off the game.

import {
  BASE_HAND_SIZE, EXTRA_DRAW, HANDS_WON_MILESTONES, HAND_SIZE_UPGRADE, LEAN_DEAL,
  LOCATION_NAME_TO_ID, MAX_SKIPS, MULLIGAN, PHASE_COUNT, PHASE_LOCK,
  SCORE_REDUCTION,
  SCORE_REDUCTION_VALUE, SKIP_CARD, TIERS, WILD_CARD,
  WILD_THEFT, milestoneLocationName, phaseLocationName, phaseUnlock,
} from "./data.js";
import { STOCK_WILDS } from "./cards.js";
import { HAND_STATE, Table, gameConfig } from "./engine.js";
import { MID, buildOpponents } from "./opponents.js";
import { Phase10Game, SAVE_VERSION, roundCleared } from "./game.js";

export const LEAN_DEAL_PENALTY = 2;

export class Phase10Session {
  constructor(opts = {}) {
    this.goal = opts.goal ?? 0;
    this.startingDraws = opts.startingDraws ?? 4;
    this.checksPerPhase = opts.checksPerPhase ?? 4;
    this.deathLink = opts.deathLink ?? false;
    this.opponents = opts.opponents ?? 3;

    this.items = new Map();
    this.consumedTraps = new Map();
    this.mulligansUsed = 0;
    this._opponentPhases = [];
    //: The table the current hand is being played at, opponents included.
    this.table = null;
    this.checkedLocations = new Set();
    this.lockedPhase = null;
    this.lastResult = null;
    this.game = opts.game ?? new Phase10Game();
  }

  static fromSlotData(slotData = {}, game = null) {
    return new Phase10Session({
      goal: Number(slotData.goal ?? 0),
      startingDraws: Number(slotData.starting_draws ?? 4),
      checksPerPhase: Number(slotData.checks_per_phase ?? 4),
      deathLink: Boolean(slotData.death_link ?? false),
      opponents: Number(slotData.opponents ?? 3),
      game: game ?? new Phase10Game(),
    });
  }

  // The game owns the running state; the session keeps one source of truth
  // rather than a second tally that could drift from the scorecard.
  get hand() {
    return this.game.hand;
  }

  get handsWon() {
    return this.game.roundsWon;
  }

  get clearedPhases() {
    return this.game.clearedPhases;
  }

  /** Points Score Reduction items have taken off the running total. */
  get scoreReduction() {
    return this.count(SCORE_REDUCTION) * SCORE_REDUCTION_VALUE;
  }

  /**
   * The score as the player is judged on it: raw, less reductions, floored at
   * zero. The scorecard still shows what each round actually cost -- a
   * reduction forgives points, it does not rewrite history.
   */
  get totalScore() {
    return Math.max(0, this.game.totalScore - this.scoreReduction);
  }

  // -- items ---------------------------------------------------------------
  /** Counter semantics: absent means zero, never undefined. */
  count(name) {
    return this.items.get(name) ?? 0;
  }

  /**
   * Replace the received-item tally. Archipelago resends the full list, so
   * this is idempotent rather than incremental, which also makes it safe to
   * call again on reconnect.
   */
  setItems(itemNames) {
    this.items = new Map();
    for (const name of itemNames) {
      this.items.set(name, this.count(name) + 1);
    }
  }

  pending(trap) {
    return Math.max(0, this.count(trap) - (this.consumedTraps.get(trap) ?? 0));
  }

  get unlockedPhases() {
    const open = new Set();
    for (let p = 1; p <= PHASE_COUNT; p += 1) {
      if (this.count(phaseUnlock(p)) > 0) open.add(p);
    }
    return open;
  }

  // -- configuration -------------------------------------------------------
  get config() {
    let handSize = BASE_HAND_SIZE + this.count(HAND_SIZE_UPGRADE);
    let wilds = Math.min(this.count(WILD_CARD), STOCK_WILDS);
    const draws = this.startingDraws + this.count(EXTRA_DRAW);

    if (this.pending(LEAN_DEAL)) handSize -= LEAN_DEAL_PENALTY;
    if (this.pending(WILD_THEFT)) wilds -= 1;

    return gameConfig({
      handSize: Math.max(4, handSize),
      wildsInDeck: Math.max(0, Math.min(wilds, STOCK_WILDS)),
      maxDraws: Math.max(1, draws),
      startingSkips: Math.min(this.count(SKIP_CARD), MAX_SKIPS),
    });
  }

  // -- playing -------------------------------------------------------------
  /** Returns null if the phase is playable, else why not. */
  canPlay(phase) {
    if (!this.unlockedPhases.has(phase)) {
      return `Phase ${phase} is not unlocked yet.`;
    }
    if (this.lockedPhase !== null && phase !== this.lockedPhase) {
      return `A Phase Lock trap is forcing you to replay Phase ${this.lockedPhase}.`;
    }
    return null;
  }

  // -- mulligans -----------------------------------------------------------
  get mulligansLeft() {
    return Math.max(0, this.count(MULLIGAN) - this.mulligansUsed);
  }

  /** Returns null if a Mulligan is usable right now, else why not. */
  canMulligan() {
    if (!this.mulligansLeft) return "No Mulligans left.";
    const hand = this.hand;
    if (!hand || hand.state !== HAND_STATE.IN_PROGRESS) return "No hand in progress.";
    if (hand.drawsUsed || hand.drewThisTurn) {
      return "A Mulligan only works before your first draw.";
    }
    if (hand.digPending) return "Finish the dig first.";
    if (hand.skipsPlayed) return "A Mulligan only works before you play a Skip.";
    return null;
  }

  /** Spend a Mulligan on the current hand and return it, redealt. */
  useMulligan() {
    const refusal = this.canMulligan();
    if (refusal) throw new Error(refusal);
    const hand = this.hand;
    hand.redeal();
    this.mulligansUsed += 1;
    return hand;
  }

  // -- the table -----------------------------------------------------------
  /** Which phase each seat is on. Grows as they clear their own. */
  get opponentPhases() {
    if (!this._opponentPhases.length) {
      this._opponentPhases = new Array(this.opponents).fill(1);
    }
    return this._opponentPhases;
  }

  get seats() {
    return this.table ? this.table.seats : [];
  }

  /** Move every seat that cleared its phase on to the next one. */
  advanceOpponents() {
    const moved = [];
    this.seats.forEach((seat, index) => {
      if (seat.laidDown && index < this.opponentPhases.length) {
        this._opponentPhases[index] = Math.min(10, seat.phase + 1);
        moved.push(seat.name);
      }
    });
    return moved;
  }

  startHand(phase, opts = {}) {
    const refusal = this.canPlay(phase);
    if (refusal) throw new Error(refusal);

    const config = this.config;
    // Consume the one-shot traps that shaped this hand.
    for (const trap of [LEAN_DEAL, WILD_THEFT]) {
      if (this.pending(trap)) {
        this.consumedTraps.set(trap, (this.consumedTraps.get(trap) ?? 0) + 1);
      }
    }
    this.table = new Table();
    if (this.opponents) {
      // Each seat carries its own phase between rounds, so the table gets
      // harder to beat as the run goes on rather than resetting to three
      // players on phase 1 every time.
      this.table.seats = buildOpponents(
        this.opponents, [...this.opponentPhases], config, this.game.random, MID,
      );
    }
    return this.game.startRound(phase, config, { table: this.table, ...opts });
  }

  /**
   * Fail the hand in progress, if there is one.
   *
   * A card game has nothing to kill, so a DeathLink death is a lost hand.
   * Between rounds there is nothing to lose and an incoming death passes
   * harmlessly -- returning null says so, rather than inventing a penalty the
   * player cannot see coming.
   */
  killHand() {
    const hand = this.hand;
    if (!hand || hand.state !== HAND_STATE.IN_PROGRESS) return null;
    hand.markFailed("death_link");
    return hand;
  }

  /** Which check tiers a finished hand is worth. */
  earnedTiers(hand) {
    if (hand.state !== HAND_STATE.PHASE_LAID && hand.state !== HAND_STATE.WENT_OUT) {
      return [];
    }

    const tiers = ["Cleared"];
    if (hand.state === HAND_STATE.WENT_OUT) tiers.push("Went Out");
    if (hand.usedWildsInLayout === 0) tiers.push("No Wilds");
    
    if (hand.drawsUsed <= Math.max(1, Math.floor(hand.config.maxDraws / 2))) {
      tiers.push("Under Par");
    }

    // Tiers the options did not create locations for must never be reported --
    // those IDs do not exist on the server.
    const allowed = new Set(TIERS.slice(0, this.checksPerPhase));
    return tiers.filter((tier) => allowed.has(tier));
  }

  /** Settle a finished hand. Returns newly checked location IDs. */
  finishHand(hand) {
    // Computed first: finishing the round takes the hand off the game.
    const tiers = this.earnedTiers(hand);
    this.advanceOpponents();
    const result = this.game.finishRound(hand);
    this.lastResult = result;

    const names = [];
    if (roundCleared(result)) {
      this.lockedPhase = null;
      for (const tier of tiers) names.push(phaseLocationName(result.phase, tier));
      for (const n of HANDS_WON_MILESTONES) {
        if (n <= this.handsWon) names.push(milestoneLocationName(n));
      }
    } else if (this.pending(PHASE_LOCK)) {
      // A failed hand under a Phase Lock pins you to this phase.
      this.consumedTraps.set(PHASE_LOCK, (this.consumedTraps.get(PHASE_LOCK) ?? 0) + 1);
      this.lockedPhase = result.phase;
    }

    const fresh = [];
    for (const name of names) {
      const id = LOCATION_NAME_TO_ID[name];
      if (!this.checkedLocations.has(id)) {
        this.checkedLocations.add(id);
        fresh.push(id);
      }
    }
    return fresh;
  }

  // -- persistence ---------------------------------------------------------
  /**
   * Everything the server does not already know. Checked locations are
   * deliberately left out: the server is the authority on those, and a second
   * copy could only ever disagree with it.
   */
  toPayload() {
    const traps = {};
    for (const [name, count] of this.consumedTraps) {
      if (count) traps[name] = count;
    }
    return {
      version: SAVE_VERSION,
      game: this.game.toPayload(),
      consumed_traps: traps,
      mulligans_used: this.mulligansUsed,
      opponent_phases: [...this._opponentPhases],
      locked_phase: this.lockedPhase,
    };
  }

  /**
   * Restore from a saved payload. Returns whether it took. Treated as
   * untrusted input -- it arrives over the network, and a partial restore
   * would be worse than none.
   */
  loadPayload(payload) {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return false;
    if (payload.version !== SAVE_VERSION) return false;
    if (!this.game.loadPayload(payload.game)) return false;

    const traps = payload.consumed_traps;
    this.consumedTraps = new Map();
    if (traps && typeof traps === "object" && !Array.isArray(traps)) {
      for (const [name, count] of Object.entries(traps)) {
        if (Number.isInteger(count) && count > 0) this.consumedTraps.set(name, count);
      }
    }

    // Absent in saves written before Mulligans did anything, so a missing key
    // restores as zero rather than refusing the whole payload.
    const used = payload.mulligans_used;
    this.mulligansUsed = Number.isInteger(used) && used >= 0 ? used : 0;

    // Without this a reconnect reseats everyone on phase 1, which quietly
    // hands the player an easier table than they had earned.
    const phases = payload.opponent_phases;
    if (Array.isArray(phases)
        && phases.every((v) => Number.isInteger(v) && v >= 1 && v <= PHASE_COUNT)) {
      this._opponentPhases = [...phases];
    }

    const locked = payload.locked_phase;
    this.lockedPhase =
      Number.isInteger(locked) && locked >= 1 && locked <= PHASE_COUNT ? locked : null;
    return true;
  }

  // -- goal ----------------------------------------------------------------
  get goalMet() {
    if (this.goal === 1) return this.clearedPhases.has(10);
    return this.clearedPhases.size === 10;
  }
}
