# AP_Phase10

## What is this game?

An original implementation of a rummy-style card game built around ten escalating objectives --
sets, runs, and colour collections -- normally played in a fixed order against
other players.

This implementation is solo. Rather than racing opponents to go out, you get a
limited number of draws per hand to lay your phase down. Run out of draws and
the hand fails.

## What does randomization do?

Archipelago decides which of the ten phases you are allowed to attempt, and
hands you the tools to attempt them. Your deck starts with no wild cards at all
and a small draw budget; Wild Card and Extra Draw items build both back up.

Because phases unlock out of order, you will not meet them in printed order --
which matters less than it sounds, because the printed order is not a
difficulty ramp. Two sets of four (Phase 7) is by a wide margin the hardest
objective in the game, harder than the run of nine (Phase 6), because each rank
has only eight copies in the deck while any of eight copies can fill a run slot.

## What items and locations exist?

Items: phase unlocks, Wild Card, Extra Draw, Hand Size Upgrade, plus filler and
traps.

Locations: each phase is worth up to four checks -- clearing it, clearing it and
going out in the same hand, clearing it without using a wild, and clearing it
inside half your draw budget.

## What is the goal?

By default, clear all ten phases. The goal option can shorten this to clearing
Phase 10 alone.
