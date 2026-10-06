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
            lines = list((Path(directory) / "news" / "raw" / "2026-10-06.jsonl").open(encoding="utf-8"))
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


if __name__ == "__main__":
    unittest.main()
