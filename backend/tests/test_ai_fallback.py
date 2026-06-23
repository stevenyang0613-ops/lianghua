"""
AI 分析 API 回退机制测试

测试覆盖：
- 外部 AI 服务不可用时，所有 AI 端点自动回退到基于规则的分析
- 回退分析的结构正确性和内容完整性
- 前端展示所需的字段齐全（summary, insights, recommendations, confidence）
"""

import pytest
from unittest.mock import patch, MagicMock
import json

from fastapi import HTTPException
from app.api.ai import (
    generate_fallback_analysis,
    _generate_fallback_sentiment,
    _generate_fallback_signal_explain,
    _generate_fallback_strategy_optimize,
    _generate_fallback_risk_assess,
    AnalysisRequest,
    AnalysisType,
)


# ==================== 回退函数单元测试 ====================

class TestFallbackAnalysis:
    """测试 generate_fallback_analysis 回退分析"""

    def test_market_industry_analysis_with_metrics(self):
        """测试行业轮动分析回退 — 完整指标"""
        req = AnalysisRequest(
            type=AnalysisType.market,
            context={
                "industry": "半导体",
                "horizon": "short_term",
                "metrics": {
                    "momentum": 85,
                    "flow": 72,
                    "turnover": 65,
                    "quality": 55,
                    "valuation": 40,
                    "total_score": 68,
                },
            },
            question="测试",
            language="zh",
        )
        result = generate_fallback_analysis(req)

        assert "summary" in result
        assert "半导体" in result["summary"]
        assert "短期" in result["summary"]
        assert result["confidence"] == 64.0

        # insights 应包含动量、资金流向分析
        insights = result["insights"]
        assert any("动量" in i for i in insights)
        assert any("资金" in i for i in insights)

        # recommendations 应包含配置建议
        recommendations = result["recommendations"]
        assert any("标配" in r or "配置" in r for r in recommendations)

        # warnings 应包含换手率风险
        assert result["warnings"] is not None
        assert any("换手率" in w for w in result["warnings"])

    def test_market_industry_analysis_strong_score(self):
        """测试行业轮动分析回退 — 高分"""
        req = AnalysisRequest(
            type=AnalysisType.market,
            context={
                "industry": "银行",
                "horizon": "long_term",
                "metrics": {
                    "momentum": 80,
                    "flow": 85,
                    "turnover": 30,
                    "quality": 75,
                    "valuation": 80,
                    "total_score": 82,
                },
            },
            question="",
            language="zh",
        )
        result = generate_fallback_analysis(req)

        assert "重点配置" in result["recommendations"][0] or "重点配置" in str(result["recommendations"])
        assert result["confidence"] == 79.2
        assert "warnings" not in result or result["warnings"] is None

    def test_market_industry_analysis_weak_score(self):
        """测试行业轮动分析回退 — 低分"""
        req = AnalysisRequest(
            type=AnalysisType.market,
            context={
                "industry": "房地产",
                "horizon": "mid_term",
                "metrics": {
                    "momentum": 20,
                    "flow": 15,
                    "turnover": 85,
                    "quality": 25,
                    "valuation": 20,
                    "total_score": 25,
                },
            },
            question="",
            language="zh",
        )
        result = generate_fallback_analysis(req)

        assert "观望" in result["recommendations"][0] or "降低" in result["recommendations"][0]
        assert result["confidence"] == 30.0

    def test_signal_fallback(self):
        """测试信号分析回退"""
        req = AnalysisRequest(
            type=AnalysisType.signal,
            context={"action": "buy", "code": "000001"},
            question="",
            language="zh",
        )
        result = generate_fallback_analysis(req)
        assert "信号" in result["summary"]
        assert any("000001" in i for i in result["insights"])

    def test_strategy_fallback(self):
        """测试策略分析回退"""
        req = AnalysisRequest(
            type=AnalysisType.strategy,
            context={},
            question="",
            language="zh",
        )
        result = generate_fallback_analysis(req)
        assert "策略" in result["summary"]
        assert any("夏普" in i or "回撤" in i for i in result["insights"])

    def test_risk_fallback(self):
        """测试风险分析回退"""
        req = AnalysisRequest(
            type=AnalysisType.risk,
            context={},
            question="",
            language="zh",
        )
        result = generate_fallback_analysis(req)
        assert "风险" in result["summary"]
        assert any("波动率" in i or "集中度" in i for i in result["insights"])

    def test_default_fallback(self):
        """测试默认回退"""
        req = AnalysisRequest(
            type=AnalysisType.sentiment,
            context={},
            question="测试问题",
            language="zh",
        )
        result = generate_fallback_analysis(req)
        assert result["summary"] == "测试问题"
        assert any("API 密钥" in r for r in result["recommendations"])


