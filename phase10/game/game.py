"""A game: many hands, one running scorecard.

A `PhaseHand` is a single attempt at a single phase and knows nothing about
what came before it. This wraps a sequence of them so there is something to
carry a score, a round count and a history.

Scoring follows the printed rules -- you score the cards still in your hand
when the hand ends, and lower is better. Going out is therefore worth zero, a
phase laid down with junk left over costs whatever that junk is worth, and a
failed hand costs the lot.

Config is passed in per round rather than held, because Archipelago items keep
arriving: the deck and draw budget you play round nine with are not the ones you
played round one with.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .cards import hand_score
from .engine import GameConfig, HandState, PhaseHand


#: Bumped when the saved shape changes. A payload from a different version is
#: discarded rather than guessed at.
SAVE_VERSION = 1


@dataclass(frozen=True)
class RoundResult:
    number: int
    phase: int
    state: HandState
    score: int
    draws_used: int
    wilds_used: int
    skips_played: int

    @property
    def cleared(self) -> bool:
        return self.state in (HandState.PHASE_LAID, HandState.WENT_OUT)

    @property
    def went_out(self) -> bool:
        return self.state is HandState.WENT_OUT

    def __str__(self) -> str:
        if self.went_out:
            outcome = "went out"
        elif self.cleared:
            outcome = "cleared"
        else:
            outcome = "failed"
        # Spelled out rather than "r4": the scorecard is read at a glance and
        # a one-letter prefix is one more thing to decode.
        return (f"round {self.number:<3} phase {self.phase:<2} {outcome:<9} "
                f"{self.score:>4} pts  {self.draws_used} draws")


class Phase10Game:
    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()
        self.rounds: list[RoundResult] = []
        self.hand: PhaseHand | None = None

    # -- state -------------------------------------------------------------
    @property
    def round_number(self) -> int:
        """The round now being played, or the one that would start next."""
        return len(self.rounds) + 1

    @property
    def total_score(self) -> int:
        return sum(r.score for r in self.rounds)

    @property
    def rounds_won(self) -> int:
        return sum(1 for r in self.rounds if r.cleared)

    @property
    def cleared_phases(self) -> set[int]:
        return {r.phase for r in self.rounds if r.cleared}

    @property
    def best_round(self) -> RoundResult | None:
        cleared = [r for r in self.rounds if r.cleared]
        return min(cleared, key=lambda r: (r.score, r.draws_used)) if cleared else None

    def history_for(self, phase: int) -> list[RoundResult]:
        return [r for r in self.rounds if r.phase == phase]

    # -- play --------------------------------------------------------------
    def start_round(self, phase: int, config: GameConfig,
                    table=None) -> PhaseHand:
        if self.hand is not None and self.hand.state is HandState.IN_PROGRESS:
            raise RuntimeError(f"round {self.round_number} is still in progress")
        self.hand = PhaseHand(phase, config, self.rng, table=table)
        return self.hand

    def finish_round(self, hand: PhaseHand | None = None) -> RoundResult:
        hand = hand if hand is not None else self.hand
        if hand is None:
            raise RuntimeError("no round to finish")
        if hand.state is HandState.IN_PROGRESS:
            raise RuntimeError("round is still in progress")

        result = RoundResult(
            number=self.round_number,
            phase=hand.phase,
            state=hand.state,
            score=hand_score(hand.hand),
            draws_used=hand.draws_used,
            wilds_used=hand.used_wilds_in_layout,
            skips_played=hand.skips_played,
        )
        self.rounds.append(result)
        self.hand = None
        return result

    # -- persistence -------------------------------------------------------
    def to_payload(self) -> dict:
        return {
            "version": SAVE_VERSION,
            "rounds": [
                {
                    "number": r.number,
                    "phase": r.phase,
                    "state": r.state.value,
                    "score": r.score,
                    "draws_used": r.draws_used,
                    "wilds_used": r.wilds_used,
                    "skips_played": r.skips_played,
                }
                for r in self.rounds
            ],
        }

    def load_payload(self, payload: object) -> bool:
        """Restore rounds from a saved payload. Returns whether it took.

        The payload comes back off the network, so nothing in it is trusted:
        anything malformed, truncated or from another save version is discarded
        and the game simply starts fresh rather than half-loading.
        """
        if not isinstance(payload, dict) or payload.get("version") != SAVE_VERSION:
            return False
        raw_rounds = payload.get("rounds")
        if not isinstance(raw_rounds, list):
            return False

        restored: list[RoundResult] = []
        try:
            for raw in raw_rounds:
                restored.append(
                    RoundResult(
                        number=int(raw["number"]),
                        phase=int(raw["phase"]),
                        state=HandState(raw["state"]),
                        score=int(raw["score"]),
                        draws_used=int(raw["draws_used"]),
                        wilds_used=int(raw["wilds_used"]),
                        skips_played=int(raw["skips_played"]),
                    )
                )
        except (KeyError, TypeError, ValueError):
            return False

        self.rounds = restored
        return True

    def scorecard(self, limit: int = 10) -> list[str]:
        """Recent rounds plus the running totals, ready to print."""
        lines = [str(r) for r in self.rounds[-limit:]]
        if len(self.rounds) > limit:
            lines.insert(0, f"... {len(self.rounds) - limit} earlier round(s)")
        if not self.rounds:
            return ["No rounds played yet."]
        lines.append(
            f"{len(self.rounds)} rounds | {self.rounds_won} won | "
            f"{self.total_score} points total"
        )
        best = self.best_round
        if best is not None:
            lines.append(f"best: {best}")
        return lines
