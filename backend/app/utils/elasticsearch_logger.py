"""
Elasticsearch 日志收集
"""

from elasticsearch import AsyncElasticsearch
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import json
import os

# Elasticsearch 配置
ELASTICSEARCH_URL = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")


class ElasticsearchLogger:
    """Elasticsearch 日志收集器"""

    def __init__(self):
        self.client: Optional[AsyncElasticsearch] = None
        self.index_prefix = "lianghua"

    async def connect(self):
        """连接 Elasticsearch"""
        if self.client is None:
            self.client = AsyncElasticsearch([ELASTICSEARCH_URL])

    async def disconnect(self):
        """断开连接"""
        if self.client:
            await self.client.close()
            self.client = None

    async def create_index(self, index_name: str):
        """创建索引"""
        if not self.client:
            await self.connect()

        index = f"{self.index_prefix}-{index_name}"

        # 索引映射
        mapping = {
            "mappings": {
                "properties": {
                    "@timestamp": {"type": "date"},
                    "level": {"type": "keyword"},
                    "category": {"type": "keyword"},
                    "message": {"type": "text"},
                    "userId": {"type": "keyword"},
                    "sessionId": {"type": "keyword"},
                    "context": {"type": "object", "enabled": True},
                }
            }
        }

        if not await self.client.indices.exists(index=index):
            await self.client.indices.create(index=index, body=mapping)

    async def log(
        self,
        level: str,
        category: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        """记录日志"""
        if not self.client:
            await self.connect()

        doc = {
            "@timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "category": category,
            "message": message,
            "userId": user_id,
            "sessionId": session_id,
            "context": context or {},
        }

        # 按日期分索引
        index = f"{self.index_prefix}-logs-{datetime.now(timezone.utc).strftime('%Y.%m.%d')}"

        await self.client.index(index=index, document=doc)

    async def search(
        self,
        query: str,
        level: Optional[str] = None,
        category: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        size: int = 100,
    ) -> List[Dict[str, Any]]:
        """搜索日志"""
        if not self.client:
            await self.connect()

        # 构建查询
        must = []

        if query:
            must.append({"match": {"message": query}})

        if level:
            must.append({"term": {"level": level}})

        if category:
            must.append({"term": {"category": category}})

        if start_time or end_time:
            range_query = {"range": {"@timestamp": {}}}
            if start_time:
                range_query["range"]["@timestamp"]["gte"] = start_time.isoformat()
            if end_time:
                range_query["range"]["@timestamp"]["lte"] = end_time.isoformat()
            must.append(range_query)

        body = {
            "query": {"bool": {"must": must}} if must else {"match_all": {}},
            "sort": [{"@timestamp": {"order": "desc"}}],
            "size": size,
        }

        # 搜索所有日志索引
        result = await self.client.search(
            index=f"{self.index_prefix}-logs-*",
            body=body,
        )

        return [hit["_source"] for hit in result["hits"]["hits"]]

    async def get_stats(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """获取日志统计"""
        if not self.client:
            await self.connect()

        range_query = {}
        if start_time or end_time:
            range_query["@timestamp"] = {}
            if start_time:
                range_query["@timestamp"]["gte"] = start_time.isoformat()
            if end_time:
                range_query["@timestamp"]["lte"] = end_time.isoformat()

        body = {
            "size": 0,
            "aggs": {
                "by_level": {"terms": {"field": "level"}},
                "by_category": {"terms": {"field": "category"}},
                "over_time": {
                    "date_histogram": {
                        "field": "@timestamp",
                        "calendar_interval": "hour",
                    }
                },
            },
        }

        if range_query:
            body["query"] = {"range": range_query}

        result = await self.client.search(
            index=f"{self.index_prefix}-logs-*",
            body=body,
        )

        return {
            "total": result["hits"]["total"]["value"],
            "byLevel": {
                bucket["key"]: bucket["doc_count"]
                for bucket in result["aggregations"]["by_level"]["buckets"]
            },
            "byCategory": {
                bucket["key"]: bucket["doc_count"]
                for bucket in result["aggregations"]["by_category"]["buckets"]
            },
            "overTime": [
                {"time": bucket["key_as_string"], "count": bucket["doc_count"]}
                for bucket in result["aggregations"]["over_time"]["buckets"]
            ],
        }

    async def delete_old_logs(self, days: int = 30):
        """删除旧日志"""
        if not self.client:
            await self.connect()

        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        await self.client.delete_by_query(
            index=f"{self.index_prefix}-logs-*",
            body={
                "query": {
                    "range": {
                        "@timestamp": {"lt": cutoff.isoformat()}
                    }
                }
            },
        )


# 导出单例
es_logger = ElasticsearchLogger()


class PerformanceTracker:
    """性能追踪器"""

    def __init__(self):
        self.client = None

    async def track(
        self,
        operation: str,
        duration_ms: float,
        success: bool,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """记录性能指标"""
        if not es_logger.client:
            await es_logger.connect()

        doc = {
            "@timestamp": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "duration_ms": duration_ms,
            "success": success,
            "metadata": metadata or {},
        }

        index = f"{es_logger.index_prefix}-performance-{datetime.now(timezone.utc).strftime('%Y.%m.%d')}"
        await es_logger.client.index(index=index, document=doc)

    async def get_slow_operations(
        self,
        threshold_ms: float = 1000,
        size: int = 100,
    ) -> List[Dict[str, Any]]:
        """获取慢操作"""
        if not es_logger.client:
            await es_logger.connect()

        result = await es_logger.client.search(
            index=f"{es_logger.index_prefix}-performance-*",
            body={
                "query": {
                    "range": {"duration_ms": {"gte": threshold_ms}}
                },
                "sort": [{"duration_ms": {"order": "desc"}}],
                "size": size,
            },
        )

        return [hit["_source"] for hit in result["hits"]["hits"]]


# 导出单例
performance_tracker = PerformanceTracker()
