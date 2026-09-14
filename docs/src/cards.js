/**
 * Card model and deck construction.
 *
 * A direct port of phase10/game/cards.py. The Python engine stays the
 * reference implementation -- tools/export_fixtures.py emits its verdicts and
 * test/crosscheck.mjs proves this port agrees with them.
 *
 * Stock deck is 108 cards: numbers 1-12 in four colors, two copies each (96),
 * plus 8 Wilds and 4 Skips. Deck composition is configurable because the AP
 * items "Wild Card" and "Skip Card" literally add cards to the draw pile.
 */

export const MIN_RANK = 1;
export const MAX_RANK = 12;
export const COPIES_PER_RANK = 2;

export const STOCK_WILDS = 8;
export const STOCK_SKIPS = 4;

/** Declaration order matters: _solveColor returns the first colour that fits. */
export const COLORS = ["red", "blue", "green", "yellow"];

export const KIND = {
  NUMBER: "number",
  WILD: "wild",
  SKIP: "skip",
};

export function numberCard(rank, color) {
  if (rank < MIN_RANK || rank > MAX_RANK) {
    throw new RangeError(`rank ${rank} out of range`);
  }
  if (!COLORS.includes(color)) {
    throw new RangeError(`unknown color ${color}`);
  }
  return { kind: KIND.NUMBER, rank, color };
}

export const WILD = Object.freeze({ kind: KIND.WILD, rank: null, color: null });
export const SKIP = Object.freeze({ kind: KIND.SKIP, rank: null, color: null });

export const isNumber = (c) => c.kind === KIND.NUMBER;
export const isWild = (c) => c.kind === KIND.WILD;
export const isSkip = (c) => c.kind === KIND.SKIP;

/** Official scoring: 1-9 = 5, 10-12 = 10, Skip = 15, Wild = 25. */
export function points(card) {
  if (card.kind === KIND.WILD) return 25;
  if (card.kind === KIND.SKIP) return 15;
  return card.rank <= 9 ? 5 : 10;
}

export function handScore(cards) {
  return cards.reduce((total, c) => total + points(c), 0);
}

/** Matches Card.__str__ in the Python model, so traces line up. */
export function cardToString(card) {
  if (card.kind === KIND.WILD) return "W";
  if (card.kind === KIND.SKIP) return "S";
  return `${card.rank}${card.color[0].toUpperCase()}`;
}

/** Inverse of cardToString -- used to read fixtures emitted by Python. */
export function cardFromString(s) {
  if (s === "W") return { ...WILD };
  if (s === "S") return { ...SKIP };
  const m = /^(\d{1,2})([RBGY])$/.exec(s);
  if (!m) throw new Error(`cannot parse card ${JSON.stringify(s)}`);
  const color = COLORS.find((c) => c[0].toUpperCase() === m[2]);
  return numberCard(Number(m[1]), color);
}

/** Filename of a card's rendered face. Mirrors cards.card_filename. */
export function cardFilename(card) {
  if (card.kind === KIND.WILD) return "wild.png";
  if (card.kind === KIND.SKIP) return "skip.png";
  return `${card.color}_${String(card.rank).padStart(2, "0")}.png`;
}

export function buildDeck(wilds = STOCK_WILDS, skips = STOCK_SKIPS) {
  if (wilds < 0 || wilds > STOCK_WILDS) {
    throw new RangeError(`wilds must be 0..${STOCK_WILDS}, got ${wilds}`);
  }
  if (skips < 0 || skips > STOCK_SKIPS) {
    throw new RangeError(`skips must be 0..${STOCK_SKIPS}, got ${skips}`);
  }
  const deck = [];
  for (let rank = MIN_RANK; rank <= MAX_RANK; rank++) {
    for (const color of COLORS) {
      for (let i = 0; i < COPIES_PER_RANK; i++) deck.push(numberCard(rank, color));
    }
  }
  for (let i = 0; i < wilds; i++) deck.push({ ...WILD });
  for (let i = 0; i < skips; i++) deck.push({ ...SKIP });
  return deck;
}
