import unittest

from src.bot.handlers.contacts import _merge_contact_tags


class MergeContactTagsTests(unittest.TestCase):
    def test_preserves_existing_tags_and_appends_new_inferred_ones(self) -> None:
        merged = _merge_contact_tags(
            ["#vip", "#работа"],
            ["#маркетинг", "#работа"],
        )

        self.assertEqual(merged, ["#vip", "#работа", "#маркетинг"])

    def test_normalizes_missing_hash_and_deduplicates_case_insensitively(self) -> None:
        merged = _merge_contact_tags(
            ["семья", "#Friends"],
            ["#Семья", "friends", "travel"],
        )

        self.assertEqual(merged, ["#семья", "#Friends", "#travel"])


if __name__ == "__main__":
    unittest.main()
