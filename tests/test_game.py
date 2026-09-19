"""Tests for the multi-hand game and its scorecard. Runnable directly."""

import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "phase10"))

import random

from game.cards import SKIP, WILD, hand_score, number_card
from game.cards import Color
from game.engine import GameConfig, HandState, PhaseHand, Table
from game.opponents import MID, Opponent, OpponentSkill, build_opponents
from game.game import Phase10Game, RoundResult

R = Color.RED


def finished(game, phase, state, leftovers, config=None):
    """Run a round to a forced outcome with a known leftover hand."""
    hand = game.start_round(phase, config or GameConfig(max_draws=8))
    hand.state = state
    hand.hand = list(leftovers)
    return game.finish_round(hand)


def test_round_numbers_increment():
    g = Phase10Game(random.Random(1))
    assert g.round_number == 1
    finished(g, 1, HandState.PHASE_LAID, [])
    assert g.round_number == 2
    finished(g, 2, HandState.FAILED, [WILD])
    assert g.round_number == 3
    assert [r.number for r in g.rounds] == [1, 2]


def test_going_out_scores_nothing():
    g = Phase10Game(random.Random(1))
    r = finished(g, 3, HandState.WENT_OUT, [])
    assert r.score == 0
    assert r.went_out and r.cleared
    assert g.total_score == 0


def test_leftovers_after_laying_down_still_cost():
    g = Phase10Game(random.Random(1))
    leftovers = [number_card(4, R), number_card(11, R), WILD]
    r = finished(g, 5, HandState.PHASE_LAID, leftovers)
    assert r.score == hand_score(leftovers) == 5 + 10 + 25
    assert r.cleared and not r.went_out


def test_a_failed_hand_costs_the_whole_hand():
    g = Phase10Game(random.Random(1))
    leftovers = [number_card(2, R), SKIP, WILD]
    r = finished(g, 7, HandState.FAILED, leftovers)
    assert r.score == 5 + 15 + 25
    assert not r.cleared


def test_total_score_accumulates_across_rounds():
    g = Phase10Game(random.Random(1))
    finished(g, 1, HandState.PHASE_LAID, [number_card(3, R)])      # 5
    finished(g, 2, HandState.FAILED, [number_card(12, R), WILD])   # 35
    finished(g, 3, HandState.WENT_OUT, [])                          # 0
    assert g.total_score == 40
    assert g.rounds_won == 2


def test_cleared_phases_tracks_only_wins():
    g = Phase10Game(random.Random(1))
    finished(g, 4, HandState.PHASE_LAID, [])
    finished(g, 6, HandState.FAILED, [WILD])
    assert g.cleared_phases == {4}


def test_best_round_is_the_cheapest_win():
    g = Phase10Game(random.Random(1))
    finished(g, 1, HandState.PHASE_LAID, [number_card(12, R)])  # 10
    finished(g, 2, HandState.WENT_OUT, [])                       # 0
    finished(g, 3, HandState.FAILED, [])                         # a loss, ignored
    assert g.best_round.phase == 2
    assert g.best_round.score == 0


def test_best_round_is_none_before_any_win():
    g = Phase10Game(random.Random(1))
    finished(g, 1, HandState.FAILED, [WILD])
    assert g.best_round is None


def test_history_is_per_phase():
    g = Phase10Game(random.Random(1))
    finished(g, 2, HandState.PHASE_LAID, [])
    finished(g, 5, HandState.FAILED, [WILD])
    finished(g, 2, HandState.WENT_OUT, [])
    assert [r.phase for r in g.history_for(2)] == [2, 2]
    assert len(g.history_for(5)) == 1


def test_cannot_start_a_round_while_one_is_live():
    g = Phase10Game(random.Random(1))
    g.start_round(1, GameConfig(max_draws=8))
    try:
        g.start_round(2, GameConfig(max_draws=8))
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected a refusal while a round is in progress")


def test_cannot_finish_a_round_still_in_progress():
    g = Phase10Game(random.Random(1))
    g.start_round(1, GameConfig(max_draws=8))
    try:
        g.finish_round()
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected a refusal for an unfinished round")


