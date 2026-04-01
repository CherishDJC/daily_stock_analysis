# -*- coding: utf-8 -*-
"""Tests for screener history storage and payload parsing."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import Config
from src.storage import DatabaseManager


class ScreenerHistoryTestCase(unittest.TestCase):
    """Screener history should preserve result payload metadata."""

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._temp_dir.name, "test_screener_history.db")
        os.environ["DATABASE_PATH"] = self._db_path

        Config._instance = None
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        self._temp_dir.cleanup()

    def test_screener_detail_exposes_payload_metadata(self) -> None:
        """Detail view should return status, provider and error metadata from payload JSON."""
        payload = {
            "dashboard": {"query": "测试条件", "results": []},
            "results": [],
            "report_markdown": "测试报告",
            "status": "failed",
            "provider": "openai",
            "error_message": "上游模型网关超时",
        }
        record_id = self.db.save_screener_result(
            query="测试条件",
            results_json=json.dumps(payload, ensure_ascii=False),
            result_count=0,
            strategy_summary="测试摘要",
            risk_warning="测试风险",
            total_steps=2,
            total_tokens=123,
        )

        detail = self.db.get_screener_detail(record_id)
        if detail is None:
            self.fail("未返回选股详情")

        self.assertEqual(detail["status"], "failed")
        self.assertEqual(detail["provider"], "openai")
        self.assertEqual(detail["error_message"], "上游模型网关超时")
        self.assertEqual(detail["report_markdown"], "测试报告")

    def test_screener_history_list_exposes_status(self) -> None:
        """History list should surface the saved screener status."""
        payload = {
            "dashboard": None,
            "results": [],
            "report_markdown": None,
            "status": "empty",
            "provider": "fallback",
            "error_message": None,
        }
        self.db.save_screener_result(
            query="空结果条件",
            results_json=json.dumps(payload, ensure_ascii=False),
            result_count=0,
        )

        history = self.db.get_screener_history(limit=10, offset=0)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["status"], "empty")


if __name__ == "__main__":
    unittest.main()
