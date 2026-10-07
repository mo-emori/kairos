import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

import news

FIXTURES = Path(__file__).with_name("fixtures")


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
    def _write_records(self, directory, kind, records):
        path = Path(directory) / "news" / kind / "fixture.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
            encoding="utf-8",
        )

    def _raw(self, url, published, retrieved, title="Macro update", summary="Raw summary"):
        return {
            "source": "Market Source", "published_at": published,
            "retrieved_at": retrieved, "title": title, "summary": summary, "url": url,
        }

    def test_analysis_cutoff_is_exclusive_next_midnight_in_tokyo(self):
        self.assertEqual(
            news.analysis_cutoff(date(2026, 10, 7)),
            datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc),
        )

    def test_selection_as_of_content_fallback_and_historical_empty(self):
        sources = [{
            "source_id": "market", "name": "Market Source",
            "url": "https://example.test/feed", "default_layer": "market", "enabled": True,
        }]
        raw = [
            self._raw("https://example.test/eligible", "2026-10-07T14:58:00+00:00",
                      "2026-10-07T14:59:00+00:00"),
            self._raw("https://example.test/future-published", "2026-10-07T15:00:00+00:00",
                      "2026-10-07T14:00:00+00:00"),
            self._raw("https://example.test/future-retrieved", "2026-10-07T13:00:00+00:00",
                      "2026-10-07T15:00:00+00:00"),
        ]
        late_text = "LATE-CONTENT " + ("x" * 700)
        content = [{
            "url": raw[0]["url"], "content_retrieved_at": "2026-10-07T15:00:00+00:00",
            "status": "success", "text": late_text,
        }]
        with tempfile.TemporaryDirectory() as directory:
            self._write_records(directory, "raw", raw)
            self._write_records(directory, "content", content)
            selected = news.select_news_context(
                directory, date(2026, 10, 7), "0000", None, 3,
                sources=sources, taxonomy=news.load_taxonomy(),
            )
            historical = news.select_news_context(
                directory, date(2026, 6, 30), "0000", None, 3,
                sources=sources, taxonomy=news.load_taxonomy(),
            )
            content[0]["content_retrieved_at"] = "2026-10-07T14:59:30+00:00"
            self._write_records(directory, "content", content)
            enriched = news.select_news_context(
                directory, date(2026, 10, 7), "0000", None, 3,
                sources=sources, taxonomy=news.load_taxonomy(),
            )
        self.assertEqual([item["url"] for item in selected], [raw[0]["url"]])
        self.assertEqual(selected[0]["excerpt"], "Raw summary")
        self.assertEqual(historical, [])
        self.assertEqual(enriched[0]["excerpt"], news.content_excerpt(late_text))
        self.assertNotIn(late_text, json.dumps(enriched, ensure_ascii=False))
        self.assertNotIn("retrieved_at", json.dumps(enriched))

    def test_per_layer_top_n_combines_matches_and_deduplicates_url(self):
        sources = [{
            "source_id": "market", "name": "Market Source",
            "url": "https://example.test/feed", "default_layer": "market", "enabled": True,
        }]
        raw = [
            self._raw(f"https://example.test/{index}", f"2026-10-0{index}T00:00:00+00:00",
                      "2026-10-07T00:00:00+00:00")
            for index in range(1, 5)
        ]
        raw[0]["title"] = "TOYOTA advances EV and semiconductor strategy"
        with tempfile.TemporaryDirectory() as directory:
            self._write_records(directory, "raw", raw)
            selected = news.select_news_context(
                directory, date(2026, 10, 7), "7203", TOYOTA, 2,
                sources=sources, taxonomy=news.load_taxonomy(),
            )
        self.assertEqual([item["url"] for item in selected], [
            "https://example.test/4", "https://example.test/3", "https://example.test/1",
        ])
        combined = selected[-1]
        self.assertEqual(combined["matches"]["layers"], ["company", "market", "theme"])
        self.assertEqual(combined["matches"]["themes"], ["ev"])
        self.assertEqual(len({item["url"] for item in selected}), len(selected))

    def test_corrupt_raw_selection_fails_clearly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "news" / "raw" / "bad.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text("{broken\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid raw news JSON"):
                news.select_news_context(directory, date(2026, 10, 7), "7203", TOYOTA, 3)

    def test_report_news_context_shows_selected_item_and_no_news_state(self):
        from report import _news_context

        item = {
            "source": "Official", "published_at": "2026-10-07T00:00:00+00:00",
            "title": "Evidence", "excerpt": "Compact excerpt",
            "url": "https://example.test/evidence",
            "matches": {"layers": ["company", "market"],
                        "company": {"ticker": "7203"}},
        }
        rendered = _news_context([item])
        self.assertIn("Official", rendered)
        self.assertIn("Compact excerpt", rendered)
        self.assertIn("company:7203", rendered)
        self.assertIn(item["url"], rendered)
        self.assertEqual(_news_context([]), "Unavailable / no eligible matching News")

    def test_local_japanese_and_english_html_extract_main_text(self):
        for fixture, expected in (("article_ja.html", "日本銀行"),
                                  ("article_en.html", "economic conditions")):
            with self.subTest(fixture=fixture), \
                 patch.object(news, "fetch_url", return_value=(FIXTURES / fixture).read_text(
                     encoding="utf-8")):
                text = news.retrieve_article_text(f"https://example.test/{fixture}")
            self.assertIn(expected, text)

    def test_content_excerpt_is_normalized_and_exactly_600_characters(self):
        text = "  " + ("あ" * 599) + "\r\nKEYWORD-after-limit  "
        self.assertEqual(news.content_excerpt(text), ("あ" * 599) + "\n")
        self.assertEqual(len(news.content_excerpt(text)), 600)

    def test_match_news_uses_excerpt_and_metadata_fallback_is_unchanged(self):
        record = {"title": "Unrelated", "summary": "No relevant phrase"}
        content = ("x" * 100) + " Toyota " + ("y" * 600)
        self.assertIn("company", news.match_news(record, "7203", TOYOTA,
                                                  content_text=content))
        self.assertEqual(news.match_news(record, "7203", TOYOTA), {})

    def test_success_and_failure_are_terminal_and_raw_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            news.store_news(parsed(), directory)
            raw_path = Path(directory) / "news" / "raw" / "2026-10-06.jsonl"
            original = raw_path.read_bytes()
            answers = [None, "Useful article body " * 5]
            with patch.object(news, "fetch_url", side_effect=answers) as fetch, \
                 patch.object(news, "extract", side_effect=lambda html: html), \
                 patch.object(news.time, "sleep") as sleep:
                first = news.enrich_news(
                    directory, now=lambda: datetime(2026, 10, 7, tzinfo=timezone.utc),
                )
                second = news.enrich_news(directory)
            raw_after = raw_path.read_bytes()
            content_path = Path(directory) / "news" / "content" / "2026-10-07.jsonl"
            stored = [json.loads(line) for line in content_path.read_text(
                encoding="utf-8").splitlines()]
        self.assertEqual(first, {"processed": 2, "success": 1,
                                 "already_enriched": 0, "failed": 1})
        self.assertEqual(second, {"processed": 0, "success": 0,
                                  "already_enriched": 2, "failed": 0})
        self.assertEqual([item["status"] for item in stored], ["failed", "success"])
        self.assertEqual(fetch.call_count, 2)
        sleep.assert_called_once_with(news.ENRICH_DELAY_SECONDS)
        self.assertEqual(raw_after, original)

    def test_corrupt_content_store_fails_clearly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "news" / "content" / "2026-10-07.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text("{broken\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid news content JSON"):
                news.load_content_urls(directory)

    def test_source_registry_loads_exact_minimal_verified_entries(self):
        sources = news.load_sources()
        self.assertEqual([source["source_id"] for source in sources], [
            "boj_updates", "frb_monetary_policy",
        ])
        self.assertTrue(all(set(source) == news.SOURCE_FIELDS for source in sources))
        self.assertTrue(all(source["default_layer"] == "market" for source in sources))

    def test_source_registry_validation_rejects_invalid_values(self):
        valid = {
            "source_id": "one", "name": "One", "url": "https://example.test/feed.xml",
            "default_layer": "market", "enabled": True,
        }
        cases = [
            [dict(valid, extra=True)],
            [valid, dict(valid)],
            [dict(valid, url="file:///feed.xml")],
            [dict(valid, enabled=1)],
            [dict(valid, default_layer="other")],
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                news.validate_sources(case)

    def test_official_format_fixtures_normalize_aware_timestamps(self):
        retrieved = datetime(2026, 10, 7, tzinfo=timezone.utc)
        boj = news.parse_rss((FIXTURES / "boj_whatsnew.xml").read_bytes(), "BOJ", retrieved)
        fed = news.parse_rss((FIXTURES / "frb_press_monetary.xml").read_bytes(), "Fed", retrieved)
        self.assertEqual(boj[0]["published_at"], "2026-09-30T23:50:00+00:00")
        self.assertEqual(fed[0]["published_at"], "2026-09-16T18:00:00+00:00")
        self.assertEqual(boj[0]["retrieved_at"], "2026-10-07T00:00:00+00:00")

    def test_fetch_enabled_sources_skips_disabled_and_uses_http_contract(self):
        sources = [
            {"source_id": "on", "name": "On", "url": "https://example.test/on.xml",
             "default_layer": "market", "enabled": True},
            {"source_id": "off", "name": "Off", "url": "https://example.test/off.xml",
             "default_layer": "market", "enabled": False},
        ]
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = RSS.encode("utf-8")
        with patch.object(news, "urlopen", return_value=response) as mocked:
            fetched = news.fetch_enabled_sources(
                sources, datetime(2026, 10, 7, tzinfo=timezone.utc),
            )
        self.assertEqual(len(fetched), 1)
        request = mocked.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.test/on.xml")
        self.assertEqual(request.get_header("User-agent"), news.USER_AGENT)
        self.assertEqual(mocked.call_args.kwargs["timeout"], 15)

    def test_multiple_sources_retrieve_store_and_repeat_without_duplicates(self):
        sources = [
            {"source_id": "boj", "name": "BOJ", "url": "https://example.test/boj.xml",
             "default_layer": "market", "enabled": True},
            {"source_id": "fed", "name": "Fed", "url": "https://example.test/fed.xml",
             "default_layer": "market", "enabled": True},
        ]
        payloads = [
            (FIXTURES / "boj_whatsnew.xml").read_bytes(),
            (FIXTURES / "frb_press_monetary.xml").read_bytes(),
        ]
        retrieved = datetime(2026, 10, 7, tzinfo=timezone.utc)

        def responses():
            result = []
            for payload in payloads:
                response = unittest.mock.MagicMock()
                response.__enter__.return_value.read.return_value = payload
                result.append(response)
            return result

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(news, "urlopen", side_effect=responses()):
                first = news.fetch_enabled_sources(sources, retrieved)
            written = [news.store_news(records, directory) for _, records in first]
            with patch.object(news, "urlopen", side_effect=responses()):
                second = news.fetch_enabled_sources(sources, retrieved)
            repeated = [news.store_news(records, directory) for _, records in second]
        self.assertEqual([len(items) for items in written], [1, 1])
        self.assertEqual(repeated, [[], []])

    def test_fetch_failure_is_fail_fast_and_identifies_source(self):
        source = {"source_id": "broken", "name": "Broken",
                  "url": "https://example.test/broken.xml",
                  "default_layer": "market", "enabled": True}
        with patch.object(news, "urlopen", side_effect=URLError("offline")), \
             self.assertRaisesRegex(ValueError, "source=broken.*offline"):
            news.fetch_enabled_sources([source], datetime.now(timezone.utc))

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

    def test_null_identity_still_selects_default_market_news(self):
        sources = [{
            "source_id": "market", "name": "Market Source",
            "url": "https://example.test/feed", "default_layer": "market", "enabled": True,
        }]
        raw = [self._raw(
            "https://example.test/market", "2026-10-06T00:00:00+00:00",
            "2026-10-06T01:00:00+00:00",
        )]
        with tempfile.TemporaryDirectory() as directory:
            self._write_records(directory, "raw", raw)
            selected = news.select_news_context(
                directory, date(2026, 10, 7), "0000", None, 3,
                sources=sources, taxonomy=news.load_taxonomy(),
            )
        self.assertEqual([item["url"] for item in selected], ["https://example.test/market"])
        self.assertEqual(selected[0]["matches"]["layers"], ["market"])

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
