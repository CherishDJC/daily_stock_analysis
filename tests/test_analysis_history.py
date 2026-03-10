# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - 分析历史存储单元测试
===================================

职责：
1. 验证分析历史保存逻辑
2. 验证上下文快照保存开关
"""

import os
import tempfile
import unittest
import json

from src.config import Config
from src.storage import DatabaseManager, AnalysisHistory
from src.analyzer import AnalysisResult
from src.services.history_service import HistoryService


class AnalysisHistoryTestCase(unittest.TestCase):
    """分析历史存储测试"""

    def setUp(self) -> None:
        """为每个用例初始化独立数据库"""
        self._temp_dir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._temp_dir.name, "test_analysis_history.db")
        os.environ["DATABASE_PATH"] = self._db_path

        Config._instance = None
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()

    def tearDown(self) -> None:
        """清理资源"""
        DatabaseManager.reset_instance()
        self._temp_dir.cleanup()

    def _build_result(self) -> AnalysisResult:
        """构造分析结果"""
        return AnalysisResult(
            code="600519",
            name="贵州茅台",
            sentiment_score=78,
            trend_prediction="看多",
            operation_advice="持有",
            analysis_summary="基本面稳健，短期震荡",
        )

    def test_save_analysis_history_with_snapshot(self) -> None:
        """保存历史记录并写入上下文快照"""
        result = self._build_result()
        result.dashboard = {
            "battle_plan": {
                "sniper_points": {
                    "ideal_buy": "理想买入点：125.5元",
                    "secondary_buy": "120",
                    "stop_loss": "止损位：110元",
                    "take_profit": "目标位：150.0元",
                }
            }
        }
        context_snapshot = {"enhanced_context": {"code": "600519"}}

        saved = self.db.save_analysis_history(
            result=result,
            query_id="query_001",
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot=context_snapshot,
            save_snapshot=True
        )

        self.assertEqual(saved, 1)

        history = self.db.get_analysis_history(code="600519", days=7, limit=10)
        self.assertEqual(len(history), 1)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertEqual(row.query_id, "query_001")
            self.assertIsNotNone(row.context_snapshot)
            self.assertEqual(row.ideal_buy, 125.5)
            self.assertEqual(row.secondary_buy, 120.0)
            self.assertEqual(row.stop_loss, 110.0)
            self.assertEqual(row.take_profit, 150.0)

    def test_save_analysis_history_without_snapshot(self) -> None:
        """关闭快照保存时不写入 context_snapshot"""
        result = self._build_result()

        saved = self.db.save_analysis_history(
            result=result,
            query_id="query_002",
            report_type="simple",
            news_content="新闻摘要",
            context_snapshot={"foo": "bar"},
            save_snapshot=False
        )

        self.assertEqual(saved, 1)

        with self.db.get_session() as session:
            row = session.query(AnalysisHistory).first()
            if row is None:
                self.fail("未找到保存的历史记录")
            self.assertIsNone(row.context_snapshot)

    def test_history_detail_falls_back_to_provider_error_summary(self) -> None:
        """When analysis_summary is empty, detail API should expose provider error clearly."""
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="query_003",
                    code="600519",
                    name="贵州茅台",
                    report_type="full",
                    sentiment_score=50,
                    operation_advice="观望",
                    trend_prediction="未知",
                    analysis_summary="",
                    raw_result=json.dumps(
                        {
                            "code": "600519",
                            "operation_advice": "观望",
                            "trend_prediction": "未知",
                            "dashboard": {
                                "code": "INVALID_API_KEY",
                                "message": "Invalid API key",
                            },
                            "analysis_summary": "",
                        },
                        ensure_ascii=False,
                    ),
                    context_snapshot=json.dumps(
                        {
                            "realtime_quote": {
                                "price": 1397.0,
                            }
                        },
                        ensure_ascii=False,
                    ),
                )
            )
            session.commit()

        detail = HistoryService(self.db).resolve_and_get_detail("1")
        if detail is None:
            self.fail("未返回历史详情")

        self.assertEqual(detail["analysis_summary"], "AI 分析失败：INVALID_API_KEY: Invalid API key")

    def test_history_detail_builds_summary_from_operation_and_context(self) -> None:
        """When no AI summary exists, detail API should still provide a readable fallback."""
        with self.db.get_session() as session:
            session.add(
                AnalysisHistory(
                    query_id="query_004",
                    code="600519",
                    name="贵州茅台",
                    report_type="full",
                    sentiment_score=50,
                    operation_advice="观望",
                    trend_prediction="未知",
                    analysis_summary="",
                    raw_result=json.dumps(
                        {
                            "code": "600519",
                            "operation_advice": "观望",
                            "trend_prediction": "未知",
                            "dashboard": {},
                            "analysis_summary": "",
                        },
                        ensure_ascii=False,
                    ),
                    context_snapshot=json.dumps(
                        {
                            "realtime_quote": {
                                "price": 1397.0,
                            }
                        },
                        ensure_ascii=False,
                    ),
                )
            )
            session.commit()

        detail = HistoryService(self.db).resolve_and_get_detail("1")
        if detail is None:
            self.fail("未返回历史详情")

        self.assertEqual(detail["analysis_summary"], "操作建议：观望；趋势判断：未知；快照价格：1397.00 元")

    def test_history_news_hides_garbled_snippet(self) -> None:
        """Legacy mojibake snippets should be sanitized on read."""
        self.db.save_news_intel(
            code="600519",
            name="贵州茅台",
            dimension="latest_news",
            query="贵州茅台 最新新闻",
            response=type(
                "FakeResponse",
                (),
                {
                    "provider": "Tavily",
                    "results": [
                        type(
                            "FakeItem",
                            (),
                            {
                                "title": "贵州茅台1400.02(-0.14%)_个股资讯- 新浪财经",
                                "snippet": "Ӫĸ︴ר⣺в 2026-03-04 07:15 20һ幫˾ֻع๫ ²ӻعܶ",
                                "url": "https://vip.stock.finance.sina.com.cn/example",
                                "source": "finance.sina.com.cn",
                                "published_date": None,
                            },
                        )()
                    ],
                },
            )(),
            query_context={"query_id": "query_news_001"},
        )

        items = HistoryService(self.db).get_news_intel("query_news_001", limit=5)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "贵州茅台1400.02(-0.14%)_个股资讯- 新浪财经")
        self.assertEqual(items[0]["snippet"], "")


if __name__ == "__main__":
    unittest.main()
