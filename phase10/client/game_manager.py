"""A Phase 10 tab for the Archipelago client window.

Every control here routes through the command processor rather than touching
the session directly, so the buttons and the typed commands cannot diverge --
clicking Draw runs exactly what /draw runs.

The view rebuilds only when a signature of the visible state changes. A card
game is mostly idle between clicks, and tearing down a dozen widgets four times
a second to redraw the same hand is pure waste.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

# kvui MUST be imported before anything from kivy -- it asserts on that for
# frozen-build compatibility. Do not let an import sorter reorder these.
from kvui import GameManager

from kivy.clock import Clock
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.layout import Layout

from ..game.cards import Color, card_filename
from ..game.engine import HandState
from ..game.phases import PHASES, phase_description

if TYPE_CHECKING:
    from .context import Phase10Context

CARD_COLORS = {
    Color.RED: (0.78, 0.22, 0.22, 1),
    Color.BLUE: (0.20, 0.42, 0.85, 1),
    Color.GREEN: (0.18, 0.62, 0.32, 1),
    Color.YELLOW: (0.85, 0.68, 0.12, 1),
}
WILD_COLOR = (0.55, 0.30, 0.78, 1)
SKIP_COLOR = (0.42, 0.44, 0.50, 1)
IDLE_COLOR = (0.30, 0.30, 0.34, 1)


def card_color(card) -> tuple[float, float, float, float]:
    if card.is_wild:
        return WILD_COLOR
    if card.is_skip:
        return SKIP_COLOR
    return CARD_COLORS[card.color]


CARD_ASSETS = Path(__file__).parent / "assets" / "cards"


def card_image(card) -> str | None:
    """Path to this card's rendered face, or None if it has not been generated.

    Faces come from tools/generate_cards.py. They are ordinary repo files, so
    normally they are simply present -- but a checkout that has not run the
    generator should still get a usable client rather than a stack trace.
    """
    path = CARD_ASSETS / card_filename(card)
    return str(path) if path.is_file() else None


class CardFace(ButtonBehavior, Image):
    """A rendered card that behaves like a button.

    ButtonBehavior supplies on_release, so call sites bind to this exactly as
    they did to the old Button. fit_mode="contain" keeps the 2:3 card shape
    inside whatever cell the layout hands it, rather than stretching it.
    """

    def __init__(self, card, source: str, **kwargs) -> None:
        super().__init__(source=source, fit_mode="contain", **kwargs)
        self.card = card


class CardChip(Button):
    """Fallback face: the coloured text button used before the art existed."""

    def __init__(self, card, **kwargs) -> None:
        super().__init__(
            text=str(card),
            background_normal="",
            background_color=card_color(card),
            font_size="18sp",
            bold=True,
            **kwargs,
        )
        self.card = card


def make_card(card, **kwargs):
    """A clickable card widget -- the rendered face when it exists."""
    source = card_image(card)
    if source is not None:
        return CardFace(card, source, **kwargs)
    return CardChip(card, **kwargs)


# Row height for a card. The faces are 2:3, and fit_mode="contain" scales a
# card to whichever of the cell's dimensions binds first -- so the row height
# is what actually decides how big a card looks.
CARD_ROW_HEIGHT = 96
CARD_WIDTH = CARD_ROW_HEIGHT * 2 // 3   # the faces are rendered 2:3
HAND_COLS = 8


class Phase10View(BoxLayout):
    """The tab body. Reads the session; writes only through commands."""

    def __init__(self, manager: "Phase10Manager", **kwargs) -> None:
        super().__init__(orientation="vertical", padding=8, spacing=6, **kwargs)
        self.manager = manager
        self._signature: tuple | None = None

        self.header = Label(text="", markup=True, size_hint_y=None, height=28,
                            font_size="17sp", halign="left", valign="middle")
        self.header.bind(size=lambda w, _: setattr(w, "text_size", w.size))

        self.objective = Label(text="", markup=True, size_hint_y=None, height=24,
                               halign="left", valign="middle")
        self.objective.bind(size=lambda w, _: setattr(w, "text_size", w.size))

        self.stats = Label(text="", markup=True, size_hint_y=None, height=24,
                           halign="left", valign="middle")
        self.stats.bind(size=lambda w, _: setattr(w, "text_size", w.size))

        self.hand_grid = GridLayout(cols=8, spacing=4, size_hint_y=None, height=110)
        self.dig_row = BoxLayout(size_hint_y=None, height=0, spacing=4)
        self.actions = BoxLayout(size_hint_y=None, height=40, spacing=4)
        self.phase_grid = GridLayout(cols=10, spacing=4, size_hint_y=None, height=38)

        for widget in (self.header, self.objective, self.stats,
                       Label(text="[b]Your hand[/b] -- click a card to discard it",
                             markup=True, size_hint_y=None, height=22),
                       self.hand_grid, self.dig_row, self.actions,
                       Label(text="[b]Phases[/b]", markup=True, size_hint_y=None, height=22),
                       self.phase_grid):
            self.add_widget(widget)
        self.add_widget(BoxLayout())  # soak up the remaining space

        self._build_actions()

    # -- input -------------------------------------------------------------
    def run(self, command: str) -> None:
        """Everything the UI does goes through the same commands you can type."""
        self.manager.commandprocessor(command)
        self.refresh(force=True)

    def _build_actions(self) -> None:
        for label, command in (
            ("Draw", "/draw"),
            ("Take discard", "/draw d"),
            ("Lay down", "/lay"),
            ("Dig (Skip)", "/skip"),
            ("Auto", "/auto"),
            ("Score", "/score"),
        ):
            button = Button(text=label, font_size="14sp")
            button.bind(on_release=lambda _w, c=command: self.run(c))
            self.actions.add_widget(button)

    # -- rendering ---------------------------------------------------------
    def signature(self) -> tuple:
        """Everything visible, cheaply. Redraw only when this changes."""
        s = self.manager.ctx.session
        hand = s.hand
        return (
            tuple(sorted(s.unlocked_phases)),
            s.game.round_number,
            s.total_score,
            s.locked_phase,
            hand.phase if hand else None,
            tuple(str(c) for c in hand.hand) if hand else (),
            str(hand.discard_top) if hand else None,
            hand.draws_left if hand else None,
            hand.state.value if hand else None,
            tuple(str(c) for c in (hand.dig_options or ())) if hand else (),
        )

    def refresh(self, force: bool = False) -> None:
        signature = self.signature()
        if not force and signature == self._signature:
            return
        self._signature = signature

        s = self.manager.ctx.session
        hand = s.hand

        self.header.text = (
            f"[b]Round {s.game.round_number}[/b]    "
            f"score [b]{s.total_score}[/b] (lower is better)    "
            f"won {s.hands_won}    cleared {len(s.cleared_phases)}/10"
        )

        if hand is not None:
            self.objective.text = f"[b]Phase {hand.phase}[/b]: {phase_description(hand.phase)}"
            self.stats.text = (
                f"draws left [b]{hand.draws_left}[/b]    stock {len(hand.stock)}    "
                f"discard {hand.discard_top}    skips in hand {hand.skips_in_hand}"
            )
        else:
            config = s.config
            self.objective.text = "No round in progress -- pick a phase below."
            self.stats.text = (
                f"deck: {config.wilds_in_deck} wilds    {config.max_draws} draws per hand    "
                f"hand size {config.hand_size}    {config.starting_skips} skip(s) per hand"
            )
            if s.locked_phase:
                self.stats.text += f"    [color=ff8888]Phase Lock: replay {s.locked_phase}[/color]"

        self._render_hand(hand)
        self._render_dig(hand)
        self._render_phases(s)

    def _render_hand(self, hand) -> None:
        self.hand_grid.clear_widgets()
        if hand is None:
            self.hand_grid.height = CARD_ROW_HEIGHT
            return
        for index, card in enumerate(hand.hand):
            button = make_card(card)
            button.bind(on_release=lambda _w, i=index: self.run(f"/discard {i}"))
            self.hand_grid.add_widget(button)

        # A GridLayout splits its height evenly across however many rows it
        # ends up with, so a fixed height shrinks every card as the hand grows.
        # Size to the content instead and the cards stay legible.
        rows = max(1, -(-len(hand.hand) // HAND_COLS))
        self.hand_grid.height = rows * CARD_ROW_HEIGHT + (rows - 1) * self.hand_grid.spacing[1]

    def _render_dig(self, hand) -> None:
        self.dig_row.clear_widgets()
        if hand is None or not hand.dig_pending:
            self.dig_row.height = 0
            return
        self.dig_row.height = CARD_ROW_HEIGHT
        self.dig_row.add_widget(Label(text="Keep one:", size_hint_x=None, width=90))
        for index, card in enumerate(hand.dig_options):
            button = make_card(card, size_hint_x=None, width=CARD_WIDTH)
            button.bind(on_release=lambda _w, i=index: self.run(f"/take {i}"))
            self.dig_row.add_widget(button)
        # Only three cards are revealed. Without a trailing spacer a BoxLayout
        # would spread them across the whole row; this keeps them together.
        self.dig_row.add_widget(BoxLayout())

    def _render_phases(self, session) -> None:
        self.phase_grid.clear_widgets()
        unlocked = session.unlocked_phases
        for phase in range(1, 11):
            button = Button(text=str(phase), font_size="14sp", background_normal="")
            if phase in session.cleared_phases:
                button.background_color = (0.18, 0.55, 0.30, 1)
            elif phase in unlocked:
                button.background_color = (0.25, 0.45, 0.75, 1)
            else:
                button.background_color = IDLE_COLOR
                button.disabled = True
            button.bind(on_release=lambda _w, p=phase: self.run(f"/play {p}"))
            self.phase_grid.add_widget(button)


class Phase10Manager(GameManager):
    base_title = "Archipelago Phase 10 Client"
    ctx: "Phase10Context"

    def build(self) -> Layout:
        container = super().build()
        self.game_view = Phase10View(self)
        self.add_client_tab("Phase 10", self.game_view)
        # Polling beats threading a redraw call through every mutation site;
        # the signature check makes an unchanged frame nearly free.
        Clock.schedule_interval(lambda _dt: self.game_view.refresh(), 1 / 4)
        return container
