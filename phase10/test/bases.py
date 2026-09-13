from test.bases import WorldTestBase

from ..world import Phase10World


class Phase10TestBase(WorldTestBase):
    game = "Phase 10"
    world: Phase10World