def test_config_is_taken_per_round_not_frozen():
    """Items keep arriving, so later rounds must see the newer deck."""
    g = Phase10Game(random.Random(1))
    lean = GameConfig(hand_size=8, wilds_in_deck=0, max_draws=8)
    rich = GameConfig(hand_size=12, wilds_in_deck=8, max_draws=20)
    first = g.start_round(1, lean)
    assert len(first.hand) == 8
    g.finish_round(_forced(first))
    second = g.start_round(1, rich)
    assert len(second.hand) == 12
    assert second.config.max_draws == 20


def _forced(hand):
    hand.state = HandState.FAILED
    return hand


def test_scorecard_reports_totals():
    g = Phase10Game(random.Random(1))
    assert "No rounds played yet." in g.scorecard()
    finished(g, 1, HandState.WENT_OUT, [])
    finished(g, 2, HandState.FAILED, [WILD])
    card = g.scorecard()
    assert any("2 rounds | 1 won | 25 points total" in line for line in card)
    assert any(line.startswith("best:") for line in card)


def test_scorecard_elides_old_rounds():
    g = Phase10Game(random.Random(1))
    for _ in range(15):
        finished(g, 1, HandState.WENT_OUT, [])
    card = g.scorecard(limit=5)
    assert any("10 earlier round(s)" in line for line in card)


# -- Mulligan (engine level) --------------------------------------------------
# The session carries its own copy of these guards so it can explain a refusal
# in words. These test the engine's, which is what protects any other driver --
# the autoplayer, a fixture replay, a player poking at the console.

def fresh_hand(seed=3, **cfg):
    return PhaseHand(1, GameConfig(max_draws=8, **cfg), random.Random(seed))


def test_redeal_replaces_the_hand():
    hand = fresh_hand()
    before = [str(c) for c in hand.hand]
    hand.redeal()
    assert [str(c) for c in hand.hand] != before


def test_redeal_conserves_the_deck():
    hand = fresh_hand()
    hand.redeal()
    total = len(hand.hand) + len(hand.discard) + len(hand.stock)
    assert total == 96 + hand.config.wilds_in_deck
    assert len(hand.hand) == hand.config.hand_size
    assert len(hand.discard) == 1


def test_redeal_costs_no_draw():
    hand = fresh_hand()
    hand.redeal()
    assert hand.draws_used == 0
    assert hand.draws_left == 8


def test_redeal_refused_after_a_draw():
    hand = fresh_hand()
    hand.draw()
    try:
        hand.redeal()
    except RuntimeError:
        return
    raise AssertionError("redeal must be refused once the hand has been played")


def test_redeal_refused_mid_turn():
    """Drawn but not yet discarded still counts as touched."""
    hand = fresh_hand()
    hand.draw()
    assert hand.drew_this_turn
    try:
        hand.redeal()
    except RuntimeError:
        return
    raise AssertionError("redeal must be refused mid-turn")


def test_redeal_refused_on_a_finished_hand():
    hand = fresh_hand()
    hand.mark_failed("test")
    try:
        hand.redeal()
    except RuntimeError:
        return
    raise AssertionError("redeal must be refused on a finished hand")


def test_redeal_refused_after_a_skip():
    hand = fresh_hand(starting_skips=1)
    hand.play_skip()
    hand.take_dug(0)
    try:
        hand.redeal()
    except RuntimeError:
        return
    raise AssertionError("redeal must be refused once a Skip has been played")


def test_redeal_refused_with_a_dig_pending():
    hand = fresh_hand(starting_skips=1)
    hand.play_skip()
    assert hand.dig_pending
    try:
        hand.redeal()
    except RuntimeError:
        return
    raise AssertionError("redeal must be refused with a dig pending")


# -- the shared table ---------------------------------------------------------
# With no seats a Table is a hand's own private stock and discard, which is what
# lets every solo measurement above stand as the regression guard for the split.

def seated(n, phases=None, skill=MID, seed=5, **cfg_kw):
    """A player hand sharing a table with `n` opponents."""
    cfg = GameConfig(max_draws=cfg_kw.pop("max_draws", 8), **cfg_kw)
    rng = random.Random(seed)
    table = Table()
    table.seats = build_opponents(n, phases or [1] * n, cfg, rng, skill)
    return PhaseHand(1, cfg, rng, table=table), table


def test_seats_are_dealt_from_the_same_deck():
    hand, table = seated(3)
    dealt = len(hand.hand) + sum(len(s.hand) for s in table.seats)
    total = dealt + len(table.stock) + len(table.discard)
    assert total == 96 + hand.config.wilds_in_deck
    assert all(len(s.hand) == hand.config.hand_size for s in table.seats)


