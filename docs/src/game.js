/**
 * A game: many hands, one running scorecard.
 *
 * A direct port of phase10/game/game.py.
 *
 * A PhaseHand is a single attempt at a single phase and knows nothing about
 * what came before it. This wraps a sequence of them so there is something to
 * carry a score, a round count and a history.
 *
 * Scoring follows the printed rules -- you score the cards still in your hand
 * when the hand ends, and lower is better. Going out is therefore worth zero,
 * a phase laid down with junk left over costs whatever that junk is worth, and
 * a failed hand costs the lot.
 *
 * Config is passed in per round rather than held, because Archipelago items
 * keep arriving: the deck and draw budget you play round nine with are not the
 * ones you played round one with.
 */

import { handScore } from "./cards.js";
import { HAND_STATE, PhaseHand } from "./engine.js";

/**
 * Bumped when the saved shape changes. A payload from a different version is
 * discarded rather than guessed at.
 */
export const SAVE_VERSION = 1;

const CLEARED_STATES = new Set([HAND_STATE.PHASE_LAID, HAND_STATE.WENT_OUT]);

export function roundCleared(result) {
  return CLEARED_STATES.has(result.state);
}

export function roundWentOut(result) {
  return result.state === HAND_STATE.WENT_OUT;
}

export function roundToString(r) {
  const outcome = roundWentOut(r) ? "went out" : roundCleared(r) ? "cleared" : "failed";
  return (
    // Spelled out rather than "r4": the scorecard is read at a glance and a
    // one-letter prefix is one more thing to decode.
    `round ${String(r.number).padEnd(3)} phase ${String(r.phase).padEnd(2)} ` +
    `${outcome.padEnd(9)} ${String(r.score).padStart(4)} pts  ${r.drawsUsed} draws`
  );
}

export class Phase10Game {
  /** @param {object} [opts] opts.random -- RNG in [0,1) used to deal rounds. */
  constructor(opts = {}) {
    this.random = opts.random ?? Math.random;
    this.rounds = [];
    this.hand = null;
  }

  // -- state ----------------------------------------------------------------
  /** The round now being played, or the one that would start next. */
  get roundNumber() {
    return this.rounds.length + 1;
  }

  get totalScore() {
    return this.rounds.reduce((n, r) => n + r.score, 0);
  }

  get roundsWon() {
    return this.rounds.filter(roundCleared).length;
  }

  get clearedPhases() {
    return new Set(this.rounds.filter(roundCleared).map((r) => r.phase));
  }

  get bestRound() {
    const cleared = this.rounds.filter(roundCleared);
    if (!cleared.length) return null;
    return cleared.reduce((best, r) => {
      if (r.score !== best.score) return r.score < best.score ? r : best;
      return r.drawsUsed < best.drawsUsed ? r : best;
    });
  }

  historyFor(phase) {
    return this.rounds.filter((r) => r.phase === phase);
  }

  // -- play -----------------------------------------------------------------
  startRound(phase, config, opts = {}) {
    if (this.hand !== null && this.hand.state === HAND_STATE.IN_PROGRESS) {
      throw new Error(`round ${this.roundNumber} is still in progress`);
    }
    this.hand = new PhaseHand(phase, config, { random: this.random, ...opts });
    return this.hand;
  }

  finishRound(hand = null) {
    const h = hand ?? this.hand;
    if (h === null) throw new Error("no round to finish");
    if (h.state === HAND_STATE.IN_PROGRESS) throw new Error("round is still in progress");

    const result = {
      number: this.roundNumber,
      phase: h.phase,
      state: h.state,
      score: handScore(h.hand),
      drawsUsed: h.drawsUsed,
      wildsUsed: h.usedWildsInLayout,
      skipsPlayed: h.skipsPlayed,
    };
    this.rounds.push(result);
    this.hand = null;
    return result;
  }

  // -- persistence ----------------------------------------------------------
  toPayload() {
    return {
      version: SAVE_VERSION,
      rounds: this.rounds.map((r) => ({
        number: r.number,
        phase: r.phase,
        state: r.state,
        score: r.score,
        draws_used: r.drawsUsed,
        wilds_used: r.wildsUsed,
        skips_played: r.skipsPlayed,
      })),
    };
  }

  /**
   * Restore rounds from a saved payload. Returns whether it took.
   *
   * The payload comes back off the network, so nothing in it is trusted:
   * anything malformed, truncated or from another save version is discarded
   * and the game simply starts fresh rather than half-loading.
   */
  loadPayload(payload) {
    if (
      payload === null ||
      typeof payload !== "object" ||
      Array.isArray(payload) ||
      payload.version !== SAVE_VERSION
    ) {
      return false;
    }
    const raw = payload.rounds;
    if (!Array.isArray(raw)) return false;

    const states = new Set(Object.values(HAND_STATE));
    const restored = [];
    for (const entry of raw) {
      if (entry === null || typeof entry !== "object") return false;
      const number = toInt(entry.number);
      const phase = toInt(entry.phase);
      const score = toInt(entry.score);
      const drawsUsed = toInt(entry.draws_used);
      const wildsUsed = toInt(entry.wilds_used);
      const skipsPlayed = toInt(entry.skips_played);
      if ([number, phase, score, drawsUsed, wildsUsed, skipsPlayed].some((v) => v === null)) {
        return false;
      }
      if (!states.has(entry.state)) return false;
      restored.push({
        number, phase, state: entry.state, score, drawsUsed, wildsUsed, skipsPlayed,
      });
    }
    this.rounds = restored;
    return true;
  }

  /** Recent rounds plus the running totals, ready to print. */
  scorecard(limit = 10) {
    if (!this.rounds.length) return ["No rounds played yet."];
    const lines = this.rounds.slice(-limit).map(roundToString);
    if (this.rounds.length > limit) {
      lines.unshift(`... ${this.rounds.length - limit} earlier round(s)`);
    }
    lines.push(
      `${this.rounds.length} rounds | ${this.roundsWon} won | ${this.totalScore} points total`
    );
    const best = this.bestRound;
    if (best !== null) lines.push(`best: ${roundToString(best)}`);
    return lines;
  }
}

/** int() with Python's strictness: reject anything not cleanly an integer. */
function toInt(value) {
  if (typeof value === "boolean") return null;
  if (typeof value === "number") return Number.isInteger(value) ? value : null;
  if (typeof value === "string" && /^-?\d+$/.test(value.trim())) return Number(value);
  return null;
}
