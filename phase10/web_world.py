from BaseClasses import Tutorial
from worlds.AutoWorld import WebWorld

from .options import option_groups, option_presets


class Phase10WebWorld(WebWorld):
    game = "Phase 10"
    theme = "partyTime"
    setup_en = Tutorial(
        "Multiworld Setup Guide",
        "A guide to setting up Phase 10 for MultiWorld.",
        "English",
        "setup_en.md",
        "setup/en",
        ["lighting8282"],
    )
    tutorials = [setup_en]
    option_groups = option_groups
    options_presets = option_presets