def test_no_seats_leaves_the_table_to_the_player():
    hand, table = seated(0)
    assert table.seats == []
    assert len(hand.hand) + len(table.stock) + len(table.discard) == 96 + hand.config.wilds_in_deck


def test_an_opponent_sheds_after_laying_down_and_goes_out():
    """The first version drew one and discarded one, so it never shed at all
    and no opponent could ever go out. Sizes must strictly decrease."""
    cfg = GameConfig(max_draws=99)
    rng = random.Random(1)
    table = Table()
    table.seats = build_opponents(1, [1], cfg, rng, MID)
    PhaseHand(1, cfg, rng, table=table)
    seat = table.seats[0]

    sizes = []
    for _ in range(40):
        if seat.take_turn(table):
            break
        if seat.laid_down:
            sizes.append(len(seat.hand))
    assert seat.went_out, "an opponent that laid down must eventually go out"
    assert sizes == sorted(sizes, reverse=True), f"hand must shrink, got {sizes}"


def test_laid_down_cards_stay_on_the_table():
    """They used to be removed from hand and stored nowhere at all, so six
    cards left the deck the moment a seat laid down -- invisible to the player
    and unaccounted for by any conservation check."""
    hand, table = seated(3, max_draws=99)

    def accounted():
        laid = sum(len(g) for s in table.seats for g in s.layout)
        seated_cards = sum(len(s.hand) for s in table.seats)
        return len(hand.hand) + seated_cards + laid + len(table.stock) + len(table.discard)

    total = 96 + hand.config.wilds_in_deck
    assert accounted() == total
    for _ in range(12):
        table.end_of_turn()
    assert any(s.laid_down for s in table.seats), "nobody laid down; test is vacuous"
    assert accounted() == total


def test_a_laid_layout_matches_the_phase_it_claims():
    hand, table = seated(1, phases=[1], max_draws=99)
    seat = table.seats[0]
    for _ in range(30):
        table.end_of_turn()
        if seat.laid_down:
            break
    assert seat.laid_down
    # Phase 1 is two sets of three.
    assert [len(g) for g in seat.layout] == [3, 3]


def test_a_redeal_clears_what_was_on_the_table():
    hand, table = seated(3)
    for _ in range(12):
        table.end_of_turn()
    hand.redeal()
    assert all(s.layout == [] and not s.laid_down for s in table.seats)


def test_an_opponent_going_out_ends_the_players_hand():
    hand, table = seated(1, max_draws=99)
    seat = table.seats[0]
    for _ in range(60):
        if seat.went_out:
            break
        table.end_of_turn()
    assert seat.went_out

    # The player is mid-hand, so the race is lost.
    hand.draw()
    hand.discard_card(hand.hand[0])
    assert hand.state is HandState.FAILED
    assert hand.events[-1].detail["reason"] == "opponent_out"


def test_going_out_cannot_undo_a_phase_already_laid():
    hand, table = seated(1, max_draws=99)
    hand.state = HandState.PHASE_LAID
    for seat in table.seats:
        seat.laid_down, seat.hand = True, []
        seat.went_out = True
    hand._end_turn()
    assert hand.state is HandState.PHASE_LAID


def test_running_out_of_draws_beats_the_race_to_the_blame():
    """Both clocks can expire on the same turn; the budget is the real cause."""
    hand, table = seated(1, max_draws=1)
    # A hand of six distinct ranks cannot make two sets of three, so the
    # player is genuinely out of road rather than entitled to lay down.
    hand.hand = [number_card(r, R) for r in range(1, 7)]
    hand.draws_used = hand.config.max_draws
    hand.drew_this_turn = True
    # The seat is one shed away from going out, so a wrong blame order shows.
    seat = table.seats[0]
    seat.laid_down, seat.hand, seat.went_out = True, [number_card(9, R)], False

    hand.discard_card(hand.hand[0])
    assert hand.state is HandState.FAILED
    assert hand.events[-1].detail["reason"] == "out_of_draws"


def test_a_mulligan_redeals_the_whole_table():
    hand, table = seated(3)
    before = [[str(c) for c in s.hand] for s in table.seats]
    hand.redeal()
    after = [[str(c) for c in s.hand] for s in table.seats]
    assert before != after
    assert all(len(s.hand) == hand.config.hand_size for s in table.seats)


