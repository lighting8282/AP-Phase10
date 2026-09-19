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

## Who am I playing against?

Three computer players by default, sharing your deck. They build toward their
own phases, lay down, and shed; when one of them goes out your round ends where
it stands. They carry their phase between rounds, so the table gets harder as
your run goes on.

You also still have a draw budget, so a round ends on whichever comes first --
your draws running out, or somebody going out. Set `opponents` to 0 for the
pure solo game.

Both clients play the same table. The two opponent implementations are checked
against each other turn for turn, so a seed plays identically in the browser and
on the desktop.

## What items and locations exist?

Items: phase unlocks, Wild Card, Extra Draw, Hand Size Upgrade and Skip Card,
plus filler and traps.

The two fillers both do something. A **Mulligan** throws back a dead opening
hand and deals you a fresh one -- usable only before your first draw, and it
costs you no draw. A **Score Reduction** takes 25 points off your running total,
which is what a Wild left in your hand costs you.

Traps, when enabled: Phase Lock pins you to the phase you just lost until you
clear it, Lean Deal costs you two cards on one hand, and Wild Theft takes a wild
out of the deck for one hand.

Locations: each of the twenty phases is worth up to four checks -- clearing it, clearing it and
going out in the same hand, clearing it without using a wild, and clearing it
inside half your draw budget.

## How many phases are there?

Twenty. The ten printed on the box, plus ten more measured to fill a hole the
originals left: none of them clears more than about two thirds of the time, so
every phase was a fight. The new ten run from a very gentle five cards of one
colour down to three sets of three.

The printed order is not a difficulty ramp and never was -- two sets of four is
by a wide margin the hardest thing in the game, harder than the run of nine.

## What is the goal?

By default, clear all twenty phases. The goal option can shorten this to
clearing Phase 10 alone.
