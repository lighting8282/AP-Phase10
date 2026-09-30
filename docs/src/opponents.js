// Computer players sharing the table with you.
//
// Port of phase10/game/opponents.py. The two files have to agree turn for
// turn, so the policy here is written to mirror that one line by line rather
// than to read idiomatically -- opponents_test.mjs replays recorded Python
// turns through this to prove they still do.
//
// They exist to put a clock on the round that is not your draw budget. A round
// ends on whichever comes first: your draws running out, or somebody going out.
//
// Measured, those two clocks do not layer. One seat takes about eight turns to
// go out, but three race and the round ends on the fastest of them, which lands
// near turn five. So the race resolves before a large budget can matter -- see
// the Python module for the numbers and what was done about them.

import { cardToString, handScore, isSkip, points } from "./cards.js?v=35be1704";
import { cardsShort, removeCard } from "./engine.js?v=35be1704";
import { PHASES, describeMeldCards, solveMelds } from "./phases.js?v=35be1704";

/**
 * How well a seat plays. 1.0 / 0.0 is the greedy autoplayer exactly.
 *
 * Skill is a pair of probabilities over one policy rather than three separate
 * policies, so later difficulty levels stay a matter of numbers.
 */
export function opponentSkill(name, discardAwareness, discardError) {
  return Object.freeze({ name, discardAwareness, discardError });
}

/** Beats a careless human, loses to a careful one. */
export const MID = opponentSkill("mid", 0.7, 0.25);

/**
 * Seat names, in the order they are dealt in.
 *
 * Exported because a finished run has to name its winner between rounds, when
 * no table is dealt and there are no seats to ask.
 */
export const NAMES = ["Ada", "Bo", "Cy", "Del", "Eve", "Fen"];

export class Opponent {
  constructor(name, phase, config, random, skill = MID) {
    this.name = name;
    this.phase = phase;
    this.config = config;
    this.random = random;
    this.skill = skill;

    this.hand = [];
    // The groups this seat has on the table, face up. Kept rather than
    // discarded: the player needs to see what is down to judge whether they
    // could hit onto it, and without this the cards simply vanish from the
    // deck -- six of them, silently, the moment a seat lays.
    this.layout = [];
    // The same groups, with what each one means, so they can be hit on.
    this.melds = [];
    this.laidDown = false;
    this.wentOut = false;
    //: Set by a Skip played against this seat; consumed when its turn would
    //: have come round.
    this.skipped = false;
    // Where this seat's cards went, so the table can be reconciled against
    // the hand it was dealt: dealt + drew == placed + held + threw. A seat
    // going out with eight cards showing is the arithmetic a player tries to
    // do in their head and cannot, because the draws and the discards are not
    // on screen. `placed` counts cards put on the table anywhere, including
    // hits onto somebody else's group, which is why it is not the size of
    // this seat's own melds.
    this.drew = 0;
    this.threw = 0;
    this.placed = 0;
  }

  get spec() {
    return PHASES[this.phase];
  }

  /** What it is caught holding when the round ends. */
  get score() {
    return handScore(this.hand);
  }

  _short(hand) {
    return cardsShort(hand, this.spec, this.config.minNaturalsPerGroup);
  }

  _solution() {
    return solveMelds(this.hand, this.spec, this.config.minNaturalsPerGroup);
  }

  // -- policy ---------------------------------------------------------------
  _wantsDiscardTop(top) {
    if (top === null || top === undefined || !this.config.allowDiscardDraw) return false;
    if (this.random() > this.skill.discardAwareness) return false; // not looking
    return this._short([...this.hand, top]) < this._short(this.hand);
  }

  _chooseDiscard() {
    // Exclude by position, matching opponents.py. Identity works here only
    // because buildDeck happens to make a fresh object per copy; Python's
    // repeats one object, and the two must not diverge on that accident.
    // points is a function, not a property -- `a.points` is undefined, and
    // -undefined is NaN, which silently destroys the ordering.
    const keyed = this.hand.map((card, index) => ({
      card,
      index,
      short: this._short([...this.hand.slice(0, index), ...this.hand.slice(index + 1)]),
      points: -points(card),
    }));
    keyed.sort((a, b) => a.short - b.short || a.points - b.points || a.index - b.index);
    const ranked = keyed.map((k) => k.card);
    // A mistake is the second-best card, not a random one: a player who
    // misreads their hand still throws something plausible.
    if (ranked.length > 1 && this.random() < this.skill.discardError) return ranked[1];
    return ranked[0];
  }

  _tryLayDown(table = null) {
    if (this.laidDown) return;
    const melds = this._solution();
    if (melds === null) return;
    for (const meld of melds) {
      for (const card of meld.cards) {
        // By value, not identity: solvePhase materialises its own card
        // objects, so indexOf gives -1 and splice(-1, 1) would quietly
        // delete the last card in hand instead of the one laid down.
        removeCard(this.hand, card);
      }
    }
    this.melds = melds;
    this.layout = melds.map((m) => m.cards);
    this.laidDown = true;
    this.placed += melds.reduce((n, m) => n + m.cards.length, 0);
    if (table) {
      const groups = melds.map(describeMeldCards).join(", ");
      table.say(this.name, `lays down phase ${this.phase}: ${groups}`);
    }
  }

