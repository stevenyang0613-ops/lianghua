"""
东方财富妙想(MX)金融数据适配器 — 使用东方财富MX官方API

本适配器作为独立数据源运行，通过 MX API Key 认证，
提供股票/指数/基金行情、财务数据、资讯搜索等能力。

API Key 从环境变量 MX_APIKEY 读取。

继承 DataSourceAdapter 基类，注册到 DataSourceManager 统一调度。
"""

import os
import sys
import json
import logging
from datetime import date
from pathlib import Path
from typing import Optional, Any, Dict, List

import pandas as pd

from .base import DataSourceAdapter, DataSourceConfig, DataQuery, DataType

from app.config import settings

logger = logging.getLogger(__name__)


class MXAdapter(DataSourceAdapter):
    """妙想金融数据适配器"""

    def __init__(self, config: DataSourceConfig = None):
        # 兼容无参构造：外部代码可能不传 config
        if config is None:
            config = DataSourceConfig(name="mx")
        super().__init__(config)
        self._api_key = settings.MX_APIKEY or config.extra.get("api_key", "")
        self._initialized = False

    async def connect(self) -> bool:
        if not self._api_key:
            logger.warning("[MX] MX_APIKEY not set, MX adapter running in DEGRADED mode (proxy to other sources)")
            self._initialized = True  # 允许在降级模式下初始化
            self._connected = True
            self._degraded_mode = True
            return True
        self._initialized = True
        self._connected = True
        self._degraded_mode = False
        logger.info(f"[MX] Connected (key masked)")
        return True

    async def disconnect(self) -> None:
        self._initialized = False
        self._connected = False

    # ------------------------------------------------------------------
    # DataSourceAdapter 抽象方法实现
    # ------------------------------------------------------------------

    async def query(self, query: DataQuery) -> pd.DataFrame:
        """通过 MX 自然语言查询返回 DataFrame"""
        if not self._initialized:
            return pd.DataFrame()
        try:
            query_text = query.filters.get("query_text", "") if query.filters else ""
            if not query_text and query.codes:
                query_text = ",".join(query.codes)

            mod = self._import_mx_module("mx-data")
            client = mod.MXData()
            result = client.query(query_text)
            tables, _, total_rows, err = client.parse_result(result)
            if err:
                logger.error(f"[MX] query parse error: {err}")
                return pd.DataFrame()
            rows = []
            for table in tables:
                rows.extend(table.get("rows", []))
            if not rows:
                return pd.DataFrame()
            return pd.DataFrame(rows)
        except Exception as e:
            self._handle_error(e)
            return pd.DataFrame()

    async def get_realtime_quotes(self, codes: List[str]) -> pd.DataFrame:
        """MX 不直接支持批量实时行情，走自然语言查询兜底"""
        if not codes:
            return pd.DataFrame()
        q = DataQuery(
            data_type=DataType.QUOTE,
            codes=codes,
            filters={"query_text": "实时行情 " + " ".join(codes[:20])},
        )
        return await self.query(q)

    async def get_convertible_bonds(self, date: Optional[date] = None) -> pd.DataFrame:
        """MX 自然语言查询可转债列表"""
        q = DataQuery(
            data_type=DataType.CONVERTIBLE,
            filters={"query_text": "可转债列表"},
        )
        return await self.query(q)

    async def get_announcements(
        self,
        codes: Optional[List[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        keywords: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """MX 资讯搜索"""
        if not self._initialized:
            return pd.DataFrame()
        try:
            query_text = " ".join(keywords or []) or "公告"
            if codes:
                query_text = " ".join(codes[:10]) + " " + query_text
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
            return pd.DataFrame(items) if items else pd.DataFrame()
        except Exception as e:
            self._handle_error(e)
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # 健康检查（覆盖基类，增加 MX 特有字段）
    # ------------------------------------------------------------------

    async def health_check(self) -> Dict[str, Any]:
        """检查MX服务状态 — 同时检查所有可能的skill安装路径"""
        base = await super().health_check()
        degraded = getattr(self, '_degraded_mode', False)
        
        # 检查所有路径下的skill安装状态
        skill_install_status = {}
        for name in ['mx-data', 'mx-search', 'mx-xuangu']:
            found_anywhere = False
            for base_path in [
                Path.home() / ".agents" / "skills",
                Path.home() / ".codex" / "skills",
                Path.home() / "skills",
            ]:
                skill_py = base_path / name / f"{name.replace('-', '_')}.py"
                skill_md = base_path / name / "SKILL.md"
                if skill_py.exists() and skill_md.exists():
                    found_anywhere = True
                    break
            skill_install_status[name] = found_anywhere
        
        base.update({
            "configured": bool(self._api_key),
            "degraded_mode": degraded,
            "api_key_prefix": "***" if self._api_key else "",
            "skills_installed": skill_install_status,
            "all_skills_ready": all(skill_install_status.values()),
        })
        return base

    # ------------------------------------------------------------------
    # 兼容旧接口：自然语言查询（保留，供非 DataSourceManager 调用方使用）
    # ------------------------------------------------------------------

    async def query_natural(self, query_text: str, data_type: str = "financial") -> dict:
        """自然语言查询 MX 金融数据（旧接口，保留兼容）"""
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
                    rows.extend(table.get("rows", []))
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

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _import_mx_module(self, name: str):
        """动态导入 MX skill 模块
        
        搜索路径优先级（从前到后）:
        1. ~/.agents/skills  - Kimi Work 新版 skill 目录
        2. ~/.codex/skills   - 旧版 skill 目录
        3. ~/skills          - 用户自定义目录
        """
        skill_dirs = [
            Path.home() / ".agents" / "skills",   # 新版 Agent 目录（优先）
            Path.home() / ".codex" / "skills",     # 旧版 Codex 目录
            Path.home() / "skills",                  # 用户自定义目录
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
        raise ImportError(f"MX skill '{name}' not found in any of: {[str(d) for d in skill_dirs]}")
