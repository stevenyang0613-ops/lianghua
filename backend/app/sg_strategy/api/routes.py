"""松岗量化可转债策略 V3.0 API接口

基于FastAPI的RESTful API，支持:
- 策略运行
- 信号查询
- 持仓查询
- 回测触发
- 报告生成

注意: 需要安装fastapi和uvicorn: pip install fastapi uvicorn
"""
from typing import List, Dict, Optional, Any
from datetime import date, datetime
import json
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 全局策略实例
_strategy_instance = None

# 可选依赖检查
try:
    from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    logger.warning("FastAPI未安装，API功能不可用。请运行: pip install fastapi uvicorn")

    # 创建空的占位类
    class BaseModel:
        pass

    def Field(*args, **kwargs):
        return None

    FastAPI = None
    app = None
    HTTPException = Exception
    Query = lambda *args, **kwargs: None
    BackgroundTasks = None
    CORSMiddleware = None


if FASTAPI_AVAILABLE:
    # ============ 请求/响应模型 ============

    class StrategyInitRequest(BaseModel):
        """策略初始化请求"""
        aum: float = Field(default=10000.0, description="资产规模(万元)")
        regime: str = Field(default="range", description="市场环境: bull/range/bear")
        log_level: str = Field(default="INFO", description="日志级别")


    class CBDataRequest(BaseModel):
        """可转债数据请求"""
        code: str = Field(description="转债代码")
        name: str = Field(description="转债名称")
        stock_code: str = Field(description="正股代码")
        stock_name: str = Field(description="正股名称")
        close: float = Field(description="收盘价")
        conversion_premium: float = Field(description="转股溢价率(%)")
        remaining_years: float = Field(description="剩余期限(年)")
        daily_amount_20d: float = Field(default=5000.0, description="20日均成交额(万元)")
        turnover_rate: float = Field(default=1.0, description="换手率(%)")
        conversion_price: float = Field(default=10.0, description="转股价")
        stock_price: float = Field(default=10.0, description="正股价格")


    class RunDailyRequest(BaseModel):
        """运行每日策略请求"""
        cb_data: List[CBDataRequest] = Field(description="可转债数据列表")
        market_cb_median_premium: float = Field(default=25.0, description="转债溢价率中位数")
        market_cb_avg_daily_amount: float = Field(default=500.0, description="转债日均成交额(亿)")


    class SignalResponse(BaseModel):
        """信号响应"""
        signal_id: str
        cb_code: str
        cb_name: str
        action: str
        signal_type: str
        price: float
        quantity: int
        reason: str
        confidence: float
        urgency: int


    class PositionResponse(BaseModel):
        """持仓响应"""
        cb_code: str
        cb_name: str
        quantity: int
        avg_cost: float
        current_price: float
        market_value: float
        unrealized_pnl: float
        unrealized_pnl_pct: float


    class PerformanceResponse(BaseModel):
        """绩效响应"""
        aum: float
        cash: float
        position_count: int
        total_market_value: float
        total_unrealized_pnl: float
        whitelist_size: int
        buffer_zone_size: int


    class BacktestRequest(BaseModel):
        """回测请求"""
        start_date: date = Field(description="开始日期")
        end_date: date = Field(description="结束日期")
        initial_capital: float = Field(default=10000.0, description="初始资金(万元)")
        strategy: str = Field(default="SonggangSevenDimension", description="策略名称")


    class BacktestResultResponse(BaseModel):
        """回测结果响应"""
        start_date: str
        end_date: str
        returns: float
        max_drawdown: float
        sharpe_ratio: float
        win_rate: float
        trade_count: int


    # 创建FastAPI应用
    app = FastAPI(
        title="松岗量化可转债策略 API",
        description="可转债量化策略的RESTful API接口",
        version="3.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS配置
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


    def get_strategy():
        """获取策略实例"""
        global _strategy_instance
        if _strategy_instance is None:
            from app.sg_strategy.core.strategy import SGConvertibleStrategy
            _strategy_instance = SGConvertibleStrategy()
        return _strategy_instance


    # ============ API端点 ============

    @app.get("/")
    async def root():
        """API根路径"""
        return {
            "name": "松岗量化可转债策略 API",
            "version": "3.0.0",
            "docs": "/docs",
            "endpoints": [
                "/strategy/init",
                "/strategy/run",
                "/strategy/signals",
                "/strategy/positions",
                "/strategy/performance",
                "/backtest/run",
                "/analyze/{code}",
            ]
        }


    @app.post("/strategy/init")
    async def init_strategy(request: StrategyInitRequest):
        """初始化策略"""
        from app.sg_strategy.core.strategy import SGConvertibleStrategy
        from app.sg_strategy.config.weights import MarketRegime

        regime_map = {
            'bull': MarketRegime.BULL,
            'range': MarketRegime.RANGE,
            'bear': MarketRegime.BEAR,
        }

        global _strategy_instance
        _strategy_instance = SGConvertibleStrategy(
            aum=request.aum,
            regime=regime_map.get(request.regime, MarketRegime.RANGE),
            log_level=request.log_level,
        )

        return {
            "success": True,
            "message": "策略初始化成功",
            "aum": request.aum,
            "regime": request.regime,
        }


    @app.post("/strategy/run")
    async def run_strategy(request: RunDailyRequest):
        """运行每日策略"""
        from app.sg_strategy.core.types import ConvertibleBondData
        from app.sg_strategy.core.timing import MarketData

        strategy = get_strategy()

        # 转换数据
        cb_list = [
            ConvertibleBondData(
                code=cb.code,
                name=cb.name,
                stock_code=cb.stock_code,
                stock_name=cb.stock_name,
                date=date.today(),
                close=cb.close,
                conversion_premium=cb.conversion_premium,
                remaining_years=cb.remaining_years,
                daily_amount_20d=cb.daily_amount_20d,
                turnover_rate=cb.turnover_rate,
                conversion_price=cb.conversion_price,
                stock_price=cb.stock_price,
                is_called=False,
                has_major_sell=False,
                has_limit_up_1y=True,
            )
            for cb in request.cb_data
        ]

        # 创建市场数据
        market_data = MarketData(
            date=date.today(),
            cb_median_premium=request.market_cb_median_premium,
            cb_avg_daily_amount=request.market_cb_avg_daily_amount,
        )

        # 运行策略
        report = strategy.run_daily(cb_list, None, market_data, date.today())

        return {
            "success": True,
            "date": str(report.date),
            "whitelist_count": len(report.whitelist),
            "signal_count": len(report.signals),
            "position_count": len(strategy.get_positions()),
            "aum": strategy.portfolio.aum,
        }


    @app.get("/strategy/signals", response_model=List[SignalResponse])
    async def get_signals(limit: int = Query(default=20, ge=1, le=100)):
        """获取当前信号"""
        strategy = get_strategy()
        signals = strategy.signal_generator.get_signals_today()

        return [
            SignalResponse(
                signal_id=s.signal_id,
                cb_code=s.cb_code,
                cb_name=s.cb_name,
                action=s.action.value,
                signal_type=s.signal_type.value,
                price=s.price,
                quantity=s.quantity,
                reason=s.reason,
                confidence=s.confidence,
                urgency=s.urgency,
            )
            for s in signals[:limit]
        ]


    @app.get("/strategy/positions", response_model=List[PositionResponse])
    async def get_positions():
        """获取当前持仓"""
        strategy = get_strategy()
        positions = strategy.get_positions()

        return [
            PositionResponse(
                cb_code=code,
                cb_name=pos.cb_name,
                quantity=pos.quantity,
                avg_cost=pos.avg_cost,
                current_price=pos.current_price,
                market_value=pos.market_value,
                unrealized_pnl=pos.unrealized_pnl,
                unrealized_pnl_pct=pos.unrealized_pnl_pct,
            )
            for code, pos in positions.items()
        ]


    @app.get("/strategy/performance", response_model=PerformanceResponse)
    async def get_performance():
        """获取策略绩效"""
        strategy = get_strategy()
        perf = strategy.get_performance_summary()

        return PerformanceResponse(
            aum=perf["aum"],
            cash=perf["cash"],
            position_count=perf["position_count"],
            total_market_value=perf["total_market_value"],
            total_unrealized_pnl=perf["total_unrealized_pnl"],
            whitelist_size=perf["whitelist_size"],
            buffer_zone_size=perf["buffer_zone_size"],
        )


    @app.get("/strategy/whitelist")
    async def get_whitelist(limit: int = Query(default=60, ge=1, le=100)):
        """获取白名单"""
        strategy = get_strategy()
        whitelist = strategy.get_whitelist()[:limit]

        return {
            "count": len(whitelist),
            "whitelist": whitelist,
        }


    @app.post("/backtest/run", response_model=BacktestResultResponse)
    async def run_backtest(request: BacktestRequest):
        """运行回测"""
        from app.sg_strategy.core.backtest import BacktestEngine, BacktestConfig
        import pandas as pd
        import numpy as np
        from datetime import timedelta

        # 从 AKShare 获取历史数据
        try:
            from app.sg_strategy.core.data_adapter import AkshareDataSource
            ds = AkshareDataSource()
            cb_list = ds.fetch_all_cb_data()
            if not cb_list:
                raise HTTPException(status_code=503, detail="无法获取可转债历史数据，请稍后重试")
            rows = []
            for cb in cb_list:
                rows.append({
                    'date': cb.date,
                    'code': cb.code,
                    'name': cb.name,
                    'close': cb.close,
                    'premium_ratio': cb.conversion_premium,
                    'volume': cb.volume,
                })
            cb_data = pd.DataFrame(rows)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"获取历史数据失败: {e}")

        # 运行回测
        config = BacktestConfig(
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
        )

        engine = BacktestEngine(config)
        result = engine.run_backtest(cb_data)

        return BacktestResultResponse(
            start_date=str(result.period_start),
            end_date=str(result.period_end),
            returns=round(result.returns * 100, 2),
            max_drawdown=round(result.max_drawdown * 100, 2),
            sharpe_ratio=round(result.sharpe_ratio, 2),
            win_rate=round(result.win_rate * 100, 1),
            trade_count=result.trade_count,
        )


    @app.get("/analyze/{code}")
    async def analyze_bond(code: str):
        """分析单只转债"""
        from app.sg_strategy.core.scoring import SevenDimScoringEngine
        from app.sg_strategy.core.types import ConvertibleBondData
        from app.sg_strategy.config.weights import MarketRegime

        # 模拟数据
        cb = ConvertibleBondData(
            code=code,
            name=f"转债{code[-3:]}",
            stock_code=code.replace("110", "000"),
            stock_name=f"股票{code[-3:]}",
            date=date.today(),
            close=105.0,
            conversion_premium=18.0,
            remaining_years=2.5,
            daily_amount_20d=5000.0,
            implied_vol_percentile=45.0,
            vol_skew=0.1,
            turnover_rate=1.5,
            conversion_price=10.0,
            stock_price=12.0,
        )

        engine = SevenDimScoringEngine(MarketRegime.RANGE, 10000.0)
        score = engine.score_bond(cb)

        return {
            "code": code,
            "name": cb.name,
            "score": {
                "total": round(score.total_score, 2),
                "stock_total": round(score.stock_total, 2),
                "cb_total": round(score.cb_total, 2),
                "dimensions": {
                    "short_momentum": round(score.short_momentum, 2),
                    "sector_sentiment": round(score.sector_sentiment, 2),
                    "technical": round(score.technical, 2),
                    "chip_structure": round(score.chip_structure, 2),
                    "volatility": round(score.volatility, 2),
                    "news_factor": round(score.news_factor, 2),
                    "fundamentals": round(score.fundamentals, 2),
                    "valuation": round(score.valuation, 2),
                    "clause_value": round(score.clause_value, 2),
                    "liquidity": round(score.liquidity, 2),
                    "credit": round(score.credit, 2),
                }
            }
        }


    @app.get("/health")
    async def health_check():
        """健康检查"""
        return {"status": "healthy", "timestamp": datetime.now().isoformat()}


    # ============ 启动配置 ============

    if __name__ == "__main__":
        import uvicorn
        from app.config import settings
        uvicorn.run(app, host=settings.host, port=settings.port)
