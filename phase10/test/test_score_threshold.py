"""The DeathLink threshold reaches the clients through slot data."""

from .bases import Phase10TestBase


class TestScoreThresholdDefault(Phase10TestBase):
    options = {"death_link": True}

    def test_the_default_threshold_is_sent(self) -> None:
        data = self.world.fill_slot_data()
        self.assertTrue(data["death_link"])
        self.assertEqual(data["score_threshold"], 500)


class TestScoreThresholdChosen(Phase10TestBase):
    options = {"death_link": True, "score_threshold": 250}

    def test_a_chosen_threshold_is_sent(self) -> None:
        self.assertEqual(self.world.fill_slot_data()["score_threshold"], 250)
