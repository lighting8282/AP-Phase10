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
  BASE_HAND_SIZE, BUFF_PRICES, BUFF_WILD, EXTRA_DRAW, HANDS_WON_MILESTONES, HAND_SIZE_UPGRADE, LEAN_DEAL,
  AP_POINT, LOCATION_NAME_TO_ID, MAX_SKIPS, MAX_STORE_SLOTS, MULLIGAN,
  PHASE_COUNT, PHASE_LOCK,
  SCORE_REDUCTION,
  SCORE_REDUCTION_VALUE, SKIP_CARD, TIERS, WILD_CARD,
  WILD_THEFT, milestoneLocationName, phaseLocationName, phaseUnlock,
  buffPrice, storeGate, storeLocationName, storePrices,
  STORE_ALL_AT_ONCE, STORE_ALWAYS_OPEN, STORE_GATINGS, STORE_LADDER, PRICE_PROGRESSION,
  DEFAULT_SCORE_THRESHOLD, MAX_SCORE_THRESHOLD, MIN_SCORE_THRESHOLD,
  OPPONENT_PHASE_MATCH, OPPONENT_PHASE_OWN, OPPONENT_PHASES,
} from "./data.js?v=de74181f";
import { SKIP, STOCK_WILDS, WILD } from "./cards.js?v=de74181f";
import { HAND_STATE, Table, gameConfig } from "./engine.js?v=de74181f";
import { MID, NAMES as OPPONENT_NAMES, buildOpponents } from "./opponents.js?v=de74181f";
import { Phase10Game, SAVE_VERSION, roundCleared } from "./game.js?v=de74181f";

export const LEAN_DEAL_PENALTY = 2;

/** The traps a score threshold sets off, in turn. See session.py. */
export const SCORE_TRAP_CYCLE = Object.freeze([LEAN_DEAL, WILD_THEFT]);

/**
 * Data Storage key for a slot's public score, which every AP_10 client in the
 * room writes and the others read. Mirrors score_key in session.py.
 */
export const scoreKey = (team, slot) => `phase10_score_${team}_${slot}`;

/** Another player's published score, or null if it is not one. */
export function readScoreRecord(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const fields = ["score", "won", "cleared"];
  if (!fields.every((f) => Number.isInteger(value[f]) && value[f] >= 0)) return null;
  return Object.fromEntries(fields.map((f) => [f, value[f]]));
}

/** The DeathLink threshold, held to the option's range; absent is the default. */
function readScoreThreshold(slotData) {
  const value = slotData.score_threshold ?? DEFAULT_SCORE_THRESHOLD;
  if (!Number.isInteger(value)) return DEFAULT_SCORE_THRESHOLD;
  return Math.min(MAX_SCORE_THRESHOLD, Math.max(MIN_SCORE_THRESHOLD, value));
}

/** The always-open prices from slot data, or null if absent or malformed. */
function readSlotPrices(slotData) {
  const prices = slotData.store_prices;
  if (!Array.isArray(prices)) return null;
  const ok = prices.every((p) => Number.isInteger(p) && p >= 1 && p <= PRICE_PROGRESSION);
  return ok ? [...prices] : null;
}

