"""The DeathLink threshold reaches the clients through slot data."""

from .bases import Phase10TestBase


class TestDeathLinkScoreDefault(Phase10TestBase):
    options = {"death_link": True}

    def test_the_default_threshold_is_sent(self) -> None:
        data = self.world.fill_slot_data()
        self.assertTrue(data["death_link"])
        self.assertEqual(data["death_link_score"], 500)


class TestDeathLinkScoreChosen(Phase10TestBase):
    options = {"death_link": True, "death_link_score": 250}

    def test_a_chosen_threshold_is_sent(self) -> None:
        self.assertEqual(self.world.fill_slot_data()["death_link_score"], 250)