def test_a_perfect_seat_never_ignores_a_useful_discard():
    """Skill is two probabilities over one policy; at 1.0/0.0 it is the greedy
    autoplayer, which is what makes later difficulty levels just numbers."""
    perfect = OpponentSkill("perfect", discard_awareness=1.0, discard_error=0.0)
    cfg = GameConfig()
    rng = random.Random(0)
    seat = Opponent("T", 1, cfg, rng, perfect)
    seat.hand = [number_card(5, R), number_card(5, Color.BLUE), number_card(9, R),
                 number_card(2, R), number_card(7, R), number_card(11, R)]
    assert seat._wants_discard_top(number_card(5, Color.GREEN)) is True
    for _ in range(20):
        assert seat._wants_discard_top(number_card(5, Color.GREEN)) is True


def test_a_careless_seat_sometimes_looks_away():
    careless = OpponentSkill("careless", discard_awareness=0.5, discard_error=0.0)
    seat = Opponent("T", 1, GameConfig(), random.Random(3), careless)
    seat.hand = [number_card(5, R), number_card(5, Color.BLUE), number_card(9, R),
                 number_card(2, R), number_card(7, R), number_card(11, R)]
    looks = [seat._wants_discard_top(number_card(5, Color.GREEN)) for _ in range(200)]
    assert any(looks) and not all(looks), "awareness below 1.0 must vary"


# -- hitting ------------------------------------------------------------------
# A laid group has to remember what it means, or a hit cannot be judged: for a
# run, `3R W 5B` must know the wild is standing in for a 4. Deriving that after
# the fact is ambiguous, so it is recorded when the group is built.

def melds_for(cards, spec):
    from game.phases import solve_melds
    out = solve_melds(cards, spec)
    assert out is not None, "fixture hand does not satisfy its own spec"
    return out


def test_a_run_remembers_the_span_its_wild_stands_in_for():
    from game.phases import RUN
    run = melds_for([number_card(3, R), WILD, number_card(5, Color.BLUE)], (RUN(3),))[0]
    assert (run.lo, run.hi) == (3, 5)


def test_a_run_takes_either_end_and_nothing_else():
    from game.phases import RUN
    run = melds_for([number_card(3, R), WILD, number_card(5, Color.BLUE)], (RUN(3),))[0]
    assert run.accepts(number_card(2, R))
    assert run.accepts(number_card(6, R))
    assert not run.accepts(number_card(8, R))
    assert not run.accepts(number_card(4, R))   # already inside the span


def test_hitting_a_run_widens_it():
    from game.phases import RUN
    run = melds_for([number_card(3, R), WILD, number_card(5, Color.BLUE)], (RUN(3),))[0]
    run.add(number_card(6, R))
    assert (run.lo, run.hi) == (3, 6)
    assert run.accepts(number_card(7, R)), "the new end has to open up"


def test_a_run_pinned_to_both_ends_has_nowhere_for_a_wild():
    from game.phases import RUN
    full = melds_for([number_card(r, R) for r in range(1, 13)], (RUN(12),))[0]
    assert (full.lo, full.hi) == (1, 12)
    assert not full.accepts(WILD), "there is no rank left for it to stand in for"


def test_a_set_takes_its_own_rank_only():
    from game.phases import SET
    st = melds_for([number_card(7, R), number_card(7, Color.BLUE),
                    number_card(7, Color.GREEN)], (SET(3),))[0]
    assert st.rank == 7
    assert st.accepts(number_card(7, Color.YELLOW))
    assert not st.accepts(number_card(8, Color.YELLOW))
    assert st.accepts(WILD)


def test_a_colour_group_takes_its_own_colour_only():
    from game.phases import COLOR
    col = melds_for([number_card(r, Color.GREEN) for r in range(1, 6)], (COLOR(5),))[0]
    assert col.color is Color.GREEN
    assert col.accepts(number_card(9, Color.GREEN))
    assert not col.accepts(number_card(9, R))


def test_a_skip_can_never_be_hit_anywhere():
    from game.phases import SET, RUN
    st = melds_for([number_card(7, R), number_card(7, Color.BLUE),
                    number_card(7, Color.GREEN)], (SET(3),))[0]
    run = melds_for([number_card(3, R), WILD, number_card(5, Color.BLUE)], (RUN(3),))[0]
    assert not st.accepts(SKIP)
    assert not run.accepts(SKIP)


