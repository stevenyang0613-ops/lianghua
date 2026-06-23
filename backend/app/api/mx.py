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
        if not settings.MX_APIKEY:
            raise HTTPException(status_code=400, detail="MX_APIKEY 未配置，请在 .env 文件中设置 LH_MX_APIKEY")
        
        mx = await _get_mx()
        result = await mx.query_natural(req.query, req.data_type)
        
        if not result.get("success"):
            error_msg = result.get("error", "查询失败")
            # 将底层错误映射为友好提示
            if "401" in error_msg or "unauthorized" in error_msg.lower():
                error_msg = "MX API Key 无效或已过期，请检查 .env 中的 LH_MX_APIKEY 配置"
            elif "403" in error_msg or "forbidden" in error_msg.lower():
                error_msg = "当前 API Key 无权限访问此接口，请升级权限或联系东方财富"
            elif "429" in error_msg or "rate limit" in error_msg.lower():
                error_msg = "请求过于频繁，请稍后再试"
            elif "timeout" in error_msg.lower() or "connection" in error_msg.lower():
                error_msg = "连接超时，请检查网络或稍后重试"
            raise HTTPException(status_code=502, detail=error_msg)
        
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
        hc = await mx.health_check()
        # 映射为前端友好的状态显示
        status_display = "正常" if hc.get("api_key_valid") else (
            "Key 无效" if hc.get("configured") else "未配置"
        )
        if hc.get("degraded_mode"):
            status_display = "降级模式"
        hc["status_display"] = status_display
        return hc
    except Exception as e:
        return {
            "configured": bool(settings.MX_APIKEY),
            "api_key_valid": False,
            "api_key_error": str(e),
            "status_display": "异常",
            "error": str(e),
        }
