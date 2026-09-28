// Computer players sharing the table with you.
//
// Port of phase10/game/opponents.py. The two files have to agree turn for
// turn, so the policy here is written to mirror that one line by line rather
// than to read idiomatically -- opponents_test.mjs replays recorded Python
// turns through this to prove they still do.
//
// The one thing here that Python has no counterpart for is the turn narration
// (`lastTurn`, `turnSummary`): it records what a seat did, it decides nothing,
// and it exists for a browser log the Kivy client does not have.
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
import { PHASES, solveMelds } from "./phases.js";

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

/**
 * A card as a person would say it, for the turn narration.
 *
 * Not cardToString: "9B" is a trace format, and the log is read at the speed
 * of a sentence.
 */
function spell(card) {
  if (card.kind === "wild") return "a Wild";
  if (card.kind === "skip") return "a Skip";
  return `the ${card.rank} ${card.color}`;
}

/** "a, b and c" -- one sentence rather than a list of three. */
function joinParts(parts) {
  if (parts.length <= 1) return parts.join("");
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

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
    // What this seat did on its most recent turn, in the order it did it.
    // Recorded rather than derived: by the time the table has been redrawn the
    // draw and the discard are indistinguishable from each other, and a player
    // watching three seats move needs to be told which of them took their card
    // off the discard pile.
    this.lastTurn = [];
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

  _tryLayDown() {
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
    this.lastTurn.push(`laid phase ${this.phase} down`);
  }

  // -- turn -----------------------------------------------------------------
  /** Play one turn. Returns true if this seat went out. */
  takeTurn(table) {
    this.lastTurn = [];
    if (this.wentOut) return false; // already out: nothing to narrate
    if (!table.stock.length) {
      this.lastTurn.push("could not move -- the stock is empty");
      return false;
    }

    this._tryLayDown();
    if (this._finished()) return true;

    if (this.laidDown) {
      // Already down: hit everything that legally extends a group on the
      // table -- its own or anybody else's -- and throw one card besides.
      // Drawing one and discarding one would leave the hand the same size
      // forever, so a seat that had laid down could never go out.
      const hits = this._hitWhatItCan(table);
      if (hits) this.lastTurn.push(`hit ${hits} card${hits === 1 ? "" : "s"} onto the table`);
      if (this._finished()) return true;
      if (this.hand.length) {
        const shed = this._shed();
        table.discard.push(shed);
        this.lastTurn.push(`discarded ${spell(shed)}`);
      }
      return this._finished();
    }

    if (this._wantsDiscardTop(table.discardTop)) {
      const taken = table.discard.pop();
      this.hand.push(taken);
      this.lastTurn.push(`took ${spell(taken)} off the discard pile`);
    } else {
      this.hand.push(table.stock.shift());
      this.lastTurn.push("drew from the stock");
    }

    this._tryLayDown();
    if (this._finished()) return true;

    const thrown = this._takeChosenDiscard();
    table.discard.push(thrown);
    this.lastTurn.push(`discarded ${spell(thrown)}`);
    return this._finished();
  }

  /**
   * The last turn as one line of the log, or null if the seat did nothing.
   *
   * null rather than "Ada passed": a seat that is already out sits out every
   * remaining turn of the round, and a line per seat per turn saying so buries
   * the ones that moved.
   */
  turnSummary() {
    if (!this.lastTurn.length) return null;
    return `${this.name} ${joinParts(this.lastTurn)}.`;
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

  _finished() {
    // Recorded here rather than in takeTurn: a seat goes out at whichever of
    // four points in the turn empties its hand, and this is the one line all
    // four pass through, so the narration lands in the right order once.
    if (this.laidDown && !this.hand.length) {
      if (!this.wentOut) this.lastTurn.push("went out");
      this.wentOut = true;
    }
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
