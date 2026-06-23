"""
妙想MX数据 API 路由 — 给前端提供MX金融数据查询接口
"""

import os
import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mx", tags=["mx"])


class MXQueryRequest(BaseModel):
    query: str
    data_type: str = "financial"  # financial or news


# 全局懒加载 MX 适配器
_mx_adapter = None

async def _get_mx():
    global _mx_adapter
    if _mx_adapter is None:
        from app.data.adapters.mx_adapter import MXAdapter
        from app.data.adapters.base import DataSourceConfig
        _mx_adapter = MXAdapter(DataSourceConfig(name="mx"))
        await _mx_adapter.connect()
    return _mx_adapter


@router.post("/query")
async def query_mx_data(req: MXQueryRequest, request: Request):
    """查询妙想金融数据"""
    try:
        api_key = settings.MX_APIKEY or os.environ.get("MX_APIKEY", "")
        if not api_key:
            raise HTTPException(status_code=400, detail="MX_APIKEY 未配置")
        
        mx = await _get_mx()
        result = await mx.query_natural(req.query, req.data_type)
        
        if not result.get("success"):
            raise HTTPException(status_code=502, detail=result.get("error", "查询失败"))
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[MX API] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def mx_status():
    """检查MX服务状态"""
    try:
        mx = await _get_mx()
        return await mx.health_check()
    except Exception as e:
        return {
            "configured": bool(settings.MX_APIKEY or os.environ.get("MX_APIKEY", "")),
            "error": str(e),
        }
