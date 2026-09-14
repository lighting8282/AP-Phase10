"""Archipelago client for AP_Phase10.

The game is played through commands in the client console rather than a bespoke
GUI -- a card game reads fine as text, and it keeps everything in one process
with no rendering layer to maintain.

Commands run on the UI thread while sending is async, so checks are queued here
and drained by phase10_loop rather than awaited inline.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

from CommonClient import (
    ClientCommandProcessor,
    CommonContext,
    logger,
    server_loop,
)
from NetUtils import ClientStatus

from ..data import GAME_NAME
from ..game.autoplay import play_out
from ..game.engine import HandState
from ..game.phases import PHASES, phase_description
from .session import Phase10Session


def render_hand(hand) -> str:
    return "  ".join(f"[{i}]{card}" for i, card in enumerate(hand.hand))


def render_group(index: int, group) -> str:
    cards = " ".join(str(c) for c in group)
    return f"  group {index}  {cards}"


class Phase10CommandProcessor(ClientCommandProcessor):
    ctx: Phase10Context

    def _require_hand(self):
        hand = self.ctx.session.hand
        if hand is None or hand.state is not HandState.IN_PROGRESS:
            self.output("No hand in progress. Start one with /play <phase>.")
            return None
        return hand

    def _cmd_phases(self) -> None:
        """List every phase, what it needs, and whether it is available."""
        s = self.ctx.session
        unlocked = s.unlocked_phases
        for phase in range(1, 11):
            if phase in s.cleared_phases:
                mark = "done"
            elif phase in unlocked:
                mark = "open"
            else:
                mark = "  --"
            self.output(f"  {mark}  Phase {phase:>2}: {phase_description(phase)}")

    def _cmd_status(self) -> None:
        """Show the deck and draw budget your items have built."""
        s = self.ctx.session
        c = s.config
        self.output(
            f"hand size {c.hand_size} | wilds in deck {c.wilds_in_deck} "
            f"| draws per hand {c.max_draws} | skips per hand {c.starting_skips}"
        )
        self.output(
            f"phases unlocked {len(s.unlocked_phases)}/10 "
            f"| cleared {len(s.cleared_phases)}/10 | hands won {s.hands_won}"
        )
        self.output(
            f"round {s.game.round_number} | {s.hands_won} won | "
            f"{s.total_score} points (lower is better)"
        )
        if s.locked_phase:
            self.output(f"Phase Lock: you must replay Phase {s.locked_phase}.")

    def _cmd_play(self, phase: str) -> None:
        """Start a hand for the given phase. Usage: /play 3"""
        try:
            number = int(phase)
            if number not in PHASES:
                raise ValueError
        except ValueError:
            self.output("Give a phase number from 1 to 10.")
            return
        try:
            self.ctx.session.start_hand(number)
        except ValueError as e:
            self.output(str(e))
            return
        self.output(f"Phase {number}: {phase_description(number)}")
        self._cmd_hand()

    def _cmd_hand(self) -> None:
        """Show your hand, the discard top, and your remaining draws."""
        hand = self.ctx.session.hand
        if hand is None:
            self.output("No hand in progress. Start one with /play <phase>.")
            return
        self.output(render_hand(hand))
        self.output(
            f"discard top {hand.discard_top} | draws left {hand.draws_left} "
            f"| stock {len(hand.stock)}"
        )
        if hand.skips_in_hand:
            self.output(f"{hand.skips_in_hand} Skip(s) in hand -- /skip digs for free")
        if hand.can_lay_down():
            self.output("You can lay this phase down now: /lay")

    def _cmd_draw(self, source: str = "") -> None:
        """Draw a card. Plain /draw takes stock, /draw d takes the discard."""
        hand = self._require_hand()
        if hand is None:
            return
        try:
            card = hand.draw(from_discard=source.lower().startswith("d"))
        except RuntimeError as e:
            self.output(str(e))
            return
        self.output(f"drew {card}")
        self._cmd_hand()

    def _cmd_discard(self, index: str) -> None:
        """Discard by position. Usage: /discard 4"""
        hand = self._require_hand()
        if hand is None:
            return
        try:
            card = hand.hand[int(index)]
        except (ValueError, IndexError):
            self.output(f"Pick a position between 0 and {len(hand.hand) - 1}.")
            return
        try:
            hand.discard_card(card)
        except RuntimeError as e:
            self.output(str(e))
            return
        self.output(f"discarded {card}")
        if hand.state is HandState.FAILED:
            self.ctx.settle(hand)
        else:
            self._cmd_hand()

    def _cmd_skip(self) -> None:
        """Spend a Skip to look at the top of the draw pile. Then /take <i>."""
        hand = self._require_hand()
        if hand is None:
            return
        try:
            options = hand.play_skip()
        except RuntimeError as e:
            self.output(str(e))
            return
        shown = "  ".join(f"[{i}]{c}" for i, c in enumerate(options))
        self.output(f"top of the pile: {shown}")
        self.output("Keep one with /take <i>; the rest go to the bottom.")

    def _cmd_take(self, index: str) -> None:
        """Keep one of the cards a Skip revealed. Usage: /take 1"""
        hand = self.ctx.session.hand
        if hand is None or not hand.dig_pending:
            self.output("Nothing revealed. Play a Skip first with /skip.")
            return
        try:
            card = hand.take_dug(int(index))
        except (ValueError, IndexError) as e:
            self.output(str(e) if isinstance(e, IndexError) else "Give a number.")
            return
        self.output(f"kept {card}")
        if hand.state is HandState.FAILED:
            self.ctx.settle(hand)
        else:
            self._cmd_hand()

    def _cmd_lay(self) -> None:
        """Lay the phase down, if your hand satisfies it."""
        hand = self._require_hand()
        if hand is None:
            return
        try:
            layout = hand.lay_down()
        except RuntimeError as e:
            self.output(str(e))
            return
        for i, group in enumerate(layout, 1):
            self.output(render_group(i, group))
        self.ctx.settle(hand)

    def _cmd_auto(self) -> None:
        """Play the current hand out with the built-in greedy player."""
        hand = self._require_hand()
        if hand is None:
            return
        play_out(hand)
        if hand.layout:
            for i, group in enumerate(hand.layout, 1):
                self.output(render_group(i, group))
        self.ctx.settle(hand)

    def _cmd_grind(self, phase: str, count: str = "5") -> None:
        """Autoplay several rounds of a phase. Usage: /grind 2 10

        The Hands Won milestones run to thirty; clicking through that by hand
        is not a game.

        Commands are synchronous while sending is not, so a long grind blocks
        the loop that drains checks -- every round in one grind plays with the
        deck you started it with, and items earned along the way only apply
        afterwards. Short grinds keep the two closer together.
        """
        try:
            number, rounds = int(phase), int(count)
        except ValueError:
            self.output("Usage: /grind <phase> [rounds]")
            return
        if number not in PHASES:
            self.output("Give a phase number from 1 to 10.")
            return
        rounds = max(1, min(rounds, 50))

        session = self.ctx.session
        if session.hand is not None:
            self.output("Finish the current round first.")
            return

        won = 0
        for _ in range(rounds):
            refusal = session.can_play(number)
            if refusal:
                self.output(refusal)
                break
            hand = session.start_hand(number)
            play_out(hand)
            self.ctx.settle(hand, quiet=True)
            if session.last_result and session.last_result.cleared:
                won += 1

        self.output(f"Played {min(rounds, session.game.round_number - 1)} round(s), won {won}.")
        self._cmd_score()

    def _cmd_score(self) -> None:
        """Show the scorecard: recent rounds and the running total."""
        for line in self.ctx.session.game.scorecard():
            self.output(line)

class Phase10Context(CommonContext):
    game = GAME_NAME
    items_handling = 0b111  # full remote
    command_processor = Phase10CommandProcessor

    def __init__(self, server_address: str | None = None, password: str | None = None) -> None:
        super().__init__(server_address, password)
        self.session = Phase10Session()
        self.rng = random.Random()
        self.pending_locations: list[int] = []
        self.goal_sent = False
        # "needed" -> ask, "requested" -> waiting, "done" -> safe to save.
        # Saving before the restore lands would overwrite a real scorecard
        # with the empty one we just built from slot_data.
        self.restore_state = "needed"
        self.save_pending = False

    @property
    def save_key(self) -> str:
        """Data Storage key for this slot's scorecard."""
        return f"phase10_game_{self.team}_{self.slot}"

    async def server_auth(self, password_requested: bool = False) -> None:
        if password_requested and not self.password:
            await super().server_auth(password_requested)
        await self.get_username()
        await self.send_connect(game=self.game)

    def on_package(self, cmd: str, args: dict[str, Any]) -> None:
        if cmd == "Connected":
            self.session = Phase10Session.from_slot_data(
                args.get("slot_data", {}), self.rng
            )
            self.goal_sent = False
            self.restore_state = "needed"
            self.save_pending = False
            self.sync_items()
            logger.info("Connected. /phases to see what you can play, /play <n> to start.")
        elif cmd == "ReceivedItems":
            self.sync_items()
        elif cmd == "Retrieved":
            self.restore_from(args.get("keys", {}))

    def sync_items(self) -> None:
        """Re-tally received items.

        Archipelago resends the full list, so this is a wholesale replace rather
        than an increment -- which also makes it safe to call on reconnect.
        """
        names = [
            self.item_names.lookup_in_game(item.item, self.game)
            for item in self.items_received
        ]
        before = self.session.unlocked_phases
        self.session.set_items(names)
        for phase in sorted(self.session.unlocked_phases - before):
            logger.info(f"Phase {phase} unlocked: {phase_description(phase)}")

    def restore_from(self, keys: dict[str, Any]) -> None:
        """Load a scorecard out of Data Storage, if there is one."""
        if self.save_key not in keys:
            return
        payload = keys[self.save_key]
        if self.session.load_payload(payload):
            game = self.session.game
            logger.info(
                f"Restored {len(game.rounds)} round(s), {game.total_score} points."
            )
        elif payload is not None:
            logger.info("Stored scorecard could not be read; starting a fresh one.")
        self.restore_state = "done"

    def settle(self, hand, quiet: bool = False) -> None:
        """Finish a hand and queue whatever checks it earned."""
        new = self.session.finish_hand(hand)
        result = self.session.last_result
        if not quiet and result is not None:
            logger.info(str(result))
        if new:
            self.pending_locations.extend(new)
        self.save_pending = True

    async def phase10_loop(self) -> None:
        while not self.exit_event.is_set():
            connected = self.server and not self.server.socket.closed

            if connected and self.restore_state == "needed":
                self.restore_state = "requested"
                await self.send_msgs([{"cmd": "Get", "keys": [self.save_key]}])

            if connected and self.save_pending and self.restore_state == "done":
                self.save_pending = False
                await self.send_msgs([{
                    "cmd": "Set",
                    "key": self.save_key,
                    "default": {},
                    "want_reply": False,
                    "operations": [
                        {"operation": "replace", "value": self.session.to_payload()}
                    ],
                }])

            if self.pending_locations and self.server and not self.server.socket.closed:
                queued, self.pending_locations = self.pending_locations, []
                await self.check_locations(queued)
            if self.session.goal_met and not self.goal_sent and self.server:
                await self.send_msgs(
                    [{"cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}]
                )
                self.finished_game = True
                self.goal_sent = True
                logger.info("Goal complete.")
            await asyncio.sleep(0.1)

    def make_gui(self):
        # Imported here, not at module scope: kivy must stay off the import
        # path for the headless tests and for anyone running without a display.
        from .game_manager import Phase10Manager

        return Phase10Manager


async def main(args) -> None:
    from CommonClient import gui_enabled

    ctx = Phase10Context(args.connect, args.password)
    ctx.auth = args.name
    ctx.server_task = asyncio.create_task(server_loop(ctx), name="server loop")
    ctx.client_loop = asyncio.create_task(ctx.phase10_loop(), name="phase10 loop")

    if gui_enabled:
        ctx.run_gui()
    ctx.run_cli()

    await ctx.exit_event.wait()
    await ctx.shutdown()
