"""
东方财富妙想(MX)金融数据适配器 — 使用东方财富MX官方API

本适配器作为独立数据源运行，通过 MX API Key 认证，
提供股票/指数/基金行情、财务数据、资讯搜索等能力。

API Key 从环境变量 MX_APIKEY 读取。
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Optional, Any

logger = logging.getLogger(__name__)


class MXAdapter:
    """妙想金融数据适配器"""
    
    def __init__(self):
        self._api_key = os.environ.get("MX_APIKEY", "")
        self._initialized = False
    
    @property
    def name(self) -> str:
        return "mx"
    
    async def connect(self) -> bool:
        if not self._api_key:
            logger.warning("[MX] MX_APIKEY not set, MX adapter disabled")
            return False
        os.environ["MX_APIKEY"] = self._api_key
        self._initialized = True
        logger.info(f"[MX] Connected (key: {self._api_key[:8]}...)")
        return True
    
    async def disconnect(self):
        self._initialized = False
    
    def _import_mx_module(self, name: str):
        """动态导入 MX skill 模块"""
        skill_dirs = [
            Path.home() / ".codex" / "skills",
            Path.home() / "skills",
        ]
        for sd in skill_dirs:
            skill_path = sd / name / f"{name.replace('-', '_')}.py"
            if skill_path.exists():
                import importlib.util
                spec = importlib.util.spec_from_file_location(
                    name.replace('-', '_'), str(skill_path))
                mod = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = mod
                spec.loader.exec_module(mod)
                return mod
        raise ImportError(f"MX skill '{name}' not found")
    
    async def query(self, query_text: str, data_type: str = "financial") -> dict:
        """查询MX金融数据"""
        if not self._initialized:
            return {"success": False, "error": "MX adapter not initialized"}
        try:
            if data_type == "news":
                mod = self._import_mx_module("mx-search")
                client = mod.MXSearch()
                result = client.search(query_text)
                items = []
                for item in result.get("data", {}).get("items", []):
                    items.append({
                        "title": item.get("title", ""),
                        "content": item.get("content", ""),
                        "date": item.get("date", ""),
                        "source": item.get("source", ""),
                        "type": item.get("type", ""),
                    })
                return {"success": True, "data": items, "total": len(items), "source": "mx_search"}
            else:
                mod = self._import_mx_module("mx-data")
                client = mod.MXData()
                result = client.query(query_text)
                tables, _, total_rows, err = client.parse_result(result)
                if err:
                    return {"success": False, "error": err}
                rows = []
                for table in tables:
                    rows.extend(table["rows"])
                return {
                    "success": True,
                    "data": rows,
                    "tables": tables,
                    "total_rows": total_rows,
                    "source": "mx_data",
                }
        except Exception as e:
            logger.error(f"[MX] Query failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def status(self) -> dict:
        """检查MX服务状态"""
        return {
            "configured": bool(self._api_key),
            "api_key_prefix": self._api_key[:8] + "..." if self._api_key else "",
            "mx_data_installed": (Path.home() / ".codex" / "skills" / "mx-data" / "SKILL.md").exists(),
            "mx_search_installed": (Path.home() / ".codex" / "skills" / "mx-search" / "SKILL.md").exists(),
        }
