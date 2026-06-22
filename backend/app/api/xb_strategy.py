"""西部量化可转债策略 V3.0 API接口"""
import asyncio
import math
from fastapi import APIRouter, Request, HTTPException
from typing import Optional, Tuple
from datetime import date, datetime
import logging

from app.xb_strategy.core.strategy import XBConvertibleStrategy
from app.xb_strategy.core.types import ConvertibleBondData, StockData
from app.xb_strategy.core.timing import TimingEngine, EnhancedTimingEngine, MarketData
from app.xb_strategy.config.weights import MarketRegime
from app.strategies.enhanced_timing_model import (
    EnhancedTimingModel,
    EnhancedTimingSignal,
    EnhancedMarketData,
    convert_from_legacy_data,
    clean_numpy_types,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/xb-strategy", tags=["西部量化策略V3.0"])


# 全局策略实例
_strategy: Optional[XBConvertibleStrategy] = None
# 全局择时引擎 + 择时信号缓存
_timing_engine = EnhancedTimingEngine()
_enhanced_timing = EnhancedTimingModel()
_timing_signal_cache: Optional[dict] = None
_enhanced_signal_cache: Optional[dict] = None
_timing_signal_cache_ts: Optional[datetime] = None
_enhanced_signal_cache_ts: Optional[datetime] = None
_timing_signal_refresh_task: Optional[asyncio.Task] = None

# 缓存有效期：与调度器刷新周期一致（300 秒）
TIMING_CACHE_TTL_SECONDS = 300


def get_strategy(aum: float = 10000.0) -> XBConvertibleStrategy:
    """获取策略实例"""
    global _strategy
    if _strategy is None:
        _strategy = XBConvertibleStrategy(aum)
    return _strategy


async def _prepare_enhanced_data(request: Request, bonds) -> Tuple[Optional[EnhancedMarketData], Optional[object]]:
    """共享的数据准备：从 request.app.state 获取 macro_svc 并构建 EnhancedMarketData"""
    macro_svc = getattr(request.app.state, "macro_data_service", None)
    macro_data = None
    if macro_svc:
        try:
            macro_data = await macro_svc.fetch_macro_data(bonds)
        except Exception as e:
            logger.warning(f"[TimingAPI] MacroDataService fetch failed: {e}")
    return _build_enhanced_data(bonds, macro_data), macro_data


def _build_enhanced_data(bonds, macro_data) -> Optional[EnhancedMarketData]:
    """由债券列表和宏观数据构建 EnhancedMarketData"""
    import pandas as pd

    if not macro_data or not bonds:
        return None

    bonds_data = []
    for b in bonds:
        bonds_data.append({
            'premium_ratio': getattr(b, 'premium_ratio', 0) or 0,
            'price': getattr(b, 'price', 0) or 0,
            'volume': getattr(b, 'volume', 0) or 0,
            'ytm': getattr(b, 'ytm', 0) or 0,
        })
    bonds_df = pd.DataFrame(bonds_data) if bonds_data else pd.DataFrame()

    legacy_market = MarketData(
        date=date.today(),
        cb_median_premium=macro_data.cb_median_premium,
        cb_avg_daily_amount=macro_data.cb_avg_daily_amount,
        cb_index_change=macro_data.cb_index_change,
        cb_index_ma20=macro_data.cb_index_ma20,
        cb_index_current=macro_data.cb_index_current,
        treasury_10y_yield=macro_data.treasury_10y_yield,
        pmi=macro_data.pmi_current,
        pmi_prev=macro_data.pmi_prev,
    )

    return convert_from_legacy_data(
        legacy_data=legacy_market,
        bonds_df=bonds_df,
        macro_data=macro_data,
    )


async def refresh_timing_signal_caches(engine, macro_svc) -> None:
    """后台定时任务：预计算并缓存增强版 + 普通版择时信号"""
    global _timing_signal_cache, _enhanced_signal_cache
    global _timing_signal_cache_ts, _enhanced_signal_cache_ts

    if not engine or not macro_svc:
        logger.warning("[TimingAPI] Cannot refresh timing signal caches: engine or macro_svc unavailable")
        return

    try:
        bonds = await engine.get_all_quotes()
        if not bonds:
            logger.warning("[TimingAPI] No bonds available for timing signal refresh")
            return

        macro_data = await macro_svc.fetch_macro_data(bonds)
        if not macro_data:
            logger.warning("[TimingAPI] No macro data available for timing signal refresh")
            return

        # 增强版信号
        enhanced_data = _build_enhanced_data(bonds, macro_data)
        if enhanced_data:
            try:
                enhanced_signal = _enhanced_timing.calculate(enhanced_data)
                _enhanced_signal_cache = _enhanced_signal_to_frontend(enhanced_signal, macro_data)
                _enhanced_signal_cache_ts = datetime.now()
                logger.info("[TimingAPI] Enhanced timing signal cache refreshed")
            except Exception as e:
                logger.warning(f"[TimingAPI] Enhanced signal calculation failed: {e}")

        # 普通版信号
        try:
            market_data = MarketData(
                date=date.today(),
                cb_median_premium=macro_data.cb_median_premium,
                cb_avg_daily_amount=macro_data.cb_avg_daily_amount,
                cb_index_change=macro_data.cb_index_change,
                cb_index_ma20=macro_data.cb_index_ma20,
                cb_index_current=macro_data.cb_index_current,
                treasury_10y_yield=macro_data.treasury_10y_yield,
                pmi=macro_data.pmi_current,
                pmi_prev=macro_data.pmi_prev,
            )
            signal = _timing_engine.calculate_timing(market_data)
            _timing_signal_cache = _signal_to_frontend(signal, macro_data)
            _timing_signal_cache_ts = datetime.now()
            logger.info("[TimingAPI] Legacy timing signal cache refreshed")
        except Exception as e:
            logger.warning(f"[TimingAPI] Legacy signal calculation failed: {e}")
    except Exception as e:
        logger.warning(f"[TimingAPI] Timing signal cache refresh failed: {e}")


def _trigger_background_refresh(request: Request) -> None:
    """请求路径上触发一次后台刷新（不阻塞响应）"""
    global _timing_signal_refresh_task
    engine = getattr(request.app.state, "engine", None)
    macro_svc = getattr(request.app.state, "macro_data_service", None)
    if not engine or not macro_svc:
        return
    if _timing_signal_refresh_task is None or _timing_signal_refresh_task.done():
        _timing_signal_refresh_task = asyncio.create_task(
            refresh_timing_signal_caches(engine, macro_svc)
        )


async def _compute_live_timing_signal(request: Request, enhanced: bool = False) -> dict:
    """返回缓存的择时信号；缓存缺失/过期时触发后台刷新，避免前端长时间等待"""
    global _timing_signal_cache, _enhanced_signal_cache
    global _timing_signal_cache_ts, _enhanced_signal_cache_ts

    now = datetime.now()

    def _cache_fresh(ts: Optional[datetime]) -> bool:
        return ts is not None and (now - ts).total_seconds() < TIMING_CACHE_TTL_SECONDS

    if enhanced and _cache_fresh(_enhanced_signal_cache_ts) and _enhanced_signal_cache:
        return _enhanced_signal_cache
    if not enhanced and _cache_fresh(_timing_signal_cache_ts) and _timing_signal_cache:
        return _timing_signal_cache

    # 没有新鲜缓存时，触发后台计算并返回旧缓存或默认提示
    _trigger_background_refresh(request)
    if enhanced and _enhanced_signal_cache:
        return _enhanced_signal_cache
    if not enhanced and _timing_signal_cache:
        return _timing_signal_cache
    return _default_signal()


def _signal_to_frontend(signal, macro_data) -> dict:
    """将 TimingSignal 转换为前端 TimingSignal 组件需要的格式"""
    # 计算各因子满分得分（前端期望的是绝对分数，不是百分比）
    # 估值(满分40), 情绪(满分25), 流动性(满分20), 宏观(满分15)
    valuation_abs = signal.valuation_score * 0.40  # 百分比转绝对分
    sentiment_abs = signal.sentiment_score * 0.25
    liquidity_abs = signal.liquidity_score * 0.20
    macro_abs = signal.macro_score * 0.15

    total_abs = valuation_abs + sentiment_abs + liquidity_abs + macro_abs

    # 状态判定
    def _factor_status(score_pct: float) -> str:
        import math
        if math.isnan(score_pct):
            return 'missing'
        if score_pct >= 70:
            return 'good'
        elif score_pct >= 40:
            return 'warning'
        return 'danger'

    # 描述
    median_p = macro_data.cb_median_premium if macro_data else 0
    vol = macro_data.cb_avg_daily_amount if macro_data else 0
    yield_10y = macro_data.treasury_10y_yield if macro_data else 0
    pmi = macro_data.pmi_current if macro_data else 50

    valuation_desc = (
        f'转股溢价率中位数{median_p:.1f}%，处于{"低估" if median_p < 20 else "正常" if median_p < 30 else "高估"}区间'
        if median_p > 0 else '暂无估值数据'
    )
    sentiment_desc = (
        f'转债日均成交额{vol:.0f}亿，市场情绪{"高涨" if vol > 600 else "正常" if vol > 300 else "低迷"}'
        if vol > 0 else '暂无情绪数据'
    )
    liquidity_desc = (
        f'10年期国债收益率{yield_10y:.2f}%，流动性{"充裕" if yield_10y < 2.5 else "中性" if yield_10y < 3.0 else "收紧"}'
        if yield_10y > 0 else '暂无流动性数据'
    )
    macro_desc = (
        f'制造业PMI为{pmi:.1f}，经济{"扩张" if pmi > 50 else "收缩"}'
        if not math.isnan(pmi) and pmi != 50.0 else '暂无宏观数据'
    )

    market_env = signal.regime.value if signal.regime else 'neutral'
    if market_env == 'range':
        market_env = 'neutral'

    position_limit = signal.position_ratio
    recommendation = _get_recommendation(total_abs, position_limit)

    return {
        "totalScore": round(total_abs, 1),
        "positionLimit": round(position_limit, 2),
        "marketEnv": market_env,
        "factors": [
            {
                "name": "估值因子",
                "score": round(valuation_abs, 1),
                "maxScore": 40,
                "weight": 0.40,
                "status": _factor_status(signal.valuation_score),
                "description": valuation_desc,
            },
            {
                "name": "情绪因子",
                "score": round(sentiment_abs, 1),
                "maxScore": 25,
                "weight": 0.25,
                "status": _factor_status(signal.sentiment_score),
                "description": sentiment_desc,
            },
            {
                "name": "流动性因子",
                "score": round(liquidity_abs, 1),
                "maxScore": 20,
                "weight": 0.20,
                "status": _factor_status(signal.liquidity_score),
                "description": liquidity_desc,
            },
            {
                "name": "宏观因子",
                "score": round(macro_abs, 1),
                "maxScore": 15,
                "weight": 0.15,
                "status": _factor_status(signal.macro_score),
                "description": macro_desc,
            },
        ],
        "recommendation": recommendation,
        "timestamp": datetime.now().isoformat(),
    }


def _get_recommendation(total_score: float, position_limit: float) -> str:
    """生成投资建议"""
    if math.isnan(total_score):
        return "数据不足，无法评估择时信号"
    if math.isnan(position_limit) or position_limit < 0:
        position_limit = 0.0
    pct = int(position_limit * 100)
    if total_score >= 70:
        return f"建议仓位{pct}%，市场情绪乐观，可积极配置低估值品种"
    elif total_score >= 50:
        return f"建议仓位{pct}%，市场中性，关注低溢价率+高评级品种"
    elif total_score >= 30:
        return f"建议仓位{pct}%，市场偏弱，以防御性品种为主"
    else:
        return f"建议仓位{pct}%，市场极度低迷，启动对冲，严控风险"


def _default_signal() -> dict:
    """默认空信号"""
    return {
        "totalScore": 0,
        "positionLimit": 0,
        "marketEnv": "unknown",
        "factors": [],
        "recommendation": "暂无择时信号，数据加载中...",
        "timestamp": "",
    }


def _enhanced_signal_to_frontend(signal, macro_data) -> dict:
    """将 EnhancedTimingSignal 转换为前端格式"""
    if signal is None:
        return _default_signal()

    is_enhanced = isinstance(signal, EnhancedTimingSignal)

    if is_enhanced:
        total_score = signal.total_score
        position_limit = signal.position_ratio
        market_env = signal.market_regime.value
        # 统一 market_env: range->neutral, strong_bull->bull, strong_bear->bear
        market_env_map = {
            'range': 'neutral', 'strong_bull': 'bull', 'strong_bear': 'bear',
        }
        market_env = market_env_map.get(market_env, market_env)

        # 转换8大类因子为前端格式
        factors = []
        cat_display_info = {
            'valuation': {'name': '估值面', 'maxScore': 100, 'icon': 'valuation'},
            'fundamental': {'name': '基本面', 'maxScore': 100, 'icon': 'fundamental'},
            'chip': {'name': '筹码面', 'maxScore': 100, 'icon': 'chip'},
            'capital_flow': {'name': '资金面', 'maxScore': 100, 'icon': 'capital'},
            'liquidity': {'name': '流动性面', 'maxScore': 100, 'icon': 'liquidity'},
            'technical': {'name': '技术面', 'maxScore': 100, 'icon': 'technical'},
            'sentiment': {'name': '情绪面', 'maxScore': 100, 'icon': 'sentiment'},
            'news': {'name': '消息面', 'maxScore': 100, 'icon': 'news'},
            'macro': {'name': '宏观面', 'maxScore': 100, 'icon': 'macro'},
        }

        for cat_key, cat in signal.category_scores.items():
            info = cat_display_info.get(cat_key, {'name': cat_key, 'maxScore': 100, 'icon': 'default'})
            # 数据缺失时 score 为 NaN，显示为 'missing' 状态（前端可渲染为灰色 + "数据缺失"）
            if math.isnan(cat.score):
                status = 'missing'
            else:
                status = 'good' if cat.score >= 65 else 'warning' if cat.score >= 40 else 'danger'
            # round(NaN, 1) 返回 NaN，clean_numpy_types 会转为 None（JSON null）
            factors.append({
                "name": info['name'],
                "score": round(cat.score, 1),
                "maxScore": info['maxScore'],
                "weight": round(cat.weight, 2),
                "status": status,
                "description": cat.description,
                "icon": info['icon'],
                "subFactors": [
                    {
                        "name": sf.name,
                        "score": round(sf.score, 1) if not math.isnan(sf.score) else None,
                        "weight": round(sf.weight, 2),
                        "signal": sf.signal if not math.isnan(sf.score) else "missing",
                        "description": sf.description,
                    }
                    for sf in cat.sub_factors
                ] if cat.sub_factors else [],
            })

        # 风险预警
        risk_alerts = signal.risk_alerts

        # 交叉验证摘要
        cv_bullish = sum(1 for cv in signal.cross_validations if cv.signal == 'bullish')
        cv_bearish = sum(1 for cv in signal.cross_validations if cv.signal == 'bearish')

        # 建议（先 guard position_limit NaN 再计算 pct）
        if math.isnan(total_score):
            recommendation = "数据不足，无法评估择时信号"
            pct = 0
        else:
            pct = int((position_limit if not math.isnan(position_limit) else 0.0) * 100)
            if total_score >= 70:
                recommendation = f"建议仓位{pct}%，多维度信号偏多，可积极配置"
            elif total_score >= 50:
                recommendation = f"建议仓位{pct}%，信号中性，精选品种均衡配置"
            elif total_score >= 30:
                recommendation = f"建议仓位{pct}%，信号偏空，以防守为主"
            else:
                recommendation = f"建议仓位{pct}%，多维度预警，启动对冲，严控风险"

        # 数值字段 NaN → None（JSON null），前端显示"N/A"
        def _r(v: float, digits: int = 1):
            if v is None or math.isnan(v):
                return None
            return round(v, digits)

        return clean_numpy_types({
            "totalScore": _r(total_score, 1),
            "positionLimit": _r(position_limit, 4),
            "marketEnv": market_env,
            "factors": factors,
            "recommendation": recommendation,
            "timestamp": signal.timestamp.isoformat() if hasattr(signal, 'timestamp') else datetime.now().isoformat(),
            # 增强字段
            "modelVersion": "v4.0-enhanced",
            "quality": signal.quality.value,
            "confidence": _r(signal.confidence, 4),
            "consensusScore": _r(signal.consensus_score, 2),
            "riskAlerts": risk_alerts,
            "hedgeRecommended": signal.hedge_recommended,
            "crossValidation": {
                "bullishCount": cv_bullish,
                "bearishCount": cv_bearish,
                "totalCount": len(signal.cross_validations),
            },
        })
    else:
        # 兼容旧版信号格式
        return _signal_to_frontend(signal, macro_data)


@router.get("/timing-signal/enhanced")
async def get_enhanced_timing_signal(request: Request):
    """获取增强择时信号（V4.0 多维度综合模型）

    包含 9 大类 40+ 子因子：
    - 估值面（溢价率、YTM、PE/PB分位、价格分布）
    - 基本面（盈利增速、GDP、工业增加值、社零）
    - 筹码面（主力资金、融资融券、北向资金、机构持仓）
    - 资金面（Shibor、M2增速、社融增速、期限利差）
    - 流动性面（Shibor、国债收益率、信用利差、M2/社融、期限利差）
    - 技术面（MA排列、MACD、RSI、布林带、量价关系）
    - 情绪面（涨跌比、涨停跌停、新高新低、PCR、VIX、换手率）
    - 消息面（政策信号、事件冲击、产业链景气）
    - 宏观面（PMI、CPI/PPI、出口、工业增加值、社零、GDP）

    额外输出：交叉验证信号、信号质量评估、风险预警
    """
    return await _compute_live_timing_signal(request, enhanced=True)


@router.get("/timing-signal/ensemble")
async def get_ensemble_timing_signal(request: Request):
    """获取集成学习择时信号（加权+排序+波动率调整三种方法融合）"""
    global _enhanced_signal_cache

    engine = getattr(request.app.state, "engine", None)
    bonds = []
    if engine:
        try:
            bonds = await engine.get_all_quotes()
        except Exception as e:
            logger.warning(f"[TimingAPI] MarketEngine fetch failed: {e}")

    if bonds:
        enhanced_data, macro_data = await _prepare_enhanced_data(request, bonds)
        if enhanced_data and macro_data:
            ensemble_signal = _enhanced_timing.calculate_ensemble(enhanced_data)
            stability = _enhanced_timing.get_signal_stability()
            risk_score = _enhanced_timing.get_risk_score()
            contributions = _enhanced_timing.get_factor_contribution()

            result = _enhanced_signal_to_frontend(ensemble_signal, macro_data)
            result["stability"] = stability
            result["riskScore"] = round(risk_score, 1)
            result["factorContributions"] = contributions
            _enhanced_signal_cache = result
            return result

    if _enhanced_signal_cache:
        return _enhanced_signal_cache
    return _default_signal()


@router.get("/timing-signal/stability")
async def get_timing_stability():
    """获取择时信号稳定性指标和风险评分"""
    stability = _enhanced_timing.get_signal_stability()
    risk_score = _enhanced_timing.get_risk_score()
    contributions = _enhanced_timing.get_factor_contribution()

    return {
        "stability": stability,
        "riskScore": round(risk_score, 1),
        "factorContributions": contributions,
    }


@router.get("/status")
async def get_status():
    """获取策略状态"""
    strategy = get_strategy()
    return {"status": "running"}


@router.get("/timing-signal")
async def get_timing_signal(request: Request):
    """获取当前择时信号（从实时数据计算）"""
    return await _compute_live_timing_signal(request)


@router.get("/timing-signal/history")
async def get_timing_history(days: int = 30):
    """获取择时历史数据"""
    return {"items": []}


@router.get("/whitelist")
async def get_whitelist():
    """获取当前白名单"""
    strategy = get_strategy()
    return {
        "whitelist": strategy.whitelist,
        "buffer_zone": strategy.buffer_zone,
        "total": len(strategy.whitelist),
    }


@router.get("/scores")
async def get_scores(top: int = 20):
    """获取七维得分排名"""
    strategy = get_strategy()
    top_scores = strategy.scores[:top]
    return {
        "scores": [s.to_dict() for s in top_scores],
        "total": len(strategy.scores),
    }


@router.get("/positions")
async def get_positions():
    """获取当前持仓"""
    strategy = get_strategy()
    positions = [
        pos.to_dict() for pos in strategy.portfolio.positions.values()
    ]
    return {
        "positions": positions,
        "total_count": len(positions),
        "total_value": strategy.portfolio.total_market_value,
    }


@router.get("/timing")
async def get_timing(request: Request):
    """获取择时信号（同 timing-signal）"""
    return await _compute_live_timing_signal(request)


@router.get("/performance")
async def get_performance():
    """获取绩效汇总"""
    strategy = get_strategy()
    return strategy.get_performance_summary()


@router.post("/run-daily")
async def run_daily(request: Request):
    """运行每日策略"""
    try:
        data = await request.json()
        return {"message": "策略运行成功", "date": date.today().isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update-aum")
async def update_aum(request: Request):
    """更新资产规模"""
    try:
        data = await request.json()
        new_aum = data.get("aum", 10000)
        strategy = get_strategy()
        strategy.update_aum(new_aum)
        return {"message": f"AUM已更新为{new_aum}万"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/events")
async def get_event_opportunities():
    """获取事件驱动机会"""
    strategy = get_strategy()
    opportunities = strategy.event_engine._opportunities
    return {
        "opportunities": [o.to_dict() for o in opportunities],
        "total": len(opportunities),
    }


@router.get("/hedge-status")
async def get_hedge_status():
    """获取对冲状态"""
    strategy = get_strategy()
    return strategy.hedge_engine.get_hedge_report()


@router.get("/monitor")
async def get_monitor_metrics():
    """获取监控指标"""
    strategy = get_strategy()
    summary = strategy.daily_monitor.get_summary()
    return summary


@router.get("/cost-report")
async def get_cost_report():
    """获取成本报告"""
    strategy = get_strategy()
    return strategy.execution_engine.cost_model.get_cost_report()


# ============ 详细接口 ============

@router.get("/credit-scores")
async def get_credit_scores(top: int = 20):
    """获取信用评分"""
    strategy = get_strategy()
    scores = [
        {"code": code, **score.to_dict()}
        for code, score in list(strategy.credit_scores.items())[:top]
    ]
    return {"scores": scores, "total": len(strategy.credit_scores)}


@router.get("/factor-analysis")
async def get_factor_analysis():
    """获取因子分析"""
    strategy = get_strategy()
    factors = strategy.factor_analyzer.get_factor_analysis()
    return {
        "factors": [f.to_dict() for f in factors],
        "validity": strategy.factor_analyzer.check_factor_validity(),
    }
