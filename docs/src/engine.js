/**
 * Headless solo Phase 10 engine.
 *
 * A direct port of phase10/game/engine.py. Pure -- no DOM, no Archipelago, no
 * I/O. A client drives it turn by turn and reads `events` to decide which
 * locations to check.
 *
 * Solo play replaces the multiplayer race-to-go-out with pressure from the
 * draw pile: you get a bounded number of draws to lay your phase down. Skips
 * have no opponent to skip, so they dig instead -- play one to see the top of
 * the stock and keep a card of your choice.
 */

import {
  SKIP,
  WILD,
  buildDeck,
  cardToString,
  handScore,
  isSkip,
  isWild,
  numberCard,
  COLORS,
} from "./cards.js?v=7cfd187b";
import {
  GROUP, PHASES, phaseCardCount, solveLayOptions, solveMelds, solvePhase,
} from "./phases.js?v=7cfd187b";

/** How deep into the stock a played Skip lets you look. */
export const SKIP_DIG_DEPTH = 3;

export const HAND_STATE = {
  IN_PROGRESS: "in_progress",
  PHASE_LAID: "phase_laid",
  WENT_OUT: "went_out",
  FAILED: "failed",
};

/** Everything Archipelago items are allowed to move. */
export function gameConfig(overrides = {}) {
  return {
    handSize: 10,          // "Hand Size +1" items
    wildsInDeck: 8,        // "Wild Card" items
    // Zero or less means no budget at all, which is how the printed game
    // plays: the round ends when somebody goes out, not when a clock runs
    // down. Archipelago never sets it there, so this is the free-play path.
    maxDraws: 20,          // "Extra Draw" items
    startingSkips: 0,
    // What playing a Skip does. "dig" reveals the top three of the stock and
    // keeps one; "deny" is the printed rule, where the next seat loses its
    // turn. Archipelago uses the dig, because every measured clear rate its
    // access rules are built on was measured with it. "deny" is the free-play
    // game, where nothing is gated on a difficulty number.
    skipMode: "dig",      // "Skip Card" items
    // Skips shuffled into the draw pile, for fidelity to the physical deck.
    // Measured as a straight loss -- they turn up 0.34 times per hand, too
    // rarely to repay the density they cost every other draw -- so Archipelago
    // grants Skips via startingSkips instead and leaves this at zero.
    skipsInDeck: 0,
    minNaturalsPerGroup: 1,
    allowDiscardDraw: true,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Randomness
//
// Deliberately NOT an attempt to mirror Python's Mersenne Twister. The engines
// are compared as pure functions over a given deck, so deck order never needs
// to agree -- see docs/test/crosscheck.mjs.
// ---------------------------------------------------------------------------

/** Small deterministic PRNG, so a seed reproduces a session for debugging. */
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function shuffledDeck(random, wilds, skips) {
  const deck = buildDeck(wilds, skips);
  for (let i = deck.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [deck[i], deck[j]] = [deck[j], deck[i]];
  }
  return deck;
}

// ---------------------------------------------------------------------------

function sameCard(a, b) {
  return a.kind === b.kind && a.rank === b.rank && a.color === b.color;
}

/**
 * Remove one card equal to `card`. Python's list.remove() deletes the first
 * VALUE-equal element (Card is a frozen dataclass); JS objects compare by
 * reference, so identity removal would silently miss an equal-but-distinct
 * card and corrupt the hand.
 */
export function removeCard(cards, card) {
  const i = cards.findIndex((c) => sameCard(c, card));
  if (i === -1) throw new Error(`${cardToString(card)} is not in hand`);
  cards.splice(i, 1);
  return card;
}

/**
 * The stock and the discard pile: what every seat shares.
 *
 * Port of engine.py's Table. Split out of PhaseHand so opponents can draw from
 * the same deck the player is drawing from. With no seats a hand builds its own
 * private Table and behaves exactly as it did when it owned these two lists.
 */
export class Table {
  constructor() {
    this.stock = [];
    this.discard = [];
    this.seats = [];
    //: What the seats did, oldest first, as [seat name, sentence]. The clients
    //: drain it: opponents played in silence before this, so a seat denied its
    //: turn looked exactly like one that took it.
    this.log = [];
    // Sticky: once somebody is out the round is over, and a player who keeps
    // acting must keep losing it rather than slipping through because the
    // transition already happened.
    this.winner = null;
    //: The hand being played at this table, so a seat aiming a Skip can see
    //: the player as a target like any other. Without it the seats could only
    //: ever deny each other, which is a rule that runs one way.
    this.player = null;
  }

  reset(stock, discard) {
    this.stock = stock;
    this.discard = discard;
    this.winner = null;
    this.log.length = 0;
  }

  say(seat, sentence) {
    this.log.push([seat, sentence]);
  }

  /** Take everything said since the last time anybody looked. */
  drainLog() {
    const said = this.log;
    this.log = [];
    return said;
  }

  deal(count) {
    return this.stock.splice(0, count);
  }

  dealSeats(count) {
    for (const seat of this.seats) {
      seat.hand = this.deal(count);
      seat.layout = [];
      seat.melds = [];
      seat.laidDown = false;
      seat.wentOut = false;
      seat.skipped = false;
      // Per round, like everything else here: last round's tally would make
      // this round's table impossible to reconcile.
      seat.drew = 0;
      seat.threw = 0;
      seat.placed = 0;
    }
  }

  get discardTop() {
    return this.discard.length ? this.discard[this.discard.length - 1] : null;
  }

  /**
   * The seat that would play next, or null if nobody would.
   *
   * Seats act in order after the player, so the next one is the first still in
   * the round. One already denied a turn is passed over: stacking two Skips on
   * a seat would cost the second one nothing.
   */
  nextActor() {
    for (const seat of this.seats) {
      if (!seat.wentOut && !seat.skipped) return seat;
    }
    return null;
  }

  /**
   * Everybody still in the round who could lose a turn, the player included.
   *
   * One place, so the player throwing a Skip and a seat throwing one are
   * choosing from the same list by the same rule. `exclude` is whoever is
   * throwing it -- you cannot deny yourself -- and anyone already denied is
   * left out, since a second Skip on them would cost nothing.
   */
  denyTargets(exclude = null) {
    const targets = [];
    const player = this.player;
    if (player && player !== exclude && !player.skipped
      && player.state === HAND_STATE.IN_PROGRESS) {
      targets.push(player);
    }
    for (const seat of this.seats) {
      if (seat !== exclude && !seat.wentOut && !seat.skipped) targets.push(seat);
    }
    return targets;
  }

  /**
   * Every group face up on the table, in seat order.
   *
   * Phase 10 lets a hit land on anybody's group, not just your own, so
   * targeting has to see the whole table rather than one seat.
   */
  allMelds() {
    const melds = [];
    for (const seat of this.seats) melds.push(...seat.melds);
    return melds;
  }

  /**
   * Play one seat's turn. Returns the winner once there is one.
   *
   * Split out of endOfTurn so a driver that wants to show the turns happening
   * one at a time can take them one at a time. Everything a turn means lives
   * here rather than in the loop below -- including consuming a Skip -- because
   * a seat played through here has to be played exactly as it is played there.
   * Pacing is presentation; it may not change what a turn does.
   */
  playSeat(seat) {
    if (this.winner !== null) return this.winner;
    if (seat.skipped) {
      // Consumed where the turn would have happened rather than where the
      // Skip was played, so it costs exactly one turn however long it waits.
      seat.skipped = false;
      this.say(seat.name, "misses a turn");
      return this.winner;
    }
    if (seat.takeTurn(this)) this.winner = seat;
    return this.winner;
  }

  /** Run every opponent's turn. Returns the seat that went out, if any. */
  endOfTurn() {
    if (this.winner !== null) return this.winner;
    for (const seat of this.seats) {
      if (this.playSeat(seat) !== null) return this.winner;
    }
    return null;
  }
}

/** One round: a single attempt at a single phase. */
export class PhaseHand {
  /**
   * @param {object} [opts]
   * @param {Function} [opts.random] RNG in [0,1); defaults to Math.random.
   * @param {Array}    [opts.deck]   Pre-built deck, bypassing the shuffle.
   *                                 Used by the differential tests so both
   *                                 engines can be replayed over one deal.
   * @param {Array}    [opts.spec]   Override the phase spec.
   * @param {boolean}  [opts.paced]  Hand the opponents' turns to the driver
   *                                 instead of playing them all the instant
   *                                 the player's turn ends. See stepOpponent.
   */
  constructor(phase, config, opts = {}) {
    this.phase = phase;
    this.spec = opts.spec ?? PHASES[phase];
    this.config = config;

    // Kept so a Mulligan can shuffle again. A fixed `deck` is honoured for the
    // opening deal only -- a redeal past it has nothing recorded to deal, so
    // the trace exporter does not emit redeals into the differential fixtures.
    this._random = opts.random ?? Math.random;
    //: Shared with the opponents when there are any; private otherwise.
    this.table = opts.table ?? new Table();
    // So the seats can aim at you. A back-reference rather than a copy of what
    // they need to know, because what a good target looks like is the seats'
    // business and it would otherwise be spelled out twice.
    this.table.player = this;
    //: Set by a seat that threw a Skip at you; consumed after the seats have
    //: played, where your turn would have been.
    this.skipped = false;
    //: How many turns Skips have cost you this hand. The flag is consumed the
    //: instant the turn is lost, so a driver that only looks between moves
    //: would never see it -- this is what it reads instead.
    this.turnsMissed = 0;
    //: Opt-in: the browser client shows each seat move and so needs to hold
    //: them, while every headless driver wants the turn resolved on the spot.
    this.paced = Boolean(opts.paced);
    //: Seats owed a turn, oldest first. Only ever non-empty when paced.
    this.pendingSeats = [];
    this._deal(opts.deck);

    this.drawsUsed = 0;
    this.state = HAND_STATE.IN_PROGRESS;
    this.layout = null;
    // The player's own groups on the table, with what each one means, so
    // cards can be hit onto them as well as onto the opponents'.
    this.melds = [];
    // Phase is on the table. Separate from `state`, which stays IN_PROGRESS
    // so the round can continue into shedding.
    this.laid = false;
    this.hits = 0;
    // Draws spent when the phase went down. "Under Par" asks how fast you
    // cleared, not how long the round then ran -- and the round now runs on
    // past the lay-down, burning the rest of the budget to shed.
    this.drawsAtLayDown = null;
    this.events = [];
    this.drewThisTurn = false;
    this.usedWildsInLayout = 0;
    this.skipsPlayed = 0;
    this.digOptions = null;
    //: A discarded Skip waiting to be aimed, as the seats it could be aimed
    //: at. Null when there is nothing to aim. Deny mode only.
    this.pendingDeny = null;
  }

  /**
   * Shuffle and deal. Shared by the opening deal and a Mulligan, so the two
   * cannot drift into dealing subtly different tables.
   */
  _deal(fixedDeck = null) {
    const deck = fixedDeck
      ? fixedDeck.map((c) => ({ ...c }))
      : shuffledDeck(this._random, this.config.wildsInDeck, this.config.skipsInDeck);

    this.hand = deck.slice(0, this.config.handSize);
    // Granted Skips are dealt on top of the hand rather than out of it, so
    // holding them costs no room to build the phase in.
    for (let i = 0; i < this.config.startingSkips; i++) this.hand.push({ ...SKIP });

    const rest = deck.slice(this.config.handSize);
    this.table.reset(rest.slice(1), rest.length ? [rest[0]] : []);
    // Opponents are dealt from the same deck, so a Mulligan before anyone has
    // acted redeals the whole table -- which is what a reshuffle means.
    this.table.dealSeats(this.config.handSize);
  }

  /**
   * Throw the opening hand back and deal a fresh one -- a Mulligan.
   *
   * Deliberately restricted to before the first draw. A reroll available at
   * any point is a far stronger item than a bad-opening insurance policy, and
   * it would invalidate the measured clear rates the access rules are built
   * on. Costs no draw: the point is to undo a dead deal, not to pay for it out
   * of the same budget the deal already ruined.
   */
  redeal() {
    if (this.state !== HAND_STATE.IN_PROGRESS) throw new Error(`hand is ${this.state}`);
    if (this.drawsUsed || this.drewThisTurn) {
      throw new Error("a Mulligan only works before your first draw");
    }
    if (this.digPending) throw new Error("finish the dig first");
    if (this.skipsPlayed) throw new Error("a Mulligan only works before you play a Skip");
    // A Mulligan redeals the whole table, so any turn still owed is owed by a
    // seat that no longer holds the hand it was owed on.
    this.pendingSeats = [];
    this._deal();
    this._emit("redeal", { hand: this.hand.length });
  }

  // -- queries --------------------------------------------------------------
  get stock() {
    return this.table.stock;
  }

  get discard() {
    return this.table.discard;
  }

  get unlimitedDraws() {
    return this.config.maxDraws <= 0;
  }

  /**
   * Draws remaining, or null when there is no budget.
   *
   * null rather than a large number, so a caller that forgets to handle the
   * unlimited case fails loudly instead of quietly comparing against
   * something arbitrary.
   */
  get drawsLeft() {
    if (this.unlimitedDraws) return null;
    return Math.max(0, this.config.maxDraws - this.drawsUsed);
  }

  get discardTop() {
    return this.discard.length ? this.discard[this.discard.length - 1] : null;
  }

  get digPending() {
    return this.digOptions !== null;
  }

  get skipsInHand() {
    return this.hand.filter(isSkip).length;
  }

  solution() {
    return solvePhase(this.hand, this.spec, this.config.minNaturalsPerGroup);
  }

  canLayDown() {
    return this.solution() !== null;
  }

  // -- actions --------------------------------------------------------------
  draw(fromDiscard = false) {
    if (this.state !== HAND_STATE.IN_PROGRESS) throw new Error(`hand is ${this.state}`);
    if (this.drewThisTurn) throw new Error("already drew this turn; discard first");
    if (this.denyPending) throw new Error("say who misses their turn first");

    let card;
    if (fromDiscard) {
      if (!this.config.allowDiscardDraw || !this.discard.length) {
        throw new Error("cannot draw from discard");
      }
      card = this.discard.pop();
    } else {
      if (!this.stock.length) this._refillStock();
      if (!this.stock.length) {
        this.markFailed("stock_empty");
        throw new Error("stock is empty");
      }
      card = this.stock.shift();
    }
    this.hand.push(card);
    this.drawsUsed += 1;
    this.drewThisTurn = true;
    return card;
  }

  /**
   * Turn the discard pile back into a stock, the way the box says.
   *
   * Without a draw budget a long round drains the stock, and the engine
   * treated that as a lost hand -- a way to lose that is in no version of the
   * rules. The top card stays face up; the rest is shuffled back.
   *
   * With a budget this is unreachable in practice (four players at eight draws
   * take 32 of about 60 cards), so it changes no measured rate.
   */
  _refillStock() {
    if (this.discard.length <= 1) return;
    const top = this.discard.pop();
    const stock = this.table.stock;
    stock.push(...this.discard);
    this.discard.length = 0;
    this.discard.push(top);
    for (let i = stock.length - 1; i > 0; i -= 1) {
      const j = Math.floor(this._random() * (i + 1));
      [stock[i], stock[j]] = [stock[j], stock[i]];
    }
    this._emit("stock_refilled", { cards: stock.length });
  }

  discardCard(card) {
    if (this.state !== HAND_STATE.IN_PROGRESS) throw new Error(`hand is ${this.state}`);
    // Before the draw check: once a Skip is waiting to be aimed the draw is
    // already spent, so "must draw before discarding" would name the wrong
    // problem and send the player looking for a draw they cannot make.
    if (this.denyPending) throw new Error("say who misses their turn first");
    if (!this.drewThisTurn) throw new Error("must draw before discarding");
    removeCard(this.hand, card);
    this.discard.push(card);
    this.drewThisTurn = false;
    if (this.laid && !this.hand.length) {
      // Shedding the last card onto the discard pile is going out, the
      // ordinary way it happens: hit what you can and throw the rest.
      // Going out ends the round, so a Skip thrown to go out denies nobody --
      // there is no next turn left for anyone to miss.
      this.state = HAND_STATE.WENT_OUT;
      this._emit("went_out", { draws_used: this.drawsUsed });
      return;
    }
    // The printed rule: a Skip is discarded, and whoever discarded it says who
    // loses a turn. The turn does not end until they have said, which is what
    // denySeat is for. With nobody eligible it is an ordinary discard -- the
    // card is spent either way, and refusing the throw would strand a player
    // holding a Skip they cannot legally get rid of.
    if (this.config.skipMode === "deny" && isSkip(card)) {
      const targets = this.denyTargets();
      if (targets.length) {
        this.pendingDeny = targets;
        return;
      }
    }
    this._endTurn();
  }

  /**
   * The seats a Skip could be thrown at right now.
   *
   * One already denied is left out: stacking two Skips on a seat would cost
   * the second one nothing, which is the same reason nextActor passes it over.
   */
  denyTargets() {
    // Excluding yourself, which is the only difference between your list and
    // a seat's -- the rule is otherwise the same for everybody at the table.
    return this.table.denyTargets(this);
  }

  /** Whether a discarded Skip is waiting to be pointed at somebody. */
  get denyPending() {
    return this.pendingDeny !== null;
  }

  /** Say who misses their turn, and end the turn. */
  denySeat(index) {
    if (this.pendingDeny === null) throw new Error("no Skip to aim");
    if (!(index >= 0 && index < this.pendingDeny.length)) {
      throw new RangeError(`pick 0..${this.pendingDeny.length - 1}`);
    }
    const target = this.pendingDeny[index];
    this.pendingDeny = null;
    target.skipped = true;
    this.skipsPlayed += 1;
    this._emit("skip_denied", { seat: target.name });
    this._endTurn();
    return target;
  }

  /**
   * Spend a Skip to look at the top of the stock.
   *
   * The Skip becomes this turn's discard, so no separate discard follows --
   * that is what keeps hand size stable and lets the Skip shed itself. The dig
   * costs no draw. Resolve the reveal with takeDug.
   */
  playSkip() {
    if (this.state !== HAND_STATE.IN_PROGRESS) throw new Error(`hand is ${this.state}`);
    if (this.digOptions !== null) throw new Error("finish the current dig first");
    if (this.drewThisTurn) throw new Error("already drew this turn; discard first");
    const skip = this.hand.find(isSkip);
    if (!skip) throw new Error("no Skip in hand");

    // Denying is done by discarding the Skip, the way the box has it, so there
    // is no pre-draw move to make. There used to be, and it was a trap: the
    // button went dark the moment you drew, and the only thing left to do with
    // the Skip was throw it away for nothing.
    if (this.config.skipMode === "deny") {
      throw new Error("discard the Skip to make somebody miss a turn");
    }

    if (!this.stock.length) throw new Error("stock is empty");

    removeCard(this.hand, skip);
    this.discard.push(skip);
    const depth = Math.min(SKIP_DIG_DEPTH, this.stock.length);
    this.digOptions = this.stock.slice(0, depth);
    this.stock.splice(0, depth);
    return [...this.digOptions];
  }

  /** Keep one revealed card; the rest go to the bottom of the stock. */
  takeDug(index) {
    if (this.digOptions === null) throw new Error("no dig in progress");
    if (!(index >= 0 && index < this.digOptions.length)) {
      throw new RangeError(`pick 0..${this.digOptions.length - 1}`);
    }
    const [chosen] = this.digOptions.splice(index, 1);
    this.hand.push(chosen);
    this.stock.push(...this.digOptions);
    this.digOptions = null;

    // A dig deliberately does NOT spend a draw. Charging for it made Skips a
    // net loss in simulation (-1% to -7% across every phase): you burn a draw
    // finding the Skip and another using it, and a choice of three does not
    // pay for two turns.
    this.skipsPlayed += 1;
    this.drewThisTurn = false;
    this._emit("skip_dug", { card: cardToString(chosen) });
    this._endTurn();
    return chosen;
  }

  /**
   * Close out the player's turn, then let the table play.
   *
   * Order matters: a budget that just ran out ends the hand before the
   * opponents move, so a loss is attributed to the thing that actually caused
   * it rather than to whoever happened to go out next.
   */
  _endTurn() {
    this._failIfOutOfRoad();
    if (this.state !== HAND_STATE.IN_PROGRESS) return;
    // A turn you have been denied is spent here, where it would have happened
    // -- the same bargain a seat's own Skip makes -- and it costs you exactly
    // one turn however long it waited. Losing it means the seats come round
    // again before you act, which is what a lost turn *is*: the table plays
    // twice and you play once.
    const lost = this.skipped;
    if (lost) {
      this.skipped = false;
      this.turnsMissed += 1;
      this.table.say("You", "miss a turn");
      this._emit("turn_missed", {});
    }
    if (this.paced) {
      // Queued, not played: the driver walks them with stepOpponent so the
      // player can watch. Nothing is owed once somebody has already gone out.
      if (this.table.winner !== null) {
        this.pendingSeats = [];
        return;
      }
      this.pendingSeats = lost
        ? [...this.table.seats, ...this.table.seats]
        : [...this.table.seats];
      return;
    }
    this._settleTableTurn(this.table.endOfTurn());
    if (lost && this.state === HAND_STATE.IN_PROGRESS) {
      this._settleTableTurn(this.table.endOfTurn());
    }
  }

  /** Apply what the table's turn did to the hand. */
  _settleTableTurn(winner) {
    if (winner === null) return;
    if (this.laid) {
      // The phase is down, so it is cleared. Somebody else going out only
      // stops the shedding; it cannot take the clear back.
      this.state = HAND_STATE.PHASE_LAID;
      this._emit("raced_after_laying", { opponent: winner.name, held: this.hand.length });
    } else {
      this.markFailed("opponent_out", { opponent: winner.name });
    }
  }

  /** Whether any seat is still owed a turn from the player's last one. */
  get turnPending() {
    return this.pendingSeats.length > 0;
  }

  /**
   * Play the next seat that is owed a turn. Returns the seat, or null.
   *
   * Paced mode only -- the seats play themselves otherwise. A seat that goes
   * out ends the round here exactly as it would have inside _endTurn, and the
   * seats behind it in the queue never move, which is the same thing endOfTurn
   * does when it returns early.
   */
  stepOpponent() {
    if (this.state !== HAND_STATE.IN_PROGRESS) {
      this.pendingSeats = [];
      return null;
    }
    const seat = this.pendingSeats.shift();
    if (seat === undefined) return null;
    const winner = this.table.playSeat(seat);
    if (winner !== null) {
      this.pendingSeats = [];
      this._settleTableTurn(winner);
    }
    return seat;
  }

  /** Play out every turn still owed, without pausing. */
  finishOpponentTurns() {
    while (this.turnPending) this.stepOpponent();
  }

  /**
   * Settle the hand if the draw budget has run out.
   *
   * Once the phase is down this is not a loss at all -- it was cleared, and
   * the budget expiring only stops you shedding the rest.
   */
  _failIfOutOfRoad() {
    if (this.state !== HAND_STATE.IN_PROGRESS || this.drawsLeft !== 0) return;
    if (this.laid) {
      this.state = HAND_STATE.PHASE_LAID;
      this._emit("out_of_draws_after_laying", { held: this.hand.length });
    } else if (!this.canLayDown()) {
      this.markFailed("out_of_draws");
    }
  }


  /**
   * Every distinct way this hand could lay the phase down.
   *
   * More than one only when a wild could stand for more than one thing -- and
   * then the choice is worth making, because it decides what can be hit onto
   * the group afterwards. A run of 4 from `W 4 5 6` is 3-4-5-6 or 4-5-6-7,
   * which take a 2 or a 7 and a 3 or an 8 respectively.
   */
  layDownOptions() {
    if (this.laid || this.state !== HAND_STATE.IN_PROGRESS) return [];
    return solveLayOptions(this.hand, this.spec, this.config.minNaturalsPerGroup);
  }

  /**
   * Lay the phase down, optionally choosing what the wilds stand for.
   *
   * With no option this keeps taking the solver's first answer, which is what
   * every caller that does not care about wilds already relied on.
   */
  layDown(option = null) {
    if (this.laid) throw new Error("phase is already down");
    let melds;
    if (option) {
      melds = [...option.melds];
      const held = [...this.hand];
      for (const card of melds.flatMap((m) => m.cards)) {
        const at = held.indexOf(card);
        if (at === -1) throw new Error("that lay-down is not from this hand");
        held.splice(at, 1);
      }
    } else {
      melds = solveMelds(this.hand, this.spec, this.config.minNaturalsPerGroup);
    }
    if (melds === null) throw new Error(`phase ${this.phase} not satisfiable from hand`);
    // The layout is built out of the melds, so what you can see and what the
    // group means cannot drift apart.
    this.melds = melds;
    const layout = melds.map((m) => m.cards);
    this.layout = layout;
    this.usedWildsInLayout = layout.flat().filter(isWild).length;
    for (const group of layout) {
      for (const card of group) removeCard(this.hand, card);
    }
    // Deliberately NOT terminal. Laying down clears the phase, and the round
    // then carries on so the cards still in hand can be hit onto whatever is
    // on the table -- which is the whole point of hitting.
    this.laid = true;
    this.drawsAtLayDown = this.drawsUsed;
    this._emit("phase_completed", {
      draws_used: this.drawsUsed,
      wilds_used: this.usedWildsInLayout,
    });
    if (!this.hand.length) {
      this.state = HAND_STATE.WENT_OUT;
      this._emit("went_out", { draws_used: this.drawsUsed });
    }
    return layout;
  }

  /**
   * Lay one card from hand onto a group already on the table.
   *
   * Only after your own phase is down -- that is the rule the whole mechanic
   * hangs on, and it is what stops hitting being a way to dump cards you
   * could not otherwise place.
   */
  hit(card, meld) {
    if (this.state !== HAND_STATE.IN_PROGRESS) throw new Error(`hand is ${this.state}`);
    if (!this.laid) throw new Error("lay your own phase down before hitting");
    if (this.digPending) throw new Error("finish the dig first");
    if (this.denyPending) throw new Error("say who misses their turn first");
    if (!meld.accepts(card)) throw new Error(`${cardToString(card)} does not fit that group`);

    removeCard(this.hand, card);
    meld.add(card);
    this.hits += 1;
    this._emit("hit", { card: cardToString(card) });
    if (!this.hand.length) {
      // Shedding the last card is going out, with no discard needed.
      this.state = HAND_STATE.WENT_OUT;
      this._emit("went_out", { draws_used: this.drawsUsed });
    }
  }

  /** Every group on the table you could legally play onto right now. */
  hittable() {
    if (this.state !== HAND_STATE.IN_PROGRESS || !this.laid) return [];
    const targets = [...this.melds, ...this.table.allMelds()];
    return targets.filter((m) => this.hand.some((c) => m.accepts(c)));
  }

  // -- bookkeeping ----------------------------------------------------------
  /**
   * End the hand as a loss. Public because a driver that runs the turn loop
   * itself (the client, the autoplayer) has to be able to call it.
   */
  markFailed(reason, detail = {}) {
    this.state = HAND_STATE.FAILED;
    this._emit("hand_failed", { reason, score: handScore(this.hand), ...detail });
  }

  _emit(kind, detail = {}) {
    this.events.push({ kind, phase: this.phase, detail });
  }
}

// ---------------------------------------------------------------------------
// cards_short -- the autoplayer heuristic and difficulty probe
// ---------------------------------------------------------------------------

/**
 * Deficits past this are indistinguishable for heuristic purposes, so the
 * search stops there rather than proving exactly how bad a hopeless hand is.
 */
export const SHORT_CAP = 5;

/**
 * Collapse a hand to only what `spec` can actually discriminate on. SET and
 * RUN ignore color; COLOR ignores rank. Projecting onto the relevant axis makes
 * the cache hit constantly across discard candidates.
 */
function canonical(hand, spec) {
  const wilds = hand.filter(isWild).length;
  if (spec.some((g) => g.kind === GROUP.COLOR)) {
    const colors = hand.filter((c) => c.kind === "number").map((c) => c.color).sort();
    return `c|${colors.join(",")}|${wilds}`;
  }
  const ranks = hand
    .filter((c) => c.kind === "number")
    .map((c) => c.rank)
    .sort((a, b) => a - b);
  return `r|${ranks.join(",")}|${wilds}`;
}

function rebuild(key) {
  const [tag, values, wilds] = key.split("|");
  const parts = values === "" ? [] : values.split(",");
  const cards =
    tag === "r"
      ? parts.map((r) => numberCard(Number(r), COLORS[0]))
      : parts.map((c) => numberCard(1, c));
  for (let i = 0; i < Number(wilds); i++) cards.push({ ...WILD });
  return cards;
}

/** All ways to remove `deficit` cards across the groups of `spec`. */
function* reductions(spec, deficit) {
  if (spec.length === 1) {
    if (deficit <= spec[0].size) yield [deficit];
    return;
  }
  for (let first = 0; first <= Math.min(deficit, spec[0].size); first++) {
    for (const rest of reductions(spec.slice(1), deficit - first)) {
      yield [first, ...rest];
    }
  }
}

// Stands in for Python's @lru_cache(maxsize=300_000).
const SHORT_CACHE = new Map();
const SHORT_CACHE_MAX = 300000;

function cardsShortCached(key, spec, minNat, cap, specKey) {
  const memoKey = `${key}|${specKey}|${minNat}|${cap}`;
  const hit = SHORT_CACHE.get(memoKey);
  if (hit !== undefined) return hit;

  const hand = rebuild(key);
  const limit = Math.min(cap, phaseCardCount(spec));
  let answer = limit + 1;

  outer: for (let deficit = 0; deficit <= limit; deficit++) {
    for (const reduction of reductions(spec, deficit)) {
      const shrunk = spec
        .map((g, i) => ({ kind: g.kind, size: g.size - reduction[i] }))
        .filter((g) => g.size > 0);
      if (shrunk.length === 0) {
        answer = deficit;
        break outer;
      }
      if (solvePhase(hand, shrunk, minNat) !== null) {
        answer = deficit;
        break outer;
      }
    }
  }

  if (SHORT_CACHE.size >= SHORT_CACHE_MAX) SHORT_CACHE.clear();
  SHORT_CACHE.set(memoKey, answer);
  return answer;
}

/**
 * How many more useful cards this hand needs to satisfy `spec`.
 *
 * Computed by shrinking the phase until it becomes solvable. A relaxation used
 * as the autoplayer heuristic and as a difficulty probe -- not an exact edit
 * distance. Values above `cap` are reported as cap + 1.
 */
export function cardsShort(hand, spec, minNat = 1, cap = SHORT_CAP) {
  const specKey = spec.map((g) => `${g.kind}${g.size}`).join("+");
  return cardsShortCached(canonical(hand, spec), spec, minNat, cap, specKey);
}
