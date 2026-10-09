import logging
from collections.abc import Mapping
from typing import Any

from worlds.AutoWorld import World

from . import items, locations, regions, rules, web_world
from . import options as phase10_options
from .data import (
    AP_POINT, GAME_NAME, HANDS_WON_MILESTONES, PHASE_COUNT, PRICE_PROGRESSION,
    PRICE_TRAP_OR_FILLER, STORE_ALWAYS_OPEN,
    STORE_LADDER, price_for, store_location_name,
)


#: The largest ladder store that fills reliably when the Hands Won checks wait
#: on clears. See generate_early.
NEW_PHASES_LADDER_SLOTS = 6


class Phase10World(World):
    """
    Phase 10 is a rummy-style card game of ten escalating objectives. This
    implementation seats you against computer players who race you to go out,
    and gives you a draw budget on top -- a round ends on whichever comes
    first. Archipelago decides which phases you may attempt, and how many wild
    cards, draws and skips you get. Set opponents to 0 for the solo game.
    """

    game = GAME_NAME
    web = web_world.Phase10WebWorld()

    options_dataclass = phase10_options.Phase10Options
    options: phase10_options.Phase10Options

    location_name_to_id = locations.LOCATION_NAME_TO_ID
    item_name_to_id = items.ITEM_NAME_TO_ID

    #: Decided in generate_early, because the store's locations are built
    #: before the item pool is and both have to agree on its size.
    store_points: int = 0

    def generate_early(self) -> None:
        """Trim the store to what the location budget can carry.

        The slot count is an option, but at one check a phase there are thirty
        locations against a floor of twenty-nine required items, so a six-slot
        store asks for points there is nowhere to put. Trimming here rather
        than raising an error keeps a legal option combination generating.
        """
        from .rules import MIN_EXTRA_DRAWS, MIN_WILD_CARDS

        self.fit_hands_won_logic()

        base = PHASE_COUNT * int(self.options.checks_per_phase) + len(HANDS_WON_MILESTONES)
        floor = PHASE_COUNT + MIN_WILD_CARDS + MIN_EXTRA_DRAWS
        slots, points = items.plan_store(
            base, int(self.options.store_slots), floor,
            int(self.options.store_buff_points), self.store_gating)
        self.options.store_slots.value = slots
        self.store_points = points

    def fit_hands_won_logic(self) -> None:
        """Adjust what new_phases cannot fill, rather than fail to generate.

        Without the free Hands Won checks a seed opens narrower and is denser
        with required items, and three option settings stopped filling. Each
        one is changed here with a warning naming it. Measured on solo seeds,
        which are the tightest a seed gets; a multiworld has more room.
        """
        options = self.options
        if not self.hands_won_grind_free:
            return
        new_phases = phase10_options.HandsWonLogic

        # At one check a phase all but three locations already hold a required
        # item, and new_phases takes the last three Hands Won checks from them.
        # It failed every seed.
        if int(options.checks_per_phase) == 1:
            self.warn("does not fit checks_per_phase 1; using replays")
            options.hands_won_logic.value = new_phases.option_replays
            return

        # One starting phase opens the seed with two checks, its own and Hands
        # Won: 1, and fill strands itself in that: 8 of 300 seeds. Two starting
        # phases, with two more easy ones placed early, failed none.
        if int(options.starting_phases) < 2:
            self.warn(f"opens with at least 2 phases; starting_phases raised "
                      f"from {int(options.starting_phases)} to 2")
            options.starting_phases.value = 2

        # The ladder's last slots end one long chain -- eleven points, then
        # fourteen -- and fill strands itself in it: 4 of 1,000 seeds at eight
        # slots, 1 of 800 at seven, none of 3,000 at six. The always-open store
        # asks three points a slot rather than a chain, and fills at eight.
        if (self.store_gating == STORE_LADDER
                and int(options.store_slots) > NEW_PHASES_LADDER_SLOTS):
            self.warn(f"fits a ladder store of at most {NEW_PHASES_LADDER_SLOTS} "
                      f"slots; store_slots lowered from {int(options.store_slots)}")
            options.store_slots.value = NEW_PHASES_LADDER_SLOTS

    def warn(self, what: str) -> None:
        logging.warning(f"{self.player_name}: hands_won_logic new_phases {what}.")

    def create_regions(self) -> None:
        regions.create_and_connect_regions(self)
        locations.create_all_locations(self)

    def set_rules(self) -> None:
        rules.set_all_rules(self)

    def create_items(self) -> None:
        items.create_all_items(self)

    def create_item(self, name: str) -> items.Phase10Item:
        return items.create_item_with_correct_classification(self, name)

    def get_filler_item_name(self) -> str:
        return items.get_random_filler_item_name(self)

    def fill_slot_data(self) -> Mapping[str, Any]:
        # The client builds its GameConfig from these; the engine's knobs map
        # one-to-one onto the option names.
        data = self.options.as_dict(
            "goal", "phases_to_win", "starting_draws", "checks_per_phase",
            "death_link", "score_threshold", "score_traps", "opponents", "store_slots",
        )
        # Spelled out rather than sent as the Choice's integer: the engine's
        # knob is the word, both clients read the word, and a number here
        # would make the two agree only by coincidence.
        data["skip_mode"] = ("deny" if int(self.options.skip_mode)
                             == phase10_options.SkipMode.option_deny else "dig")
        data["store_gating"] = self.store_gating
        data["opponent_phase"] = ("own" if int(self.options.opponent_phase)
                                  == phase10_options.OpponentPhase.option_own else "match")
        if self.store_gating == STORE_ALWAYS_OPEN:
            data["store_prices"] = self.store_slot_prices()
        return data

    def store_slot_prices(self) -> list[int]:
        """Each always-open slot's price, from the item fill put in it.

        Slot data is written after fill, which is the first moment the price
        can be known; the logic and the pool were sized for the worst case
        before it. An empty slot only happens outside a real generation -- a
        unit test that stops short of fill -- and is priced at the worst case,
        which overcharges and so can never strand anything.
        """
        prices = []
        for slot in range(1, int(self.options.store_slots) + 1):
            item = self.get_location(store_location_name(slot)).item
            if item is None:
                prices.append(PRICE_PROGRESSION)
            elif item.player == self.player and item.name == AP_POINT:
                # Your own AP Point is progression, but charging three for it
                # would make the slot a loss of two. It costs one: change, not
                # a purchase. Keeping points out of the store instead made
                # fill fail in 1 seed in 10 at the default size.
                prices.append(PRICE_TRAP_OR_FILLER)
            else:
                prices.append(price_for(item.advancement, item.useful))
        return prices

    @property
    def hands_won_grind_free(self) -> bool:
        """Whether Hands Won checks wait on clearing that many phases."""
        return (int(self.options.hands_won_logic)
                == phase10_options.HandsWonLogic.option_new_phases)

    @property
    def store_gating(self) -> str:
        """The word for `store_gating`, as the data helpers and clients take it."""
        return (STORE_ALWAYS_OPEN if int(self.options.store_gating)
                == phase10_options.StoreGating.option_always_open else STORE_LADDER)
