from BaseClasses import Tutorial
from worlds.AutoWorld import WebWorld

from .data import GAME_NAME
from .options import option_groups, option_presets


class Phase10WebWorld(WebWorld):
    game = GAME_NAME
    theme = "partyTime"
    setup_en = Tutorial(
        "Multiworld Setup Guide",
        "A guide to setting up AP_10 for MultiWorld.",
        "English",
        "setup_en.md",
        "setup/en",
        ["lighting8282"],
    )
    tutorials = [setup_en]
    option_groups = option_groups
    options_presets = option_presets
