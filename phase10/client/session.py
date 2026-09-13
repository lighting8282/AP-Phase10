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
    PHASE_LOCK,
    PHASE_UNLOCK,
    STOCK_SKIPS,
    TIERS,
    WILD_CARD,
    WILD_THEFT,
    milestone_location_name,
    phase_location_name,
)
from ..game.cards import STOCK_WILDS
from ..game.engine import GameConfig, HandState, PhaseHand

#: Traps are one-shot. Received counts only ever grow, so pending effects are
#: tracked as (received - consumed) rather than by mutating the counts.
TRAP_NAMES = (PHASE_LOCK, LEAN_DEAL, WILD_THEFT)

LEAN_DEAL_PENALTY = 2


@dataclass
class Phase10Session:
    goal: int = 0
    starting_draws: int = 4
    checks_per_phase: int = 4
    include_skips: bool = False

    items: Counter = field(default_factory=Counter)
    consumed_traps: Counter = field(default_factory=Counter)
    hands_won: int = 0
    cleared_phases: set[int] = field(default_factory=set)
    checked_locations: set[int] = field(default_factory=set)
    locked_phase: int | None = None
    hand: PhaseHand | None = None

    @classmethod
    def from_slot_data(cls, slot_data: Mapping[str, Any]) -> Phase10Session:
        return cls(
            goal=int(slot_data.get("goal", 0)),
            starting_draws=int(slot_data.get("starting_draws", 4)),
            checks_per_phase=int(slot_data.get("checks_per_phase", 4)),
            include_skips=bool(slot_data.get("include_skips", False)),
        )

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
            skips_in_deck=STOCK_SKIPS if self.include_skips else 0,
            max_draws=max(1, draws),
        )

    # -- playing -----------------------------------------------------------
    def can_play(self, phase: int) -> str | None:
        """Returns None if the phase is playable, else why not."""
        if phase not in self.unlocked_phases:
            return f"Phase {phase} is not unlocked yet."
        if self.locked_phase is not None and phase != self.locked_phase:
            return f"A Phase Lock trap is forcing you to replay Phase {self.locked_phase}."
        return None

    def start_hand(self, phase: int, rng) -> PhaseHand:
        refusal = self.can_play(phase)
        if refusal:
            raise ValueError(refusal)

        config = self.config
        # Consume the one-shot traps that shaped this hand.
        for trap in (LEAN_DEAL, WILD_THEFT):
            if self.pending(trap):
                self.consumed_traps[trap] += 1

        self.hand = PhaseHand(phase, config, rng)
        return self.hand

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
        names: list[str] = []
        cleared = hand.state in (HandState.PHASE_LAID, HandState.WENT_OUT)

        if cleared:
            self.cleared_phases.add(hand.phase)
            self.hands_won += 1
            self.locked_phase = None
            names += [phase_location_name(hand.phase, tier) for tier in self.earned_tiers(hand)]
            names += [
                milestone_location_name(n)
                for n in HANDS_WON_MILESTONES
                if n <= self.hands_won
            ]
        elif self.pending(PHASE_LOCK):
            # A failed hand under a Phase Lock pins you to this phase.
            self.consumed_traps[PHASE_LOCK] += 1
            self.locked_phase = hand.phase

        new = [
            LOCATION_NAME_TO_ID[name]
            for name in names
            if LOCATION_NAME_TO_ID[name] not in self.checked_locations
        ]
        self.checked_locations.update(new)
        self.hand = None
        return new

    # -- goal --------------------------------------------------------------
    @property
    def goal_met(self) -> bool:
        if self.goal == 1:  # phase_ten
            return 10 in self.cleared_phases
        return len(self.cleared_phases) == 10
