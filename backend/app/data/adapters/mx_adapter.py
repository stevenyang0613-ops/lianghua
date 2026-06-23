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
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Any, Dict, List

import pandas as pd

from .base import DataSourceAdapter, DataSourceConfig, DataQuery, DataType
from .eastmoney_adapter import EastmoneyAdapter

from app.config import settings

logger = logging.getLogger(__name__)

# MX API Key 首次验证时间戳文件（用于有效期管理）
_MX_KEY_VALIDATED_AT_FILE = Path.home() / ".lianghua" / ".mx_key_validated_at"


def _get_key_validated_at() -> Optional[datetime]:
    """读取上次验证时间"""
    try:
        if _MX_KEY_VALIDATED_AT_FILE.exists():
            ts = float(_MX_KEY_VALIDATED_AT_FILE.read_text().strip())
            return datetime.fromtimestamp(ts)
    except Exception:
        pass
    return None


def _set_key_validated_at():
    """记录验证时间"""
    try:
        _MX_KEY_VALIDATED_AT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _MX_KEY_VALIDATED_AT_FILE.write_text(str(datetime.now().timestamp()))
    except Exception:
        pass


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
            client = mod.MXData(api_key=self._api_key)
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
            client = mod.MXSearch(api_key=self._api_key)
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
        """检查MX服务状态 — 包含实际API连通性验证与有效期管理"""
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
        
        # 实际API连通性测试 — 发一个轻量级请求验证Key是否有效
        api_key_valid = False
        api_key_error = None
        if self._api_key and not degraded:
            try:
                mod = self._import_mx_module("mx-data")
                client = mod.MXData(api_key=self._api_key)
                result = client.query("上证指数")
                status = result.get("status")
                if status == 0:
                    api_key_valid = True
                    _set_key_validated_at()  # 记录验证时间
                else:
                    api_key_error = f"API返回状态码 {status}: {result.get('message', '未知错误')}"
            except Exception as e:
                api_key_error = str(e)
                if "401" in str(e).lower() or "unauthorized" in str(e).lower():
                    api_key_error = "API Key 无效或已过期，请重新配置"
        
        # Key 有效期管理：计算距离上次验证的天数
        key_validated_at = _get_key_validated_at()
        days_since_validated = None
        key_expiry_warning = None
        if key_validated_at:
            days_since_validated = (datetime.now() - key_validated_at).days
            # 东方财富 API Key 通常有效期为 30-90 天，超过 60 天给出提醒
            if days_since_validated > 60:
                key_expiry_warning = f"距离上次验证已 {days_since_validated} 天，建议检查 Key 是否仍有效"
            elif days_since_validated > 30:
                key_expiry_warning = f"距离上次验证已 {days_since_validated} 天，Key 可能即将过期"
        
        base.update({
            "configured": bool(self._api_key),
            "api_key_valid": api_key_valid,
            "api_key_error": api_key_error,
            "key_validated_at": key_validated_at.isoformat() if key_validated_at else None,
            "days_since_validated": days_since_validated,
            "key_expiry_warning": key_expiry_warning,
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
        """自然语言查询 MX 金融数据（旧接口，保留兼容）
        
        当 MX API 不可用时，自动回退到 EastmoneyAdapter（直接 HTTP 调用，无需 Key）
        """
        if not self._initialized:
            return {"success": False, "error": "MX adapter not initialized"}
        try:
            if data_type == "news":
                mod = self._import_mx_module("mx-search")
                client = mod.MXSearch(api_key=self._api_key)
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
                client = mod.MXData(api_key=self._api_key)
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
            logger.warning(f"[MX] Query failed, attempting fallback to EastmoneyAdapter: {e}")
            # 降级策略：MX 失败时回退到 EastmoneyAdapter（直接 HTTP 调用，无需 Key）
            try:
                em = EastmoneyAdapter(DataSourceConfig(name="eastmoney"))
                await em.connect()
                
                # 尝试提取代码
                codes = []
                import re
                code_matches = re.findall(r'(\d{6})', query_text)
                if code_matches:
                    codes = code_matches[:20]
                
                if data_type == "news":
                    # 资讯搜索暂无可直接回退的接口，返回提示
                    return {
                        "success": False,
                        "error": "MX API 暂不可用，资讯搜索暂无降级方案。请检查 MX_APIKEY 配置。",
                        "fallback": True,
                        "fallback_reason": str(e),
                    }
                elif codes:
                    # 有代码 → 尝试获取实时行情
                    df = await em.get_realtime_quotes(codes)
                    if not df.empty:
                        rows = df.to_dict("records")
                        return {
                            "success": True,
                            "data": rows,
                            "tables": [{"sheet_name": "实时行情", "rows": rows, "fieldnames": list(df.columns)}],
                            "total_rows": len(rows),
                            "source": "eastmoney_fallback",
                            "fallback": True,
                            "fallback_reason": str(e),
                        }
                    else:
                        # Eastmoney 也返回空 → 标记已尝试降级
                        return {
                            "success": False,
                            "error": f"MX API 不可用（{str(e)[:80]}…），Eastmoney 降级回退也未返回数据。",
                            "fallback": True,
                            "fallback_reason": str(e),
                        }
                
                # 无代码或行情失败 → 回退到宏观/行业数据
                return {
                    "success": False,
                    "error": f"MX API 暂不可用（{str(e)[:80]}…），且当前查询暂无降级方案。请检查 MX_APIKEY 配置。",
                    "fallback": True,
                    "fallback_reason": str(e),
                }
            except Exception as fallback_err:
                logger.error(f"[MX] Fallback to EastmoneyAdapter also failed: {fallback_err}")
                return {
                    "success": False,
                    "error": f"MX API 错误: {str(e)[:80]}…；降级回退也失败: {str(fallback_err)[:80]}…",
                    "fallback": True,
                    "fallback_reason": str(e),
                }

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