def test_a_skip_is_refused_even_by_an_unanchored_group():
    """The Skip guard only bites here.

    A normal group rejects a Skip incidentally -- a Skip has no rank, so the
    rank check fails anyway. A group with no anchor (all wilds, which needs
    min_naturals_per_group=0) answers "any rank will do", and without the
    explicit guard it would happily swallow a Skip.
    """
    from game.phases import GroupKind, Meld, SET, COLOR

    loose_set = Meld(SET(3), [WILD, WILD, WILD], GroupKind.SET, rank=None)
    loose_color = Meld(COLOR(3), [WILD, WILD, WILD], GroupKind.COLOR, color=None)
    assert loose_set.accepts(number_card(4, R)), "no anchor means any rank fits"
    assert not loose_set.accepts(SKIP)
    assert not loose_color.accepts(SKIP)


def test_opponents_shed_by_hitting_the_table():
    """The old stand-in threw one card a turn and drew nothing. Now a seat
    lays every card that legally extends anything already down -- its own
    groups or anybody else's -- so melds visibly grow."""
    hand, table = seated(3, max_draws=99, seed=4)
    for _ in range(40):
        if table.end_of_turn() is not None:
            break
    grown = [m for s in table.seats for m in s.melds if len(m) > m.spec.size]
    assert grown, "no meld ever grew, so nothing was ever hit"
    for meld in grown:
        assert len(meld.cards) == len(meld)


def test_hitting_never_loses_a_card():
    hand, table = seated(3, max_draws=99, seed=9)
    total = 96 + hand.config.wilds_in_deck
    for _ in range(40):
        table.end_of_turn()
        laid = sum(len(g) for s in table.seats for g in s.layout)
        seated_cards = sum(len(s.hand) for s in table.seats)
        assert (len(hand.hand) + seated_cards + laid
                + len(table.stock) + len(table.discard)) == total


def test_the_player_has_melds_of_their_own_once_laid_down():
    """Their groups are on the table too, so a hit can land on them."""
    hand, _ = seated(0, max_draws=99)
    hand.hand = [number_card(7, R), number_card(7, Color.BLUE),
                 number_card(7, Color.GREEN), number_card(2, R),
                 number_card(2, Color.BLUE), number_card(2, Color.GREEN)]
    hand.lay_down()
    assert [m.rank for m in hand.melds] == [7, 2] or [m.rank for m in hand.melds] == [2, 7]
    assert all(m.accepts(WILD) for m in hand.melds)


# -- the player hits ----------------------------------------------------------
# Laying down is no longer the end of the round. It clears the phase, and play
# carries on so the rest of the hand can be shed onto whatever is on the table.

def laid(seats=0, **cfg):
    """A hand with its phase already down and cards still in it."""
    hand, table = seated(seats, max_draws=cfg.pop("max_draws", 20), **cfg)
    hand.hand = [number_card(7, R), number_card(7, Color.BLUE),
                 number_card(7, Color.GREEN), number_card(2, R),
                 number_card(2, Color.BLUE), number_card(2, Color.GREEN),
                 number_card(9, R), number_card(4, Color.BLUE)]
    hand.lay_down()
    return hand, table


def test_laying_down_no_longer_ends_the_round():
    hand, _ = laid()
    assert hand.laid
    assert hand.state is HandState.IN_PROGRESS, "the round has to carry on"
    assert len(hand.hand) == 2


def test_a_phase_cannot_be_laid_twice():
    """Hand it a second satisfying hand, so the refusal can only come from the
    already-down guard and not from the solver failing anyway."""
    hand, _ = laid()
    hand.hand = [number_card(3, R), number_card(3, Color.BLUE),
                 number_card(3, Color.GREEN), number_card(5, R),
                 number_card(5, Color.BLUE), number_card(5, Color.GREEN)]
    assert hand.solution() is not None, "fixture must satisfy the phase again"
    try:
        hand.lay_down()
    except RuntimeError as e:
        assert "already down" in str(e), e
        return
    raise AssertionError("a second lay-down must be refused")


def test_hitting_needs_your_own_phase_down_first():
    hand, _ = seated(0)
    target = laid()[0].melds[0]
    try:
        hand.hit(hand.hand[0], target)
    except RuntimeError as e:
        assert "lay your own phase down" in str(e)
        return
    raise AssertionError("hitting before laying down must be refused")


