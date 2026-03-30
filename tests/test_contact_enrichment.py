import unittest

from src.services.contact_enrichment import _collect_keyword_tags


class ContactEnrichmentKeywordTagsTests(unittest.TestCase):
    def test_collect_keyword_tags_maps_startupper_to_startap_tag(self) -> None:
        self.assertEqual(_collect_keyword_tags("стартапер, развивает новый сервис"), ["#стартап"])

    def test_collect_keyword_tags_deduplicates_multiple_startup_variants(self) -> None:
        self.assertEqual(
            _collect_keyword_tags("фаундер стартапа", "startup founder"),
            ["#стартап"],
        )

    def test_collect_keyword_tags_extracts_business_and_moscow(self) -> None:
        self.assertEqual(
            _collect_keyword_tags("владелец бизнеса из Москвы"),
            ["#бизнес", "#москва"],
        )


if __name__ == "__main__":
    unittest.main()
