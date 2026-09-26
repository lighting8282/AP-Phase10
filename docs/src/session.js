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
  AP_POINT, LOCATION_NAME_TO_ID, MAX_SKIPS, MAX_STORE_SLOTS, MULLIGAN,
  PHASE_COUNT, PHASE_LOCK,
  SCORE_REDUCTION,
  SCORE_REDUCTION_VALUE, SKIP_CARD, TIERS, WILD_CARD,
  WILD_THEFT, milestoneLocationName, phaseLocationName, phaseUnlock,
  storeGate, storeLocationName, storePrices,
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
    this.storeSlots = opts.storeSlots ?? 0;
    this.deathLink = opts.deathLink ?? false;
    this.opponents = opts.opponents ?? 3;

    this.items = new Map();
    this.consumedTraps = new Map();
    this.mulligansUsed = 0;
    //: Which store slots have been bought, so what has been spent is derived
    //: rather than stored twice and left to disagree with itself.
    this.boughtSlots = new Set();
    this._opponentPhases = [];
    this._opponentScores = [];
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
      storeSlots: Number(slotData.store_slots ?? 0),
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
      // Zero starting draws means no budget at all, which only free play
      // asks for: the Archipelago option starts at 2.
      maxDraws: this.startingDraws <= 0 ? 0 : Math.max(1, draws),
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

  // -- the store -----------------------------------------------------------
  // Points arrive as items and buy a check outright. The seed priced each slot
  // at generation, and the gate on a slot is the sum of the cheapest prices up
  // to it -- so holding enough to reach a slot's gate means you could have
  // bought the cheaper ones instead, and any order is legal.

  /** Points received. Never goes down; spending is tracked separately. */
  get points() {
    return this.count(AP_POINT);
  }

  get pointsSpent() {
    const prices = storePrices(this.storeSlots);
    let spent = 0;
    for (const slot of this.boughtSlots) {
      if (slot >= 1 && slot <= this.storeSlots) spent += prices[slot - 1];
    }
    return spent;
  }

  get pointsLeft() {
    return Math.max(0, this.points - this.pointsSpent);
  }

  storePrice(slot) {
    return storePrices(this.storeSlots)[slot - 1];
  }

  /** Returns null if the slot is buyable right now, else why not. */
  canBuy(slot) {
    if (!this.storeSlots) return "This seed has no store.";
    if (!(slot >= 1 && slot <= this.storeSlots)) {
      return `The store has slots 1 to ${this.storeSlots}.`;
    }
    if (this.boughtSlots.has(slot)) return `Slot ${slot} is already bought.`;
    const gate = storeGate(slot);
    if (this.points < gate) {
      // The gate is on points received, not points left: it is what the seed's
      // logic was built on, so checking it here is what keeps the client from
      // reporting a location the server thinks is unreachable.
      return `Slot ${slot} opens at ${gate} points received; you have ${this.points}.`;
    }
    const price = this.storePrice(slot);
    // Unreachable while the prices ascend: any set of slots whose gates you
    // have met costs at most the largest of those gates, which you have. Kept
    // because it is what would catch a ladder that stopped ascending, and the
    // tests pin the invariant rather than this branch.
    if (this.pointsLeft < price) {
      return `Slot ${slot} costs ${price}; you have ${this.pointsLeft} unspent.`;
    }
    return null;
  }

  /** Buy a slot. Returns the location ID to check. */
  buySlot(slot) {
    const refusal = this.canBuy(slot);
    if (refusal) throw new Error(refusal);
    this.boughtSlots.add(slot);
    const id = LOCATION_NAME_TO_ID[storeLocationName(slot)];
    this.checkedLocations.add(id);
    return id;
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

  /**
   * Each seat's running total, the way the pad on the table works.
   *
   * Kept on the session rather than on the seat because the seats are rebuilt
   * from scratch every round, exactly like opponentPhases.
   */
  get opponentScores() {
    if (!this._opponentScores.length) {
      this._opponentScores = new Array(this.opponents).fill(0);
    }
    return this._opponentScores;
  }

  get seats() {
    return this.table ? this.table.seats : [];
  }

  /** Move every seat that cleared its phase on to the next one. */
  advanceOpponents() {
    const moved = [];
    this.seats.forEach((seat, index) => {
      if (seat.laidDown && index < this.opponentPhases.length) {
        this._opponentPhases[index] = Math.min(PHASE_COUNT, seat.phase + 1);
        moved.push(seat.name);
      }
    });
    return moved;
  }

  /**
   * Score every seat on what it is caught holding.
   *
   * Must run before the round is finished, while the seats still hold the
   * hands they ended with. Lower is better here as it is for you: the seat
   * that went out scores nothing, and the one still sitting on a Wild pays
   * twenty-five for it.
   */
  tallyOpponents() {
    const scores = this.opponentScores;
    this.seats.forEach((seat, index) => {
      if (index < scores.length) scores[index] += seat.score;
    });
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

    // Measured at the lay-down, not at the end of the round: the round
    // carries on afterwards so the rest of the hand can be shed, and counting
    // those draws would make Under Par unearnable.
    const spent = hand.drawsAtLayDown ?? hand.drawsUsed;

    const earned = new Set(["Cleared"]);
    if (hand.state === HAND_STATE.WENT_OUT) earned.add("Went Out");
    if (hand.usedWildsInLayout === 0) earned.add("No Wilds");
    if (spent <= Math.max(1, Math.floor(hand.config.maxDraws / 2))) {
      earned.add("Under Par");
    }

    // Walk TIERS rather than the order they were collected in, so the result
    // follows the table and a reorder reaches here for free. checksPerPhase
    // takes a prefix: tiers past it have no location on the server, so
    // reporting one would check an ID that does not exist.
    return TIERS.slice(0, this.checksPerPhase).filter((tier) => earned.has(tier));
  }

  /** Settle a finished hand. Returns newly checked location IDs. */
  finishHand(hand) {
    // Computed first: finishing the round takes the hand off the game.
    const tiers = this.earnedTiers(hand);
    // Both read the seats as they ended the round, so they come before the
    // round is finished and the table is torn down.
    this.tallyOpponents();
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
      opponent_scores: [...this._opponentScores],
      bought_slots: [...this.boughtSlots].sort((a, b) => a - b),
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

    // Absent in saves written before the seats kept score, so a missing key
    // restores as zero rather than refusing the whole payload.
    const scores = payload.opponent_scores;
    if (Array.isArray(scores)
        && scores.every((v) => Number.isInteger(v) && v >= 0)) {
      this._opponentScores = [...scores];
    }

    // Absent in saves written before the store existed, so a missing key
    // restores as nothing bought rather than refusing the whole payload.
    const bought = payload.bought_slots;
    if (Array.isArray(bought)
        && bought.every((v) => Number.isInteger(v) && v >= 1 && v <= MAX_STORE_SLOTS)) {
      this.boughtSlots = new Set(bought);
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
