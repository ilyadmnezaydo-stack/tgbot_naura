import unittest

from src.bot.handlers.payments import _parse_donation_amount_text


class DonationAmountParsingTests(unittest.TestCase):
    def test_accepts_plain_integer(self) -> None:
        self.assertEqual(_parse_donation_amount_text("777"), 777)

    def test_accepts_stars_suffix_and_spaces(self) -> None:
        self.assertEqual(_parse_donation_amount_text("1 000 ⭐"), 1000)
        self.assertEqual(_parse_donation_amount_text("250 stars"), 250)
        self.assertEqual(_parse_donation_amount_text("300 звезды"), 300)

    def test_rejects_zero_negative_and_garbage(self) -> None:
        self.assertIsNone(_parse_donation_amount_text("0"))
        self.assertIsNone(_parse_donation_amount_text("-5"))
        self.assertIsNone(_parse_donation_amount_text("сколько не жалко"))


if __name__ == "__main__":
    unittest.main()