class TestSpecializedFallbacks:
    """测试专用回退函数"""

    def test_sentiment_fallback(self):
        """测试情绪分析回退"""
        result = _generate_fallback_sentiment(["000001.SZ", "600519.SH"])
        assert result["overall"] == "neutral"
        assert result["score"] == 0
        assert len(result["factors"]) >= 1
        assert "外部 AI" in result["analysis"]

    def test_signal_explain_fallback(self):
        """测试信号解读回退"""
        signal_data = {
            "id": "sig-1",
            "type": "momentum",
            "action": "buy",
            "code": "000001",
            "name": "平安银行",
            "price": 12.5,
            "reason": "动量突破",
        }
        result = _generate_fallback_signal_explain(signal_data)
        assert "平安银行" in result["explanation"]
        assert "000001" in result["explanation"]
        assert result["signalId"] == "sig-1"
        assert len(result["suggestedActions"]) >= 1

    def test_strategy_optimize_fallback(self):
        """测试策略优化回退"""
        strategy_data = {"name": "双低策略", "params": {"threshold": 130}}
        result = _generate_fallback_strategy_optimize(strategy_data)
        assert "双低策略" in result["analysis"]
        assert len(result["improvements"]) >= 1
        assert len(result["riskWarnings"]) >= 1

    def test_risk_assess_fallback(self):
        """测试风险评估回退"""
        portfolio = {
            "positions": [{"code": "000001"}, {"code": "600519"}],
            "total_value": 1000000,
        }
        result = _generate_fallback_risk_assess(portfolio)
        assert result["riskScore"] == 50
        assert len(result["riskFactors"]) >= 1
        assert len(result["hedgeSuggestions"]) >= 1
        assert "外部 AI" in result["analysis"]


# ==================== 集成测试 ====================

@pytest.mark.integration
def test_ai_analyze_endpoint_fallback(monkeypatch):
    """测试 /ai/analyze 端点在外部 AI 不可用时的回退行为"""
    import tempfile, shutil, os
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    from app.main import app

    tmpdir = tempfile.mkdtemp()
    tmpdb = os.path.join(tmpdir, "test.db")

    from app.engine.signals import SignalEngine
    from app.engine.storage import DataStorage
    engine = SignalEngine()
    storage = DataStorage(db_path=tmpdb)
    engine.set_storage(storage)

    @asynccontextmanager
    async def noop_lifespan(app: FastAPI):
        app.state.signal_engine = engine
        app.state.storage = storage
        app.state.trade_engine = MagicMock()
        app.state.engine = MagicMock()
        app.state.scheduler = MagicMock()
        yield

    app.router.lifespan_context = noop_lifespan

    from app.config import settings
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "")

    auth_headers = {"Authorization": f"Bearer {settings.ws_auth_token}"}

    with TestClient(app, raise_server_exceptions=True) as tc:
        response = tc.post(
            "/api/v1/ai/analyze",
            headers=auth_headers,
            json={
                "type": "market",
                "context": {
                    "industry": "半导体",
                    "horizon": "short_term",
                    "metrics": {
                        "momentum": 85,
                        "flow": 72,
                        "turnover": 65,
                        "quality": 55,
                        "valuation": 40,
                        "total_score": 68,
                    },
                },
                "question": "",
                "language": "zh",
            },
        )

        # 应返回 200（回退成功），而非 503
        assert response.status_code == 200, response.text
        data = response.json()
        assert "summary" in data
        assert "insights" in data
        assert "recommendations" in data
        assert "confidence" in data
        assert "半导体" in data["summary"]

    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.integration
def test_ai_sentiment_endpoint_fallback(monkeypatch):
    """测试 /ai/sentiment 端点在外部 AI 不可用时的回退行为"""
    import tempfile, shutil, os
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    from app.main import app

    tmpdir = tempfile.mkdtemp()
    tmpdb = os.path.join(tmpdir, "test.db")

    from app.engine.signals import SignalEngine
    from app.engine.storage import DataStorage
    engine = SignalEngine()
    storage = DataStorage(db_path=tmpdb)
    engine.set_storage(storage)

    @asynccontextmanager
    async def noop_lifespan(app: FastAPI):
        app.state.signal_engine = engine
        app.state.storage = storage
        app.state.trade_engine = MagicMock()
        app.state.engine = MagicMock()
        app.state.scheduler = MagicMock()
        yield

    app.router.lifespan_context = noop_lifespan

    from app.config import settings
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "")

    auth_headers = {"Authorization": f"Bearer {settings.ws_auth_token}"}

    with TestClient(app, raise_server_exceptions=True) as tc:
        response = tc.post(
            "/api/v1/ai/sentiment",
            headers=auth_headers,
            json={"symbols": ["000001.SZ"], "data": None},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["overall"] == "neutral"
        assert data["score"] == 0

    shutil.rmtree(tmpdir, ignore_errors=True)
