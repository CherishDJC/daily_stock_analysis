# -*- coding: utf-8 -*-
"""Unit tests for GDELT public search provider."""

import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock newspaper before search_service import (optional dependency)
if "newspaper" not in sys.modules:
    mock_np = MagicMock()
    mock_np.Article = MagicMock()
    mock_np.Config = MagicMock()
    sys.modules["newspaper"] = mock_np

from src.search_service import GDELTSearchProvider, SearchService


class GDELTSearchProviderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        GDELTSearchProvider._last_request_ts = 0.0

    def test_search_service_is_available_without_api_keys(self) -> None:
        service = SearchService()

        self.assertTrue(service.is_available)
        self.assertIn("GDELT", service.provider_names)

    def test_symbol_detection_requires_all_caps(self) -> None:
        self.assertFalse(GDELTSearchProvider._looks_like_symbol("Tesla"))
        self.assertTrue(GDELTSearchProvider._looks_like_symbol("TSLA"))

    def test_build_query_prefers_identity_and_context(self) -> None:
        query = GDELTSearchProvider._build_query("贵州茅台 600519 股票 最新消息")
        self.assertEqual(query, '("贵州茅台" OR "600519")')

        query_with_context = GDELTSearchProvider._build_query("Tesla TSLA earnings revenue growth forecast")
        self.assertEqual(query_with_context, '("Tesla" OR "TSLA") AND ("earnings" OR "revenue" OR "growth")')

    @patch("src.search_service._get_with_retry")
    def test_provider_parses_json_articles(self, mock_get: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "articles": [
                {
                    "title": "茅台发布年报",
                    "url": "https://example.com/news/maotai",
                    "domain": "example.com",
                    "language": "Chinese",
                    "sourcecountry": "China",
                    "seendate": "20260309T120000Z",
                }
            ]
        }
        mock_get.return_value = mock_response

        provider = GDELTSearchProvider()
        response = provider.search("贵州茅台 600519 股票 最新消息", max_results=5, days=2)

        self.assertTrue(response.success)
        self.assertEqual(response.provider, "GDELT")
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].title, "茅台发布年报")
        self.assertEqual(response.results[0].source, "example.com")
        self.assertEqual(response.results[0].published_date, "2026-03-09 12:00")
        self.assertIn("语言: Chinese", response.results[0].snippet)

    @patch("src.search_service.time.sleep")
    @patch("src.search_service._get_with_retry")
    def test_provider_retries_once_after_http_429(self, mock_get: MagicMock, mock_sleep: MagicMock) -> None:
        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.text = "Please limit requests to one every 5 seconds."

        success = MagicMock()
        success.status_code = 200
        success.json.return_value = {
            "articles": [
                {
                    "title": "茅台公告",
                    "url": "https://example.com/news/notice",
                    "domain": "example.com",
                    "seendate": "20260309T130000Z",
                }
            ]
        }

        mock_get.side_effect = [rate_limited, success]

        provider = GDELTSearchProvider()
        response = provider.search("贵州茅台 600519 股票 最新消息", max_results=5, days=2)

        self.assertTrue(response.success)
        self.assertEqual(response.provider, "GDELT")
        self.assertEqual(len(response.results), 1)
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called()


if __name__ == "__main__":
    unittest.main()
