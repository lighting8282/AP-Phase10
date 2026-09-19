"""Visual and interaction check for the Phase 10 client tab.

Kivy needs a real window, so this is not a unit test -- it launches the client
UI with a seeded session, dispatches real button events to prove the bindings
work, screenshots the result and exits.

    <AP checkout>/.venv/Scripts/python.exe tests/ui_check.py out.png

Requires kivy and kivymd in the Archipelago venv.
"""

import sys, os, asyncio, random

AP = os.environ.get("AP_ROOT", "C:/Users/turtl/Archipelago")
sys.path.insert(0, AP)
os.chdir(AP)

import ModuleUpdate

ModuleUpdate.update_ran = True

OUT = sys.argv[1] if len(sys.argv) > 1 else "phase10_ui.png"

from worlds.phase10.client.context import Phase10Context
from worlds.phase10.client.session import Phase10Session
from worlds.phase10.data import (
    EXTRA_DRAW, GAME_NAME, MULLIGAN, PHASE_UNLOCK, SKIP_CARD, WILD_CARD,
)

failures: list[str] = []


def check(condition, message):
    if condition:
        print(f"  ok   {message}")
    else:
        failures.append(message)
        print(f"  FAIL {message}")


async def main():
    ctx = Phase10Context(None, None)
    ctx.session = Phase10Session.from_slot_data(
        {"goal": 0, "starting_draws": 6, "checks_per_phase": 4}, random.Random(7)
    )
    ctx.session.set_items(
        [PHASE_UNLOCK.format(p) for p in (1, 2, 4, 6, 7)]
        + [WILD_CARD] * 5 + [EXTRA_DRAW] * 3 + [SKIP_CARD] * 2 + [MULLIGAN]
    )
    ctx.run_gui()

    from kivy.clock import Clock
    from kivy.core.window import Window

    def exercise(_dt):
        view = ctx.ui.game_view
        session = ctx.session

        # Start a round by "clicking" the Phase 6 button (index 5 of ten).
        view.refresh(force=True)
        phase_buttons = list(reversed(view.phase_grid.children))
        phase_buttons[5].dispatch("on_release")
        check(session.hand is not None and session.hand.phase == 6,
              "phase button starts the round")

        hand = session.hand
        check(len(hand.hand) == 12, "hand shows 10 dealt cards plus 2 granted skips")

        # The table strip has to show the seats, or a round that ends because
        # somebody went out looks like it ended for no reason at all.
        check(len(session.seats) == 3, "three opponents are seated")
        check(all(s.name in view.seats.text for s in session.seats),
              "every seat is named in the table strip")
        check(str(session.seats[0].phase) in view.seats.text,
              "and the strip shows what phase they are on")

        # What the computers have face up, so a player can read whether a
        # spare card of theirs would extend one of the groups.
        for _ in range(20):
            if any(s.layout for s in session.seats):
                break
            session.table.end_of_turn()
        view.refresh(force=True)
        down = [s for s in session.seats if s.layout]
        check(bool(down), "a seat lays its phase down")
        check(len(view.melds.children) > 0, "laid groups are rendered on the table")
        laid_cards = sum(len(g) for s in down for g in s.layout)
        check(laid_cards > 0, f"and carry real cards ({laid_cards})")

        # Mulligan, while the deal is still untouched. It has to run before
        # the draw below, which is exactly what makes it unavailable after.
        dealt = [str(c) for c in hand.hand]
        next(b for b in view.actions.children if b.text == "Mulligan").dispatch("on_release")
        check([str(c) for c in hand.hand] != dealt, "Mulligan button redeals the hand")
        check(session.mulligans_left == 0, "and the Mulligan is spent")

        # Draw, via the action button rather than the session.
        before = hand.draws_used
        next(b for b in view.actions.children if b.text == "Draw").dispatch("on_release")
        check(hand.draws_used == before + 1, "Draw button spends a draw")

        # Discard by clicking a card.
        view.refresh(force=True)
        size = len(hand.hand)
        card = hand.hand[0]
        list(reversed(view.hand_grid.children))[0].dispatch("on_release")
        check(len(hand.hand) == size - 1, "clicking a card discards it")
        # Not the discard *top* any more: the opponents take their turns as
        # soon as yours ends, and each throws a card on the same pile. What
        # has to hold is that the card you clicked is the one that left your
        # hand and reached the pile.
        check(card in hand.discard, "the clicked card is the one discarded")
        check(card not in hand.hand, "and it left your hand")

        # Dig with a Skip and keep a revealed card.
        view.refresh(force=True)
        next(b for b in view.actions.children if b.text == "Dig (Skip)").dispatch("on_release")
        check(hand.dig_pending, "Dig reveals the top of the stock")
        view.refresh(force=True)
        check(len(view.dig_row.children) > 1, "revealed cards are rendered")
        draws = hand.draws_used
        list(reversed(view.dig_row.children))[1].dispatch("on_release")
        check(not hand.dig_pending, "taking a revealed card resolves the dig")
        check(hand.draws_used == draws, "the dig costs no draw")

        view.refresh(force=True)
        try:
            ctx.ui.screens.current = GAME_NAME
        except Exception as e:
            print("  tab switch failed:", e)
        Clock.schedule_once(lambda _d: Window.screenshot(name=OUT), 0.8)
        Clock.schedule_once(lambda _d: ctx.ui.stop(), 2.0)

    Clock.schedule_once(exercise, 2.5)
    await ctx.ui_task
    ctx.exit_event.set()

    print()
    if failures:
        print(f"{len(failures)} UI check(s) FAILED")
        sys.exit(1)
    print("all UI checks passed")


asyncio.run(main())
