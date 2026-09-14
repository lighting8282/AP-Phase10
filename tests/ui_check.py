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
from worlds.phase10.data import EXTRA_DRAW, GAME_NAME, PHASE_UNLOCK, SKIP_CARD, WILD_CARD

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
        + [WILD_CARD] * 5 + [EXTRA_DRAW] * 3 + [SKIP_CARD] * 2
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
        check(hand.discard_top == card, "the clicked card is the one discarded")

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
