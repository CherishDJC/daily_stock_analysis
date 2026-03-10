# -*- coding: utf-8 -*-
"""Tests for news title/snippet sanitization."""

import sys
import unittest

from unittest.mock import MagicMock

# Mock newspaper before search_service import.
if "newspaper" not in sys.modules:
    mock_np = MagicMock()
    mock_np.Article = MagicMock()
    mock_np.Config = MagicMock()
    sys.modules["newspaper"] = mock_np

from src.news_text import is_probably_garbled_text, sanitize_news_snippet
from src.search_service import BaseSearchProvider, SearchResponse, SearchResult


class _DummyProvider(BaseSearchProvider):
    def __init__(self):
        super().__init__(["dummy-key"], "Dummy")

    def _do_search(self, query: str, api_key: str, max_results: int, days: int = 7) -> SearchResponse:
        return SearchResponse(
            query=query,
            results=[
                SearchResult(
                    title="贵州茅台1400.02(-0.14%)_个股资讯- 新浪财经",
                    snippet="Ӫĸ︴ר⣺в 2026-03-04 07:15 20һ幫˾ֻع๫ ²ӻعܶ",
                    url="https://vip.stock.finance.sina.com.cn/example",
                    source="finance.sina.com.cn",
                )
            ],
            provider=self.name,
            success=True,
        )


class NewsTextSanitizationTestCase(unittest.TestCase):
    def test_detects_mojibake_like_snippet(self) -> None:
        self.assertTrue(
            is_probably_garbled_text("Ӫĸ︴ר⣺в 2026-03-04 07:15 20һ幫˾ֻع๫ ²ӻعܶ")
        )

    def test_preserves_normal_chinese_snippet(self) -> None:
        text = "公司回购进展正常，市场关注分红预期和业绩稳定性。"
        self.assertFalse(is_probably_garbled_text(text))
        self.assertEqual(sanitize_news_snippet(text), text)

    def test_base_provider_search_sanitizes_results(self) -> None:
        provider = _DummyProvider()
        response = provider.search("贵州茅台", max_results=3)

        self.assertTrue(response.success)
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].title, "贵州茅台1400.02(-0.14%)_个股资讯- 新浪财经")
        self.assertEqual(response.results[0].snippet, "")


if __name__ == "__main__":
    unittest.main()