export class Phase10Session {
  constructor(opts = {}) {
    this.goal = opts.goal ?? 0;
    this.startingDraws = opts.startingDraws ?? 4;
    this.checksPerPhase = opts.checksPerPhase ?? 4;
    this.storeSlots = opts.storeSlots ?? 0;
    //: "ladder" or "all_at_once". A seed from before the option sends
    //: nothing and reads as the ladder, which is what it was generated as --
    //: reading it any other way would gate slots the server does not.
    this.storeGating = opts.storeGating ?? STORE_LADDER;
    //: Always open only: each slot's price, decided by the world after fill
    //: from the item in it. null for the shapes whose prices are fixed.
    this.slotPrices = opts.slotPrices ?? null;
    //: "dig" or "deny". Only free play sends the latter; an Archipelago seed
    //: never does, because its access rules are built on the dig's numbers.
    this.skipMode = opts.skipMode ?? "dig";
    //: Skips shuffled into the draw pile, so everybody at the table is dealt
    //: from the same deck. Free play sends the four the box has; a seed sends
    //: none and grants Skips as items instead, because a shuffled Skip turns
    //: up too rarely to repay the density it costs every other draw -- which
    //: is a statement about an item's worth, not about how the game is dealt.
    this.skipsInDeck = opts.skipsInDeck ?? 0;
    //: How many phases this run climbs. A free-play run is ten or twenty by
    //: the player's choice; a seed is always the full set, because its
    //: locations exist for every phase.
    this.phaseCap = opts.phaseCap ?? PHASE_COUNT;
    this.phasesToWin = opts.phasesToWin ?? PHASE_COUNT;
    //: Whether finishing the last phase ends the run for everybody, which is
    //: the printed game. A seed has its own goal instead and must not be
    //: ended by a seat -- an opponent finishing is not an Archipelago notion.
    this.raceToEnd = opts.raceToEnd ?? false;
    this.deathLink = opts.deathLink ?? false;
    //: Every this many points of round score sends one DeathLink death.
    this.scoreThreshold = opts.scoreThreshold ?? DEFAULT_SCORE_THRESHOLD;
    //: Thresholds already accounted for -- sent, or absorbed by a hand an
    //: incoming death took. A saved high-water mark, so a reload or a switch
    //: of client never sends one twice.
    this.scoreMarks = 0;
    //: Whether passing a threshold also sets off one of your own traps.
    this.scoreTraps = opts.scoreTraps ?? false;
    //: How many score traps have gone off. Saved; the cycle says which each was.
    this.scoreTrapsFired = 0;
    //: The trap the last threshold set off, for the client to announce.
    this.lastScoreTrap = null;
    this.opponents = opts.opponents ?? 3;
    //: "match": the seats play your phase every round. "own": each climbs
    //: its own from Phase 1 -- free play, and a seed from before the option.
    this.opponentPhase = opts.opponentPhase ?? OPPONENT_PHASE_OWN;

    this.items = new Map();
    this.consumedTraps = new Map();
    this.mulligansUsed = 0;
    //: Which store slots have been bought, so what has been spent is derived
    //: rather than stored twice and left to disagree with itself.
    this.boughtSlots = new Set();
    //: How many of each one-use card have been bought, so what has been spent
    //: on them is derived rather than stored twice and left to disagree.
    this.buffsBought = new Map();
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
      storeGating: STORE_GATINGS.includes(slotData.store_gating)
        ? slotData.store_gating : STORE_LADDER,
      slotPrices: readSlotPrices(slotData),
      // Absent in seeds generated before the option existed, where the
      // world's own rule asked for every phase.
      phasesToWin: Number(slotData.phases_to_win ?? PHASE_COUNT),
      skipMode: slotData.skip_mode === "deny" ? "deny" : "dig",
      skipsInDeck: Number(slotData.skips_in_deck ?? 0),
      raceToEnd: Boolean(slotData.race_to_end ?? false),
      deathLink: Boolean(slotData.death_link ?? false),
      scoreThreshold: readScoreThreshold(slotData),
      scoreTraps: Boolean(slotData.score_traps ?? false),
      opponents: Number(slotData.opponents ?? 3),
      opponentPhase: OPPONENT_PHASES.includes(slotData.opponent_phase)
        ? slotData.opponent_phase : OPPONENT_PHASE_OWN,
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

  // -- DeathLink by score -----------------------------------------------------
  /** The total score at which the next death goes out. */
  get nextScoreMark() {
    return (this.scoreMarks + 1) * this.scoreThreshold;
  }

  /**
   * Whether the score has crossed a new threshold; marks it handled. Returns
   * the threshold reached when a death should go out now, else null. At most
   * one per call, which is one per round. `absorb` marks without sending, for
   * a hand an incoming death ended. A high-water mark: Score Reduction pushes
   * the next death further away. Mirrors score_mark_due in session.py.
   */
  scoreMarkDue({ absorb = false } = {}) {
    this.lastScoreTrap = null;
    const crossed = Math.floor(this.totalScore / this.scoreThreshold);
    if (crossed <= this.scoreMarks) return null;
    this.scoreMarks = crossed;
    if (absorb) return null;
    if (this.scoreTraps) {
      this.lastScoreTrap = SCORE_TRAP_CYCLE[this.scoreTrapsFired % SCORE_TRAP_CYCLE.length];
      this.scoreTrapsFired += 1;
    }
    return crossed * this.scoreThreshold;
  }

  // -- the public score -----------------------------------------------------
  /** What the other AP_10 players see of this run. */
  scoreRecord() {
    return { score: this.totalScore, won: this.handsWon, cleared: this.clearedPhases.size };
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
    return Math.max(0, this.trapCount(trap) - (this.consumedTraps.get(trap) ?? 0));
  }

  /** Traps of this kind received, plus those your score set off. */
  trapCount(trap) {
    const turn = SCORE_TRAP_CYCLE.indexOf(trap);
    if (turn < 0) return this.count(trap);
    const n = SCORE_TRAP_CYCLE.length;
    return this.count(trap) + Math.max(0, Math.floor((this.scoreTrapsFired - turn + n - 1) / n));
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
      skipsInDeck: this.skipsInDeck,
      skipMode: this.skipMode,
    });
  }

  // -- playing -------------------------------------------------------------
  /** Returns null if the phase is playable, else why not. */
  canPlay(phase) {
    if (this.runOver) {
      const won = this.runWinner;
      return won && won.name === "You"
        ? "You won the run -- start a new one when you like."
        : `${won ? won.name : "Somebody"} finished the last phase. `
          + "The run is over -- start a new one when you like.";
    }
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
    let spent = 0;
    for (const slot of this.boughtSlots) {
      if (slot >= 1 && slot <= this.storeSlots) spent += this.storePrice(slot);
    }
    // Cards spend earned points first; only the rest comes out of AP Points.
    return spent + Math.max(0, this.buffPointsSpent - this.cardPointsEarned);
  }

  /**
   * One per round you went out in. Card money only, derived from the
   * scorecard so both clients agree. Mirrors card_points_earned in session.py.
   */
  get cardPointsEarned() {
    return this.game.rounds.filter((r) => r.state === HAND_STATE.WENT_OUT).length;
  }

  get buffPointsSpent() {
    let spent = 0;
    for (const [name, count] of this.buffsBought) spent += buffPrice(name) * count;
    return spent;
  }

  /**
   * What the slots you have not bought still cost.
   *
   * The one thing spending must never do is strand a location the seed was
   * generated as reachable. Archipelago's logic cannot model a currency being
   * spent -- it reasons about points *received* -- so the client is where that
   * has to hold, and it holds by keeping the slots' own prices out of what a
   * buff is allowed to touch.
   */
  get pointsReserved() {
    let owed = 0;
    for (let slot = 1; slot <= this.storeSlots; slot += 1) {
      if (!this.boughtSlots.has(slot)) owed += this.storePrice(slot);
    }
    return owed;
  }

  get slotsLeft() {
    let left = 0;
    for (let slot = 1; slot <= this.storeSlots; slot += 1) {
      if (!this.boughtSlots.has(slot)) left += 1;
    }
    return left;
  }

  /**
   * Points you may spend on a card rather than a check: earned points not yet
   * spent, plus AP Points beyond what the unbought slots owe.
   */
  get buffPointsLeft() {
    const earnedLeft = Math.max(0, this.cardPointsEarned - this.buffPointsSpent);
    return earnedLeft + Math.max(0, this.pointsLeft - this.pointsReserved);
  }

  get pointsLeft() {
    return Math.max(0, this.points - this.pointsSpent);
  }

  storePrice(slot) {
    if (this.storeGating === STORE_ALWAYS_OPEN) {
      // Missing or malformed prices charge the worst case, which can only cost
      // spending money: the pool carries three a slot.
      const prices = this.slotPrices ?? [];
      return prices.length === this.storeSlots ? prices[slot - 1] : PRICE_PROGRESSION;
    }
    return storePrices(this.storeSlots, this.storeGating)[slot - 1];
  }

  /**
   * Points received before `slot` may be bought, for this seed's shape. Always
   * open, none: buying before the logic's gate is out of logic, not out of
   * bounds, and a slot bought costs exactly what it releases from the reserve.
   */
  storeGate(slot) {
    if (this.storeGating === STORE_ALWAYS_OPEN) return 0;
    return storeGate(slot, this.storeSlots, this.storeGating);
  }

  /** Returns null if the slot is buyable right now, else why not. */
  canBuy(slot) {
    if (!this.storeSlots) return "This seed has no store.";
    if (!(slot >= 1 && slot <= this.storeSlots)) {
      return `The store has slots 1 to ${this.storeSlots}.`;
    }
    if (this.boughtSlots.has(slot)) return `Slot ${slot} is already bought.`;
    const gate = this.storeGate(slot);
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

  // -- one-use cards ---------------------------------------------------------
  // The other half of the store: a card, once, now. Bought any number of times
  // while the points last, and gone the moment it is played or discarded. They
  // are here for the run where you are three rounds into phase 17 and the deck
  // will not give you a fourth nine.

  /** Returns null if the buff is buyable right now, else why not. */
  canBuyBuff(buff) {
    if (!(buff in BUFF_PRICES)) return `The store does not sell ${buff}.`;
    if (!this.storeSlots) return "This seed has no store.";
    const hand = this.hand;
    if (!hand || hand.state !== HAND_STATE.IN_PROGRESS) {
      return "A one-use card is bought into a hand; start a round first.";
    }
    if (hand.digPending || hand.denyPending) {
      return "Finish the move you are in first.";
    }
    const price = buffPrice(buff);
    if (this.buffPointsLeft < price) {
      const reserved = this.pointsReserved;
      if (reserved && this.pointsLeft >= price) {
        // Spelled out rather than refused flatly: the points are there, they
        // are just the ones the remaining checks are owed.
        return `${buff} costs ${price}; ${this.pointsLeft} unspent, but `
          + `${reserved} of those are held for the ${this.slotsLeft} slot(s) `
          + "you have not bought.";
      }
      return `${buff} costs ${price}; you have ${this.buffPointsLeft} to spend.`;
    }
    return null;
  }

  /** Buy a one-use card. It lands in your hand, and it is yours to lose. */
  buyBuff(buff) {
    const refusal = this.canBuyBuff(buff);
    if (refusal) throw new Error(refusal);
    this.buffsBought.set(buff, (this.buffsBought.get(buff) ?? 0) + 1);
    return this.hand.takeBoughtCard(buff === BUFF_WILD ? WILD : SKIP);
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
  /** The phase each seat plays this round. Mirrors seat_phases in session.py. */
  seatPhases(phase) {
    if (this.opponentPhase === OPPONENT_PHASE_MATCH) return new Array(this.opponents).fill(phase);
    return [...this.opponentPhases];
  }

  advanceOpponents() {
    // Matching seats have no phase of their own to climb.
    if (this.opponentPhase === OPPONENT_PHASE_MATCH) return [];
    const moved = [];
    this.seats.forEach((seat, index) => {
      if (seat.laidDown && index < this.opponentPhases.length) {
        // One past the cap in a race, and no further. That is not a phase
        // anybody plays: it is how a seat records that it finished the last
        // one, the same way your own cleared set records that you did. It
        // used to stop at PHASE_COUNT whatever the run's cap was, so a
        // ten-phase run had seats climbing to sixteen.
        //
        // Without a race there is nothing to finish, so a seat stops *on* the
        // last phase -- a seed showing "phase 21" would be a marker for an
        // event that mode does not have.
        const ceiling = this.phaseCap + (this.raceToEnd ? 1 : 0);
        this._opponentPhases[index] = Math.min(ceiling, seat.phase + 1);
        moved.push(seat.name);
      }
    });
    return moved;
  }

  /** Whether a seat has finished the last phase of the run. */
  seatFinished(index) {
    return (this.opponentPhases[index] ?? 1) > this.phaseCap;
  }

  /** Whether you have. */
  get playerFinished() {
    return this.clearedPhases.has(this.phaseCap);
  }

  /**
   * Whether the run is over, which only the printed game decides this way.
   *
   * Derived rather than stored, like the unlocks and the cleared set: the
   * seat phases and the scorecard are both saved already, so a reloaded run
   * knows it is finished without a save format that could disagree with it.
   */
  get runOver() {
    if (!this.raceToEnd) return false;
    if (this.playerFinished) return true;
    return this.opponentPhases.some((_, i) => this.seatFinished(i));
  }

  /**
   * Who won, and by what.
   *
   * Everybody who finished the last phase is a finisher -- more than one can,
   * in the round that ends the run -- and the lowest score among them wins,
   * which is how the box breaks it. A tie on score goes to you, then round
   * the table, because somebody has to be named and an unresolved tie is not
   * something a solitaire run can play off.
   */
  get runWinner() {
    if (!this.runOver) return null;
    const finishers = [];
    if (this.playerFinished) finishers.push({ name: "You", score: this.totalScore });
    this.opponentPhases.forEach((_, i) => {
      if (this.seatFinished(i)) {
        finishers.push({ name: this.seatName(i), score: this.opponentScores[i] ?? 0 });
      }
    });
    if (!finishers.length) return null;
    return finishers.reduce((best, who) => (who.score < best.score ? who : best));
  }

  /** What a seat is called, whether or not a table is dealt right now. */
  seatName(index) {
    return this.seats[index]?.name ?? OPPONENT_NAMES[index] ?? `Seat ${index + 1}`;
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
      // On your phase when they match it -- the default for a seed, so a
      // round's difficulty is the phase you chose. Otherwise each seat carries
      // its own phase between rounds, which in free play is the race.
      this.table.seats = buildOpponents(
        this.opponents, this.seatPhases(phase), config, this.game.random, MID,
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
      // Saved, or a reload would hand the points back and the one-use cards
      // would be free to anybody willing to refresh the page.
      buffs_bought: Object.fromEntries(this.buffsBought),
      locked_phase: this.lockedPhase,
      score_marks: this.scoreMarks,
      score_traps_fired: this.scoreTrapsFired,
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

    // Same, one version later. A name the store does not sell is dropped
    // rather than trusted: this arrives over the network like the rest.
    const buffs = payload.buffs_bought;
    if (buffs && typeof buffs === "object" && !Array.isArray(buffs)) {
      for (const [name, count] of Object.entries(buffs)) {
        if (name in BUFF_PRICES && Number.isInteger(count) && count >= 0) {
          this.buffsBought.set(name, count);
        }
      }
    }

    // Absent in saves written before deaths were sent by score. Caught up
    // rather than zeroed, so an update never sends a surprise death.
    const sent = payload.score_marks;
    this.scoreMarks = Number.isInteger(sent) && sent >= 0
      ? sent : Math.floor(this.totalScore / this.scoreThreshold);

    const fired = payload.score_traps_fired;
    this.scoreTrapsFired = Number.isInteger(fired) && fired >= 0 ? fired : 0;

    const locked = payload.locked_phase;
    this.lockedPhase =
      Number.isInteger(locked) && locked >= 1 && locked <= PHASE_COUNT ? locked : null;
    return true;
  }

  // -- goal ----------------------------------------------------------------
  /**
   * Whether this slot is finished, by the seed's own reckoning.
   *
   * Counted against `phasesToWin` and against the *named* phases, not against
   * a total. Two bugs lived here. The count was ten while the world's
   * completion rule asked for every one of twenty, so a client declared
   * victory at half the seed and the server believed it -- the number was
   * written when there were ten phases and never moved when the other ten
   * arrived. And a total would let any ten phases stand in for the first ten,
   * which is not what `HasAll(Phase 1..N Clear)` says.
   */
  get goalMet() {
    if (this.goal === 1) return this.clearedPhases.has(10);
    for (let phase = 1; phase <= this.phasesToWin; phase += 1) {
      if (!this.clearedPhases.has(phase)) return false;
    }
    return true;
  }
}
