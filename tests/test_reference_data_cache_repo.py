# -*- coding: utf-8 -*-
"""Tests for the DB-backed reference data cache repository."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta

from src.config import Config
from src.repositories.reference_data_cache_repo import ReferenceDataCacheRepository
from src.storage import DatabaseManager, ReferenceDataCache


class ReferenceDataCacheRepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._temp_dir.name, "test_reference_cache.db")
        os.environ["DATABASE_PATH"] = self._db_path

        Config._instance = None
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()
        self.repo = ReferenceDataCacheRepository(self.db)

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        self._temp_dir.cleanup()

    def test_set_and_get_json_round_trip(self) -> None:
        payload = {"name": "贵州茅台", "former_names": ["茅台股份"]}

        self.repo.set_json("base_info", "600519", payload, ttl_seconds=3600, source="tushare")
        result = self.repo.get_json("base_info", "600519")

        self.assertEqual(result, payload)

    def test_get_json_returns_none_after_expiry_and_cleans_up_row(self) -> None:
        self.repo.set_json("stock_name", "600519", "贵州茅台", ttl_seconds=3600, source="cache")

        with self.db.session_scope() as session:
            row = session.query(ReferenceDataCache).filter_by(namespace="stock_name", cache_key="600519").one()
            row.expires_at = datetime.now() - timedelta(seconds=1)

        result = self.repo.get_json("stock_name", "600519")
        self.assertIsNone(result)

        with self.db.get_session() as session:
            row = session.query(ReferenceDataCache).filter_by(namespace="stock_name", cache_key="600519").one_or_none()
            self.assertIsNone(row)


if __name__ == "__main__":
    unittest.main()
