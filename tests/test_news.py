import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import news


RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Fixture</title>
  <item><title>日銀、政策を維持</title><link>https://example.test/one</link>
    <description>市場への影響を確認する。</description>
    <pubDate>Tue, 06 Oct 2026 09:30:00 +0900</pubDate></item>
  <item><title>Summary omitted</title><link>https://example.test/two</link>
    <pubDate>Mon, 05 Oct 2026 23:00:00 GMT</pubDate></item>
</channel></rss>"""

TOYOTA = {"name_ja": "トヨタ自動車", "name_en": "TOYOTA MOTOR CORPORATION"}
ADVANTEST = {"name_ja": "アドバンテスト", "name_en": "ADVANTEST CORPORATION"}
SOFTBANK = {"name_ja": "ソフトバンクグループ", "name_en": "SoftBank Group Corp."}


def parsed(retrieved_at=None):
    return news.parse_rss(
        RSS.encode("utf-8"), "Fixture Source",
        retrieved_at or datetime(2026, 10, 7, 8, 0, tzinfo=timezone(timedelta(hours=9))),
    )


class NewsTest(unittest.TestCase):
    def test_rss_parse_normalizes_exact_minimal_record(self):
        records = parsed()
        self.assertEqual(records[0], {
            "source": "Fixture Source",
            "published_at": "2026-10-06T00:30:00+00:00",
            "retrieved_at": "2026-10-06T23:00:00+00:00",
            "title": "日銀、政策を維持",
            "summary": "市場への影響を確認する。",
            "url": "https://example.test/one",
        })
        self.assertEqual(records[1]["summary"], "")
        self.assertEqual(set(records[0]), set(news.RECORD_FIELDS))

    def test_utf8_roundtrip_and_daily_jsonl_content(self):
        with tempfile.TemporaryDirectory() as directory:
            written = news.store_news(parsed(), directory)
            path = Path(directory) / "news" / "raw" / "2026-10-06.jsonl"
            raw = path.read_bytes()
            stored = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
        self.assertEqual(written, stored)
        self.assertEqual(stored[0]["title"], "日銀、政策を維持")
        self.assertEqual(stored[0]["summary"], "市場への影響を確認する。")
        self.assertEqual(len(stored), 2)

    def test_same_url_in_same_batch_is_stored_once(self):
        record = parsed()[0]
        with tempfile.TemporaryDirectory() as directory:
            written = news.store_news([record, dict(record)], directory)
            lines = (Path(directory) / "news" / "raw" / "2026-10-06.jsonl").read_text(
                encoding="utf-8",
            ).splitlines()
        self.assertEqual(len(written), 1)
        self.assertEqual(len(lines), 1)

    def test_url_in_prior_daily_file_is_not_stored_again(self):
        first = parsed(datetime(2026, 10, 6, tzinfo=timezone.utc))[0]
        later = parsed(datetime(2026, 10, 8, tzinfo=timezone.utc))[0]
        with tempfile.TemporaryDirectory() as directory:
            news.store_news([first], directory)
            written = news.store_news([later], directory)
            later_path = Path(directory) / "news" / "raw" / "2026-10-08.jsonl"
        self.assertEqual(written, [])
        self.assertFalse(later_path.exists())

    def test_distinct_url_is_appended(self):
        records = parsed()
        with tempfile.TemporaryDirectory() as directory:
            news.store_news([records[0]], directory)
            written = news.store_news([records[1]], directory)
            path = Path(directory) / "news" / "raw" / "2026-10-06.jsonl"
            stored = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(written, [records[1]])
        self.assertEqual([item["url"] for item in stored], [
            "https://example.test/one", "https://example.test/two",
        ])

    def test_malformed_items_are_skipped_deterministically(self):
        malformed_items = """<rss version="2.0"><channel>
          <item><title>Missing URL</title><pubDate>Tue, 06 Oct 2026 00:00:00 GMT</pubDate></item>
          <item><title>Bad date</title><link>https://example.test/bad</link><pubDate>not-a-date</pubDate></item>
          <item><link>https://example.test/no-title</link><pubDate>Tue, 06 Oct 2026 00:00:00 GMT</pubDate></item>
        </channel></rss>"""
        self.assertEqual(news.parse_rss(
            malformed_items, "Fixture", datetime(2026, 10, 7, tzinfo=timezone.utc),
        ), [])

    def test_invalid_feed_and_naive_retrieval_time_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid RSS XML"):
            news.parse_rss("<rss", "Fixture", datetime.now(timezone.utc))
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            news.parse_rss(RSS, "Fixture", datetime(2026, 10, 7))

    def test_default_taxonomy_loads_and_has_only_controlled_ticker_fields(self):
        config = news.load_taxonomy()
        self.assertEqual(set(config["tickers"]), {"7203", "9984", "6857"})
        self.assertEqual(set(config["tickers"]["7203"]), {
            "additional_aliases", "sector_l1", "sector_l2", "themes",
        })
        self.assertNotIn("sector_l3", json.dumps(config))

    def test_company_alias_is_latin_case_insensitive_and_japanese_literal(self):
        latin = news.match_news({"title": "TOYOTA plans update", "summary": ""}, "7203", TOYOTA)
        japanese = news.match_news({"title": "トヨタが発表", "summary": ""}, "7203", TOYOTA)
        self.assertEqual(latin["company"]["keywords"], ["Toyota"])
        self.assertEqual(japanese["company"]["keywords"], ["トヨタ"])

    def test_sector_l1_and_l2_keywords_match(self):
        matches = news.match_news({
            "title": "Semiconductor outlook", "summary": "SEMICONDUCTOR EQUIPMENT demand",
        }, "6857", ADVANTEST)
        self.assertEqual(matches["sector_l1"], {
            "id": "semiconductor", "keywords": ["semiconductor"],
        })
        self.assertEqual(matches["sector_l2"], {
            "id": "semiconductor_equipment", "keywords": ["semiconductor equipment"],
        })

    def test_one_record_can_match_company_sectors_and_multiple_themes(self):
        record = {
            "title": "ADVANTEST CORPORATION advances AI semiconductor test systems",
            "summary": "半導体製造装置の需要",
            "url": "https://example.test/multi",
        }
        matches = news.match_news(record, "6857", ADVANTEST)
        self.assertEqual(set(matches), {"company", "sector_l1", "sector_l2", "themes"})
        self.assertEqual([item["id"] for item in matches["themes"]], [
            "ai", "semiconductor_test",
        ])
        self.assertEqual(record["url"], "https://example.test/multi")

    def test_unrelated_article_has_no_match_and_ai_uses_boundaries(self):
        self.assertEqual(news.match_news({
            "title": "Retail sales said to rise", "summary": "Consumer outlook",
        }, "6857", ADVANTEST), {})

    def test_unregistered_ticker_uses_identity_without_sector_or_theme(self):
        matches = news.match_news({
            "title": "ACME HOLDINGS announces AI semiconductor investment", "summary": "",
        }, "0000", {"name_ja": "アクメ", "name_en": "Acme Holdings"})
        self.assertEqual(matches, {"company": {"keywords": ["Acme Holdings"]}})

    def test_registered_ticker_combines_identity_and_additional_aliases(self):
        automatic = news.match_news({"title": "TOYOTA MOTOR CORPORATION update", "summary": ""},
                                    "7203", TOYOTA)
        enriched = news.match_news({"title": "Toyota update", "summary": ""}, "7203", TOYOTA)
        self.assertEqual(automatic["company"]["keywords"], ["TOYOTA MOTOR CORPORATION", "Toyota"])
        self.assertEqual(enriched["company"]["keywords"], ["Toyota"])

    def test_no_identity_and_no_enrichment_returns_no_company_match(self):
        self.assertEqual(news.match_news({"title": "Anything", "summary": ""}, "0000", None), {})

    def test_nullable_sector_and_l2_without_l1_validation(self):
        config = news.load_taxonomy()
        self.assertIsNone(config["tickers"]["9984"]["sector_l1"])
        config["tickers"]["9984"]["sector_l2"] = "semiconductor_equipment"
        with self.assertRaisesRegex(ValueError, "sector_l2 requires sector_l1"):
            news.validate_taxonomy(config)

    def test_seed_aliases_and_theme_mappings(self):
        config = news.load_taxonomy()
        self.assertEqual(config["tickers"]["9984"]["additional_aliases"], ["ソフトバンクG", "SBG"])
        self.assertNotIn("ソフトバンク", config["tickers"]["9984"]["additional_aliases"])
        for alias in ("SBG", "ソフトバンクG"):
            self.assertIn("company", news.match_news({"title": alias, "summary": ""},
                                                     "9984", SOFTBANK))
        self.assertNotIn("company", news.match_news({"title": "ソフトバンクが発表", "summary": ""},
                                                    "9984", SOFTBANK))
        self.assertEqual(config["tickers"]["7203"]["themes"], ["hv", "ev"])
        toyota = news.match_news({"title": "HVとEVの需要", "summary": ""}, "7203", TOYOTA)
        self.assertEqual([item["id"] for item in toyota["themes"]], ["hv", "ev"])
        self.assertEqual(config["tickers"]["6857"]["themes"],
                         ["ai", "semiconductor_test", "hbm", "hpc"])
        self.assertNotIn("semiconductor", config["tickers"]["6857"]["themes"])
        advantest = news.match_news({
            "title": "Semiconductor equipment for HBM and HPC", "summary": "",
        }, "6857", ADVANTEST)
        self.assertEqual(advantest["sector_l1"]["id"], "semiconductor")
        self.assertEqual(advantest["sector_l2"]["id"], "semiconductor_equipment")
        self.assertEqual([item["id"] for item in advantest["themes"]], ["hbm", "hpc"])

    def test_latin_aliases_are_case_insensitive_and_boundary_safe(self):
        self.assertIn("company", news.match_news({"title": "sbg strategy", "summary": ""},
                                                 "9984", SOFTBANK))
        self.assertNotIn("company", news.match_news({"title": "XSBG strategy", "summary": ""},
                                                    "9984", SOFTBANK))

    def test_undefined_theme_reference_is_rejected(self):
        config = news.load_taxonomy()
        config["tickers"]["7203"]["themes"] = ["not_defined"]
        with self.assertRaisesRegex(ValueError, "references undefined theme not_defined"):
            news.validate_taxonomy(config)

    def test_invalid_json_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "taxonomy.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cannot load news taxonomy"):
                news.load_taxonomy(path)


if __name__ == "__main__":
    unittest.main()