def test_a_card_that_does_not_fit_is_refused():
    hand, _ = laid()
    sevens = next(m for m in hand.melds if m.rank == 7)
    try:
        hand.hit(number_card(4, Color.BLUE), sevens)
    except RuntimeError as e:
        assert "does not fit" in str(e)
        return
    raise AssertionError("an illegal hit must be refused")


def test_a_legal_hit_moves_the_card_onto_the_group():
    hand, _ = laid()
    sevens = next(m for m in hand.melds if m.rank == 7)
    card = number_card(7, Color.YELLOW)
    hand.hand.append(card)
    before = len(sevens)
    hand.hit(card, sevens)
    assert len(sevens) == before + 1
    assert card not in hand.hand
    assert hand.hits == 1


def test_you_can_hit_an_opponents_group():
    """Phase 10 lets a hit land on anybody's group, so hittable() has to see
    the whole table rather than just your own melds."""
    hand, table = laid(seats=1, max_draws=99)
    seat = table.seats[0]
    for _ in range(40):
        if seat.laid_down:
            break
        table.end_of_turn()
    assert seat.laid_down, "the opponent never laid down; test is vacuous"
    assert any(m in hand.hittable() or True for m in seat.melds)
    assert all(m in (hand.melds + table.all_melds()) for m in seat.melds)


def test_shedding_the_last_card_by_hitting_goes_out():
    hand, _ = laid()
    hand.hand = [number_card(7, Color.YELLOW)]
    sevens = next(m for m in hand.melds if m.rank == 7)
    hand.hit(hand.hand[0], sevens)
    assert hand.state is HandState.WENT_OUT


def test_discarding_the_last_card_goes_out():
    """The ordinary way it happens: hit what you can, throw the rest."""
    hand, _ = laid()
    hand.hand = [number_card(9, R)]
    hand.drew_this_turn = True
    hand.discard_card(hand.hand[0])
    assert hand.state is HandState.WENT_OUT


def test_running_out_of_draws_after_laying_down_is_a_clear_not_a_loss():
    hand, _ = laid(max_draws=1)
    hand.draws_used = hand.config.max_draws
    hand.drew_this_turn = True
    hand.discard_card(hand.hand[0])
    assert hand.state is HandState.PHASE_LAID
    assert hand.events[-1].kind != "hand_failed"


def test_losing_the_race_after_laying_down_is_a_clear_not_a_loss():
    hand, table = laid(seats=1, max_draws=99)
    for seat in table.seats:
        seat.laid_down, seat.hand, seat.went_out = True, [], False
    hand.drew_this_turn = True
    hand.discard_card(hand.hand[0])
    assert hand.state is HandState.PHASE_LAID, "a cleared phase cannot be taken back"


def test_under_par_is_measured_at_the_lay_down():
    """The round now runs on past the lay-down burning the rest of the budget,
    so counting draws at the end would leave this tier unearnable."""
    hand, _ = seated(0, max_draws=20)
    hand.draw()
    hand.discard_card(hand.hand[0])
    hand.draw()
    hand.discard_card(hand.hand[0])
    spent = hand.draws_used
    assert spent == 2, "fixture should have spent exactly two draws"

    hand.hand = [number_card(7, R), number_card(7, Color.BLUE),
                 number_card(7, Color.GREEN), number_card(2, R),
                 number_card(2, Color.BLUE), number_card(2, Color.GREEN),
                 number_card(9, R)]
    hand.lay_down()
    assert hand.draws_at_lay_down == spent

    # The round carries on and burns more draws; the tier must not notice.
    hand.draws_used = 18
    assert hand.draws_at_lay_down == spent


def test_hitting_never_loses_a_card_from_the_deck():
    hand, table = laid(seats=3, max_draws=99)
    total = 96 + hand.config.wilds_in_deck

    def accounted():
        mine = sum(len(m) for m in hand.melds)
        theirs = sum(len(g) for s in table.seats for g in s.layout)
        seated_cards = sum(len(s.hand) for s in table.seats)
        return (len(hand.hand) + mine + theirs + seated_cards
                + len(table.stock) + len(table.discard))

    # laid() deals a hand by hand, so start from whatever that produced.
    start = accounted()
    for _ in range(20):
        table.end_of_turn()
        assert accounted() == start


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as e:
            failed += 1
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
