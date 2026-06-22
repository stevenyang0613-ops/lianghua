"""
日志 API
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from enum import Enum

router = APIRouter()


@router.get("/")
async def list_logs():
    """日志列表索引 — 返回已上报的日志条目数量(无 query 参数时使用)"""
    return {"count": len(logs_db), "hint": "use /query for filtered listing"}


class LogLevel(str, Enum):
    debug = "debug"
    info = "info"
    warn = "warn"
    error = "error"
    fatal = "fatal"

class LogEntry(BaseModel):
    id: str
    level: LogLevel
    category: str
    message: str
    timestamp: datetime
    userId: Optional[str] = None
    sessionId: str
    context: Optional[dict] = None

class LogReport(BaseModel):
    logs: List[LogEntry]
    metadata: Optional[dict] = None

# 临时存储
logs_db = []

@router.post("/report")
async def report_logs(report: LogReport):
    """上报日志"""
    for log in report.logs:
        logs_db.append(log)
    return {"received": len(report.logs)}

@router.get("/query", response_model=List[LogEntry])
async def query_logs(
    level: Optional[LogLevel] = None,
    category: Optional[str] = None,
    startTime: Optional[datetime] = None,
    endTime: Optional[datetime] = None,
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=200)
):
    """查询日志"""
    results = logs_db

    if level:
        results = [l for l in results if l.level == level]
    if category:
        results = [l for l in results if l.category == category]
    if startTime:
        results = [l for l in results if l.timestamp >= startTime]
    if endTime:
        results = [l for l in results if l.timestamp <= endTime]

    start = (page - 1) * pageSize
    return results[start:start + pageSize]

@router.get("/stats")
async def get_log_stats(startTime: Optional[datetime] = None, endTime: Optional[datetime] = None):
    """获取日志统计"""
    from collections import Counter

    results = logs_db
    if startTime:
        results = [l for l in results if l.timestamp >= startTime]
    if endTime:
        results = [l for l in results if l.timestamp <= endTime]

    level_counts = Counter(l.level for l in results)
    category_counts = Counter(l.category for l in results)

    return {
        "total": len(results),
        "byLevel": dict(level_counts),
        "byCategory": dict(category_counts),
    }


@router.get("/export")
async def export_logs(
    format: str = "json",
    startTime: Optional[datetime] = None,
    endTime: Optional[datetime] = None,
    level: Optional[str] = None,
):
    """导出日志（兼容端点）"""
    results = logs_db
    if startTime:
        results = [l for l in results if l.timestamp >= startTime]
    if endTime:
        results = [l for l in results if l.timestamp <= endTime]
    if level:
        results = [l for l in results if l.level == level]

    if format == "csv":
        import csv, io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "level", "category", "message", "timestamp", "userId", "sessionId"])
        for l in results:
            writer.writerow([l.id, l.level, l.category, l.message, l.timestamp.isoformat(), l.userId, l.sessionId])
        return {"format": "csv", "data": output.getvalue(), "count": len(results)}
    return {"format": "json", "data": [l.model_dump() for l in results], "count": len(results)}
