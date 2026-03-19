# -*- coding: utf-8 -*-
"""
===================================
参考数据缓存仓库
===================================

职责：
1. 为低频变化的外部参考数据提供 DB 持久化缓存
2. 基于 namespace/key/TTL 管理 JSON 负载
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

import numpy as np
import pandas as pd
from sqlalchemy import select

from src.storage import DatabaseManager, ReferenceDataCache

logger = logging.getLogger(__name__)


def _normalize_payload(value: Any) -> Any:
    """Convert pandas/numpy/date values into JSON-safe primitives."""
    if isinstance(value, dict):
        return {str(key): _normalize_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_payload(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return value


class ReferenceDataCacheRepository:
    """Read-through cache repository backed by the main SQLite database."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None) -> None:
        self.db = db_manager or DatabaseManager.get_instance()

    def get_json(self, namespace: str, cache_key: str) -> Optional[Any]:
        """Return cached JSON payload when the record exists and is not expired."""
        now = datetime.now()
        with self.db.session_scope() as session:
            row = session.execute(
                select(ReferenceDataCache)
                .where(
                    ReferenceDataCache.namespace == namespace,
                    ReferenceDataCache.cache_key == cache_key,
                )
                .limit(1)
            ).scalar_one_or_none()

            if row is None:
                return None

            if row.expires_at <= now:
                session.delete(row)
                logger.debug("[ReferenceCache] expired: %s/%s", namespace, cache_key)
                return None

            return json.loads(row.payload_json)

    def set_json(
        self,
        namespace: str,
        cache_key: str,
        payload: Any,
        ttl_seconds: int,
        source: Optional[str] = None,
    ) -> None:
        """Insert or update a cached JSON payload with a TTL."""
        now = datetime.now()
        expires_at = now + timedelta(seconds=max(1, ttl_seconds))
        normalized_payload = _normalize_payload(payload)
        payload_json = json.dumps(normalized_payload, ensure_ascii=False, separators=(",", ":"))

        with self.db.session_scope() as session:
            row = session.execute(
                select(ReferenceDataCache)
                .where(
                    ReferenceDataCache.namespace == namespace,
                    ReferenceDataCache.cache_key == cache_key,
                )
                .limit(1)
            ).scalar_one_or_none()

            if row is None:
                row = ReferenceDataCache(
                    namespace=namespace,
                    cache_key=cache_key,
                    payload_json=payload_json,
                    source=source,
                    fetched_at=now,
                    expires_at=expires_at,
                )
                session.add(row)
            else:
                row.payload_json = payload_json
                row.source = source
                row.fetched_at = now
                row.expires_at = expires_at

    def purge_expired(self, namespace: Optional[str] = None) -> int:
        """Delete expired rows and return the number of removed records."""
        now = datetime.now()
        removed = 0
        with self.db.session_scope() as session:
            stmt = select(ReferenceDataCache).where(ReferenceDataCache.expires_at <= now)
            if namespace:
                stmt = stmt.where(ReferenceDataCache.namespace == namespace)
            rows = session.execute(stmt).scalars().all()
            for row in rows:
                session.delete(row)
                removed += 1
        return removed
