"""The bridge between engine state and Archipelago.

Everything here is pure: no sockets, no async, no CommonClient. That is what
makes the interesting parts -- how received items become a GameConfig, and which
location IDs a finished hand is worth -- testable without standing up a server.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..data import (
    BASE_HAND_SIZE,
    EXTRA_DRAW,
    HAND_SIZE_UPGRADE,
    HANDS_WON_MILESTONES,
    LEAN_DEAL,
    LOCATION_NAME_TO_ID,
    MAX_SKIPS,
    PHASE_LOCK,
    PHASE_UNLOCK,
    SKIP_CARD,
    TIERS,
    WILD_CARD,
    WILD_THEFT,
    milestone_location_name,
    phase_location_name,
)
from ..game.cards import STOCK_WILDS
from ..game.engine import GameConfig, HandState, PhaseHand
from ..game.game import SAVE_VERSION, Phase10Game, RoundResult

#: Traps are one-shot. Received counts only ever grow, so pending effects are
#: tracked as (received - consumed) rather than by mutating the counts.
TRAP_NAMES = (PHASE_LOCK, LEAN_DEAL, WILD_THEFT)

LEAN_DEAL_PENALTY = 2


@dataclass
class Phase10Session:
    goal: int = 0
    starting_draws: int = 4
    checks_per_phase: int = 4
    death_link: bool = False

    items: Counter = field(default_factory=Counter)
    consumed_traps: Counter = field(default_factory=Counter)
    checked_locations: set[int] = field(default_factory=set)
    locked_phase: int | None = None
    last_result: RoundResult | None = None
    game: Phase10Game = field(default_factory=Phase10Game)

    @classmethod
    def from_slot_data(cls, slot_data: Mapping[str, Any], rng=None) -> Phase10Session:
        return cls(
            goal=int(slot_data.get("goal", 0)),
            starting_draws=int(slot_data.get("starting_draws", 4)),
            checks_per_phase=int(slot_data.get("checks_per_phase", 4)),
            death_link=bool(slot_data.get("death_link", False)),
            game=Phase10Game(rng),
        )

    # The game owns the running state; the session keeps one source of truth
    # rather than a second tally that could drift from the scorecard.
    @property
    def hand(self) -> PhaseHand | None:
        return self.game.hand

    @property
    def hands_won(self) -> int:
        return self.game.rounds_won

    @property
    def cleared_phases(self) -> set[int]:
        return self.game.cleared_phases

    @property
    def total_score(self) -> int:
        return self.game.total_score

    # -- items -------------------------------------------------------------
    def set_items(self, item_names: list[str]) -> None:
        """Replace the received-item tally. AP resends the full list, so this
        is idempotent rather than incremental."""
        self.items = Counter(item_names)

    def pending(self, trap: str) -> int:
        return max(0, self.items[trap] - self.consumed_traps[trap])

    @property
    def unlocked_phases(self) -> set[int]:
        return {p for p in range(1, 11) if self.items[PHASE_UNLOCK.format(p)]}

    # -- configuration -----------------------------------------------------
    @property
    def config(self) -> GameConfig:
        """Build the engine's knobs from what Archipelago has handed over."""
        hand_size = BASE_HAND_SIZE + self.items[HAND_SIZE_UPGRADE]
        wilds = min(self.items[WILD_CARD], STOCK_WILDS)
        draws = self.starting_draws + self.items[EXTRA_DRAW]

        if self.pending(LEAN_DEAL):
            hand_size -= LEAN_DEAL_PENALTY
        if self.pending(WILD_THEFT):
            wilds -= 1

        return GameConfig(
            hand_size=max(4, hand_size),
            wilds_in_deck=max(0, min(wilds, STOCK_WILDS)),
            max_draws=max(1, draws),
            starting_skips=min(self.items[SKIP_CARD], MAX_SKIPS),
        )

    # -- playing -----------------------------------------------------------
    def can_play(self, phase: int) -> str | None:
        """Returns None if the phase is playable, else why not."""
        if phase not in self.unlocked_phases:
            return f"Phase {phase} is not unlocked yet."
        if self.locked_phase is not None and phase != self.locked_phase:
            return f"A Phase Lock trap is forcing you to replay Phase {self.locked_phase}."
        return None

    def start_hand(self, phase: int) -> PhaseHand:
        refusal = self.can_play(phase)
        if refusal:
            raise ValueError(refusal)

        config = self.config
        # Consume the one-shot traps that shaped this hand.
        for trap in (LEAN_DEAL, WILD_THEFT):
            if self.pending(trap):
                self.consumed_traps[trap] += 1

        return self.game.start_round(phase, config)

    def kill_hand(self) -> PhaseHand | None:
        """Fail the hand in progress, if there is one.

        A card game has nothing to kill, so a DeathLink death is a lost hand.
        Between rounds there is nothing to lose and an incoming death passes
        harmlessly -- returning None says so, rather than inventing a penalty
        the player cannot see coming.
        """
        hand = self.hand
        if hand is None or hand.state is not HandState.IN_PROGRESS:
            return None
        hand.mark_failed("death_link")
        return hand

    def earned_tiers(self, hand: PhaseHand) -> list[str]:
        """Which check tiers a finished hand is worth."""
        if hand.state not in (HandState.PHASE_LAID, HandState.WENT_OUT):
            return []

        tiers = ["Cleared"]
        if hand.state is HandState.WENT_OUT:
            tiers.append("Went Out")
        if hand.used_wilds_in_layout == 0:
            tiers.append("No Wilds")
        if hand.draws_used <= max(1, hand.config.max_draws // 2):
            tiers.append("Under Par")

        # Tiers the player's options did not create locations for must never be
        # reported -- the IDs would not exist on the server.
        allowed = set(TIERS[: self.checks_per_phase])
        return [tier for tier in tiers if tier in allowed]

    def finish_hand(self, hand: PhaseHand) -> list[int]:
        """Settle a finished hand. Returns newly checked location IDs."""
        tiers = self.earned_tiers(hand)
        result = self.game.finish_round(hand)
        self.last_result = result

        names: list[str] = []
        if result.cleared:
            self.locked_phase = None
            names += [phase_location_name(result.phase, tier) for tier in tiers]
            names += [
                milestone_location_name(n)
                for n in HANDS_WON_MILESTONES
                if n <= self.hands_won
            ]
        elif self.pending(PHASE_LOCK):
            # A failed hand under a Phase Lock pins you to this phase.
            self.consumed_traps[PHASE_LOCK] += 1
            self.locked_phase = result.phase

        new = [
            LOCATION_NAME_TO_ID[name]
            for name in names
            if LOCATION_NAME_TO_ID[name] not in self.checked_locations
        ]
        self.checked_locations.update(new)
        return new

    # -- persistence -------------------------------------------------------
    def to_payload(self) -> dict:
        """Everything the server does not already know.

        Checked locations are deliberately left out: the server is the
        authority on those, and writing our own copy back would only create
        something that could disagree with it.
        """
        return {
            "version": SAVE_VERSION,
            "game": self.game.to_payload(),
            "consumed_traps": {k: int(v) for k, v in self.consumed_traps.items() if v},
            "locked_phase": self.locked_phase,
        }

    def load_payload(self, payload: object) -> bool:
        """Restore from a saved payload. Returns whether it took.

        Treated as untrusted input -- it arrives over the network and a partial
        restore would be worse than none.
        """
        if not isinstance(payload, dict) or payload.get("version") != SAVE_VERSION:
            return False
        if not self.game.load_payload(payload.get("game")):
            return False

        traps = payload.get("consumed_traps")
        if isinstance(traps, dict):
            try:
                self.consumed_traps = Counter(
                    {str(k): int(v) for k, v in traps.items()}
                )
            except (TypeError, ValueError):
                self.consumed_traps = Counter()

        locked = payload.get("locked_phase")
        self.locked_phase = locked if isinstance(locked, int) and 1 <= locked <= 10 else None
        return True

    # -- goal --------------------------------------------------------------
    @property
    def goal_met(self) -> bool:
        if self.goal == 1:  # phase_ten
            return 10 in self.cleared_phases
        return len(self.cleared_phases) == 10