  // -- turn -----------------------------------------------------------------
  /**
   * Play one turn. Returns true if this seat went out.
   *
   * The same shape as the player's turn: draw one, lay the phase down if it
   * is there, hit what fits, throw one card.
   *
   * A seat that had laid down used to skip the draw and throw anyway, so its
   * hand fell by one every turn for nothing. That is not a turn anybody else
   * at the table can take: your own draw and discard cancel out, and hitting
   * is the only thing that shortens your hand. It made the seats go out about
   * two turns sooner than the rules allow, and it showed -- a seat went out
   * having laid eight of the ten cards it was dealt, an arithmetic nobody
   * watching could reproduce.
   *
   * The comment that justified it said a drawing seat "could never go out".
   * That was simply wrong: it goes out by hitting, which is how the player
   * does it, and _hitWhatItCan was already here. Measured over 400 rounds,
   * somebody still goes out in every one of them.
   */
  takeTurn(table) {
    if (this.wentOut) return false;
    if (!table.stock.length) return false;

    if (this._wantsDiscardTop(table.discardTop)) {
      const taken = table.discard.pop();
      this.hand.push(taken);
      table.say(this.name, `takes ${cardToString(taken)} from the discard`);
    } else {
      this.hand.push(table.stock.shift());
      // Not which card: it went into a hand you cannot see.
      table.say(this.name, "draws from the stock");
    }
    this.drew += 1;

    this._tryLayDown(table);
    if (this._finished()) {
      table.say(this.name, "goes out");
      return true;
    }

    // Hitting is the only thing that shortens a hand, so it is the whole road
    // from "down" to "out" -- onto any group on the table, its own or
    // anybody else's.
    if (this.laidDown) {
      this._hitWhatItCan(table);
      if (this._finished()) {
        table.say(this.name, "goes out");
        return true;
      }
    }

    const thrown = this._chooseThrow();
    table.discard.push(thrown);
    this.threw += 1;
    table.say(this.name, `discards ${cardToString(thrown)}`);
    // The printed rule, and the same one the player plays by: the Skip is the
    // discard, and whoever threw it says who loses a turn.
    if (isSkip(thrown) && this.config.skipMode === "deny") this._denySomebody(table);
    return this._finished();
  }

  /**
   * Lay every card that legally extends a group already on the table.
   *
   * Repeated rather than a single pass: hitting a run at one end opens the
   * next rank along, so one sweep would leave behind cards the very next
   * check would accept.
   */
  _hitWhatItCan(table) {
    let played = 0;
    let moved = true;
    while (moved && this.hand.length) {
      moved = false;
      for (const card of [...this.hand]) {
        for (const meld of table.allMelds()) {
          if (meld.accepts(card)) {
            removeCard(this.hand, card);
            meld.add(card);
            this.placed += 1;
            table.say(this.name,
              `plays ${cardToString(card)} onto ${describeMeldCards(meld)}`);
            played += 1;
            moved = true;
            break;
          }
        }
        if (moved) break;
      }
    }
    return played;
  }

  /** Throw the most expensive card; nothing left is worth building on. */
  _shed() {
    let worst = this.hand[0];
    for (const card of this.hand) if (points(card) > points(worst)) worst = card;
    removeCard(this.hand, worst);
    return worst;
  }

  _takeChosenDiscard() {
    const card = this._chooseDiscard();
    removeCard(this.hand, card);
    return card;
  }

  /**
   * What to throw this turn.
   *
   * A Skip first, where a Skip denies: it is the only card in hand that does
   * something on the way out, it is never part of a phase, and it costs
   * fifteen to be caught with. Otherwise the usual choice -- down, the phase
   * is safe and only points in hand matter; still building, it is about what
   * the phase still needs.
   */
  _chooseThrow() {
    if (this.config.skipMode === "deny") {
      const skip = this.hand.find(isSkip);
      if (skip) {
        removeCard(this.hand, skip);
        return skip;
      }
    }
    return this.laidDown ? this._shed() : this._takeChosenDiscard();
  }

  /**
   * Aim a thrown Skip at whoever is closest to going out.
   *
   * The player counts, and is usually the answer: a seat that has laid down
   * and holds two cards is one turn from ending the round, and so are you.
   * Denying the next seat round the table instead would be the safe-looking
   * choice and the wrong one.
   *
   * Everything read here is face up -- whether somebody is down, and how many
   * cards they hold -- so this is not the seat looking at hands it cannot see.
   * A mistake is the second-best target rather than a random one, the same
   * shape the discard chooser uses: a player who misjudges the table still
   * denies somebody plausible.
   */
  _denySomebody(table) {
    const targets = table.denyTargets(this);
    // Nobody left to deny. The Skip is spent either way, which is what the
    // player's own throw does in the same spot.
    if (!targets.length) return null;
    const down = (t) => (t.laidDown === undefined ? t.laid : t.laidDown);
    const ranked = targets
      .map((target, order) => ({ target, order }))
      .sort((a, b) => (down(b.target) - down(a.target))
        || (a.target.hand.length - b.target.hand.length)
        || (a.order - b.order))
      .map((k) => k.target);
    const pick = ranked.length > 1 && this.random() < this.skill.discardError
      ? ranked[1]
      : ranked[0];
    pick.skipped = true;
    table.say(this.name, pick === table.player
      ? "makes you miss a turn"
      : `makes ${pick.name} miss a turn`);
    return pick;
  }

  _finished() {
    if (this.laidDown && !this.hand.length) this.wentOut = true;
    return this.wentOut;
  }
}

/** Seat `count` opponents, each on its own phase. */
export function buildOpponents(count, phases, config, random, skill = MID) {
  const seats = phases ?? new Array(count).fill(1);
  const out = [];
  for (let i = 0; i < count; i += 1) {
    out.push(new Opponent(NAMES[i % NAMES.length], seats[i], config, random, skill));
  }
  return out;
}
