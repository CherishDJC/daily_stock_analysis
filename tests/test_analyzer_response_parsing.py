# -*- coding: utf-8 -*-
"""Tests for analyzer response parsing fallbacks."""

import unittest

from src.analyzer import GeminiAnalyzer


class AnalyzerResponseParsingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)

    def test_parse_response_detects_provider_error_payload(self) -> None:
        response_text = """
        {
          "code": "600519",
          "name": "贵州茅台",
          "operation_advice": "观望",
          "trend_prediction": "未知",
          "analysis_summary": "",
          "dashboard": {
            "code": "INVALID_API_KEY",
            "message": "Invalid API key"
          }
        }
        """

        result = self.analyzer._parse_response(response_text, "600519", "贵州茅台")

        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "INVALID_API_KEY: Invalid API key")
        self.assertEqual(result.analysis_summary, "AI 分析失败：INVALID_API_KEY: Invalid API key")
        self.assertEqual(result.operation_advice, "观望")
        self.assertEqual(result.trend_prediction, "未知")

    def test_parse_response_detects_invalid_dashboard_html_payload(self) -> None:
        response_text = """
        {
          "code": "600519",
          "name": "贵州茅台",
          "operation_advice": "观望",
          "trend_prediction": "未知",
          "analysis_summary": "",
          "dashboard": {
            "b&&(b.classList.remove(\\"hidden\\"),c.addEventListener(\\"click\\",function(){c.classList.add(\\"hidden\\");a.getElementById(\\"cf-footer-ip\\").classList.remove(\\"hidden\\")": ""
          }
        }
        """

        result = self.analyzer._parse_response(response_text, "600519", "贵州茅台")

        self.assertFalse(result.success)
        self.assertIn("AI 返回了无效响应", result.analysis_summary)


if __name__ == "__main__":
    unittest.main()
