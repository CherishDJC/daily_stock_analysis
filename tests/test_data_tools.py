# -*- coding: utf-8 -*-
"""Tests for agent data tool routing."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from src.agent.tools.data_tools import _handle_get_stock_info


class DataToolsStockInfoTestCase(unittest.TestCase):
    @patch("src.agent.tools.data_tools._get_fetcher_manager")
    def test_get_stock_info_uses_manager_base_info_and_board_membership(self, manager_factory) -> None:
        manager = MagicMock()
        manager.get_base_info.return_value = {
            "code": "600519",
            "name": "贵州茅台",
            "industry": "白酒",
            "source": "tushare",
        }
        manager.get_belong_board.return_value = pd.DataFrame(
            [
                {"板块名称": "白酒概念", "板块代码": "BK001", "涨跌幅": 1.23},
                {"板块名称": "沪深300", "板块代码": "BK300", "涨跌幅": 0.45},
            ]
        )
        manager_factory.return_value = manager

        result = _handle_get_stock_info("600519")

        self.assertEqual(result["name"], "贵州茅台")
        self.assertEqual(result["industry"], "白酒")
        self.assertEqual(result["source"], "tushare")
        self.assertEqual(len(result["belong_boards"]), 2)
        manager.get_base_info.assert_called_once_with("600519")
        manager.get_belong_board.assert_called_once_with("600519")


if __name__ == "__main__":
    unittest.main()
