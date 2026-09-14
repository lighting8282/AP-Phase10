from test.bases import WorldTestBase

from ..data import GAME_NAME
from ..world import Phase10World


class Phase10TestBase(WorldTestBase):
    game = GAME_NAME
    world: Phase10World
