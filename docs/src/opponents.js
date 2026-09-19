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

import { handScore, points } from "./cards.js";
import { cardsShort, removeCard } from "./engine.js";
import { PHASES, solvePhase } from "./phases.js";

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

const NAMES = ["Ada", "Bo", "Cy", "Del", "Eve", "Fen"];

export class Opponent {
  constructor(name, phase, config, random, skill = MID) {
    this.name = name;
    this.phase = phase;
    this.config = config;
    this.random = random;
    this.skill = skill;

    this.hand = [];
    this.laidDown = false;
    this.wentOut = false;
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
    return solvePhase(this.hand, this.spec, this.config.minNaturalsPerGroup);
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

  _tryLayDown() {
    if (this.laidDown) return;
    const layout = this._solution();
    if (layout === null) return;
    for (const group of layout) {
      for (const card of group) {
        // By value, not identity: solvePhase materialises its own card
        // objects, so indexOf gives -1 and splice(-1, 1) would quietly
        // delete the last card in hand instead of the one laid down.
        removeCard(this.hand, card);
      }
    }
    this.laidDown = true;
  }

  // -- turn -----------------------------------------------------------------
  /** Play one turn. Returns true if this seat went out. */
  takeTurn(table) {
    if (this.wentOut) return false;
    if (!table.stock.length) return false;

    this._tryLayDown();
    if (this._finished()) return true;

    if (this.laidDown) {
      // Already down: shed, do not draw. Drawing one and discarding one leaves
      // the hand the same size forever, so a seat that has laid down could
      // never go out. Real Phase 10 sheds by hitting onto groups already on
      // the table; until that exists, one card a turn and no draw is the
      // conservative stand-in -- slower than the real thing, not faster.
      table.discard.push(this._shed());
      return this._finished();
    }

    if (this._wantsDiscardTop(table.discardTop)) {
      this.hand.push(table.discard.pop());
    } else {
      this.hand.push(table.stock.shift());
    }

    this._tryLayDown();
    if (this._finished()) return true;

    table.discard.push(this._takeChosenDiscard());
    return this._finished();
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
