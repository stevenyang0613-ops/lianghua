"""松岗量化可转债策略 V3.0 前端仪表盘API模块

功能:
- 仪表盘数据接口
- 图表数据格式
- 实时数据推送
- 数据聚合
- 导出功能
"""
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Any
from enum import Enum
import logging
import json
from fastapi import Depends, Query

from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["仪表盘"])


# ============ 数据模型 ============

class ChartType(str, Enum):
    """图表类型"""
    LINE = "line"
    AREA = "area"
    BAR = "bar"
    PIE = "pie"
    SCATTER = "scatter"
    HEATMAP = "heatmap"
    TREEMAP = "treemap"


class DataType(str, Enum):
    """数据类型"""
    NAV = "nav"
    RETURN = "return"
    POSITION = "position"
    SIGNAL = "signal"
    TRADE = "trade"
    RISK = "risk"


# ============ 仪表盘数据模型 ============

class DashboardSummary(BaseModel):
    """仪表盘汇总"""
    # 净值信息
    nav: float
    nav_date: date
    daily_return: float
    monthly_return: float
    annual_return: float

    # 持仓信息
    position_count: int
    position_value: float
    cash: float
    total_value: float

    # 风险指标
    drawdown: float
    max_drawdown: float
    sharpe_ratio: float
    var_95: float

    # 信号信息
    pending_signals: int
    today_trades: int

    # 更新时间
    last_update: datetime


class NavChartData(BaseModel):
    """净值曲线数据"""
    dates: List[str]
    nav_values: List[float]
    benchmark_values: Optional[List[float]] = None
    drawdown_values: Optional[List[float]] = None


class PositionChartData(BaseModel):
    """持仓分布数据"""
    labels: List[str]
    values: List[float]
    percentages: List[float]
    colors: Optional[List[str]] = None


class ReturnChartData(BaseModel):
    """收益分布数据"""
    daily_returns: List[float]
    positive_days: int
    negative_days: int
    win_rate: float


class SignalChartData(BaseModel):
    """信号统计图表"""
    dates: List[str]
    buy_signals: List[int]
    sell_signals: List[int]
    success_rate: List[float]


class RiskChartData(BaseModel):
    """风险指标图表"""
    dates: List[str]
    var_95: List[float]
    drawdown: List[float]
    volatility: List[float]


class HeatmapData(BaseModel):
    """热力图数据"""
    x_labels: List[str]
    y_labels: List[str]
    values: List[List[float]]


# ============ 仪表盘服务 ============

class DashboardService:
    """仪表盘服务"""

    def __init__(self):
        self._cache = {}
        self._last_update = None

    def get_summary(self) -> DashboardSummary:
        """获取汇总数据"""
        # 模拟数据
        return DashboardSummary(
            nav=1.25,
            nav_date=date.today(),
            daily_return=0.005,
            monthly_return=0.02,
            annual_return=0.18,
            position_count=15,
            position_value=8500000.0,
            cash=1500000.0,
            total_value=10000000.0,
            drawdown=0.02,
            max_drawdown=0.08,
            sharpe_ratio=1.85,
            var_95=0.025,
            pending_signals=3,
            today_trades=5,
            last_update=datetime.now(),
        )

    def get_nav_chart(
        self,
        start_date: date = None,
        end_date: date = None,
        include_benchmark: bool = True,
        include_drawdown: bool = True,
    ) -> NavChartData:
        """获取净值曲线"""
        end_date = end_date or date.today()
        start_date = start_date or (end_date - timedelta(days=90))

        # 生成日期序列
        dates = []
        nav_values = []
        benchmark_values = []
        drawdown_values = []

        current = start_date
        nav = 1.0
        benchmark = 1.0
        max_nav = 1.0

        while current <= end_date:
            if current.weekday() < 5:
                dates.append(current.strftime("%Y-%m-%d"))

                # 模拟净值变化
                import random
                change = random.uniform(-0.02, 0.025)
                nav *= (1 + change)
                nav_values.append(round(nav, 4))

                # 基准
                benchmark_change = random.uniform(-0.015, 0.018)
                benchmark *= (1 + benchmark_change)
                benchmark_values.append(round(benchmark, 4))

                # 回撤
                max_nav = max(max_nav, nav)
                drawdown = (max_nav - nav) / max_nav
                drawdown_values.append(round(drawdown, 4))

            current += timedelta(days=1)

        return NavChartData(
            dates=dates,
            nav_values=nav_values,
            benchmark_values=benchmark_values if include_benchmark else None,
            drawdown_values=drawdown_values if include_drawdown else None,
        )

    def get_position_distribution(
        self,
        by: str = "code",  # code, sector, rating
    ) -> PositionChartData:
        """获取持仓分布"""
        if by == "sector":
            return PositionChartData(
                labels=["金融", "科技", "消费", "医药", "制造", "其他"],
                values=[2000000, 1500000, 1800000, 1200000, 1500000, 500000],
                percentages=[0.235, 0.176, 0.212, 0.141, 0.176, 0.059],
                colors=["#5470c6", "#91cc75", "#fac858", "#ee6666", "#73c0de", "#3ba272"],
            )
        elif by == "rating":
            return PositionChartData(
                labels=["AAA", "AA+", "AA", "AA-", "A+"],
                values=[3000000, 2500000, 2000000, 500000, 500000],
                percentages=[0.353, 0.294, 0.235, 0.059, 0.059],
            )
        else:
            return PositionChartData(
                labels=["转债A", "转债B", "转债C", "转债D", "转债E"],
                values=[800000, 700000, 600000, 600000, 500000],
                percentages=[0.211, 0.184, 0.158, 0.158, 0.132],
            )

    def get_return_distribution(
        self,
        start_date: date = None,
        end_date: date = None,
    ) -> ReturnChartData:
        """获取收益分布"""
        end_date = end_date or date.today()
        start_date = start_date or (end_date - timedelta(days=90))

        import random

        daily_returns = []
        current = start_date

        while current <= end_date:
            if current.weekday() < 5:
                daily_returns.append(round(random.uniform(-0.02, 0.025), 4))
            current += timedelta(days=1)

        positive = sum(1 for r in daily_returns if r > 0)
        negative = sum(1 for r in daily_returns if r < 0)

        return ReturnChartData(
            daily_returns=daily_returns,
            positive_days=positive,
            negative_days=negative,
            win_rate=positive / len(daily_returns) if daily_returns else 0,
        )

    def get_signal_chart(
        self,
        start_date: date = None,
        end_date: date = None,
    ) -> SignalChartData:
        """获取信号统计图表"""
        end_date = end_date or date.today()
        start_date = start_date or (end_date - timedelta(days=30))

        dates = []
        buy_signals = []
        sell_signals = []
        success_rate = []

        current = start_date
        while current <= end_date:
            if current.weekday() < 5:
                dates.append(current.strftime("%Y-%m-%d"))

                import random
                buy_signals.append(random.randint(0, 5))
                sell_signals.append(random.randint(0, 3))
                success_rate.append(round(random.uniform(0.5, 0.9), 2))

            current += timedelta(days=1)

        return SignalChartData(
            dates=dates,
            buy_signals=buy_signals,
            sell_signals=sell_signals,
            success_rate=success_rate,
        )

    def get_risk_chart(
        self,
        start_date: date = None,
        end_date: date = None,
    ) -> RiskChartData:
        """获取风险指标图表"""
        end_date = end_date or date.today()
        start_date = start_date or (end_date - timedelta(days=90))

        dates = []
        var_95 = []
        drawdown = []
        volatility = []

        current = start_date
        while current <= end_date:
            if current.weekday() < 5:
                dates.append(current.strftime("%Y-%m-%d"))

                import random
                var_95.append(round(random.uniform(0.01, 0.04), 4))
                drawdown.append(round(random.uniform(0, 0.05), 4))
                volatility.append(round(random.uniform(0.08, 0.15), 4))

            current += timedelta(days=1)

        return RiskChartData(
            dates=dates,
            var_95=var_95,
            drawdown=drawdown,
            volatility=volatility,
        )

    def get_performance_heatmap(
        self,
        year: int = None,
        metric: str = "return",  # return, volatility, sharpe
    ) -> HeatmapData:
        """获取绩效热力图"""
        year = year or date.today().year

        import random

        # 月份标签
        months = ["1月", "2月", "3月", "4月", "5月", "6月",
                  "7月", "8月", "9月", "10月", "11月", "12月"]

        # 周标签
        weeks = ["第1周", "第2周", "第3周", "第4周", "第5周"]

        # 生成数据
        values = []
        for _ in range(5):
            row = []
            for _ in range(12):
                if metric == "return":
                    row.append(round(random.uniform(-0.02, 0.03), 4))
                elif metric == "volatility":
                    row.append(round(random.uniform(0.005, 0.02), 4))
                else:
                    row.append(round(random.uniform(-0.5, 2.0), 2))
            values.append(row)

        return HeatmapData(
            x_labels=months,
            y_labels=weeks,
            values=values,
        )

    def get_sector_rotation(
        self,
        periods: int = 6,
    ) -> Dict[str, Any]:
        """获取板块轮动数据"""
        import random

        sectors = ["金融", "科技", "消费", "医药", "制造", "能源"]
        months = [(date.today() - timedelta(days=30*i)).strftime("%Y-%m") for i in range(periods)][::-1]

        data = {
            "sectors": sectors,
            "periods": months,
            "weights": [],
        }

        for _ in months:
            weights = [round(random.uniform(0.1, 0.25), 2) for _ in sectors]
            total = sum(weights)
            weights = [round(w / total, 2) for w in weights]
            data["weights"].append(weights)

        return data

    def get_top_holdings(self, limit: int = 10) -> List[Dict]:
        """获取Top持仓"""
        import random

        holdings = []
        for i in range(limit):
            profit_pct = random.uniform(-0.05, 0.15)
            holdings.append({
                "rank": i + 1,
                "code": f"11000{i+1}",
                "name": f"转债{chr(65+i)}",
                "quantity": random.randint(500, 2000) * 100,
                "cost_price": round(random.uniform(95, 110), 2),
                "market_price": round(random.uniform(95, 120), 2),
                "market_value": round(random.uniform(500000, 1000000), 2),
                "profit_pct": round(profit_pct, 4),
                "weight": round(random.uniform(0.02, 0.08), 4),
                "score": round(random.uniform(60, 90), 1),
            })

        return sorted(holdings, key=lambda x: x["market_value"], reverse=True)

    def get_recent_trades(self, limit: int = 20) -> List[Dict]:
        """获取最近交易"""
        import random

        trades = []
        actions = ["buy", "sell"]
        codes = [f"11000{i}" for i in range(1, 21)]

        for i in range(limit):
            action = random.choice(actions)
            trades.append({
                "trade_id": f"T{datetime.now().strftime('%Y%m%d')}{i:04d}",
                "time": (datetime.now() - timedelta(minutes=random.randint(0, 1440))).isoformat(),
                "code": random.choice(codes),
                "action": action,
                "quantity": random.randint(1, 10) * 100,
                "price": round(random.uniform(95, 115), 2),
                "amount": round(random.uniform(10000, 100000), 2),
                "status": "filled",
            })

        return sorted(trades, key=lambda x: x["time"], reverse=True)

    def export_data(
        self,
        data_type: str,
        start_date: date = None,
        end_date: date = None,
        format: str = "csv",  # csv, excel, json
    ) -> bytes:
        """导出数据"""
        import io

        # 获取数据
        if data_type == "nav":
            data = self.get_nav_chart(start_date, end_date)
            df_data = {
                "date": data.dates,
                "nav": data.nav_values,
            }
            if data.benchmark_values:
                df_data["benchmark"] = data.benchmark_values
            if data.drawdown_values:
                df_data["drawdown"] = data.drawdown_values

        elif data_type == "position":
            positions = self.get_top_holdings(100)
            df_data = positions

        else:
            df_data = []

        # 转换格式
        if format == "json":
            return json.dumps(df_data, ensure_ascii=False, indent=2).encode('utf-8')

        elif format == "csv":
            import pandas as pd
            df = pd.DataFrame(df_data)
            output = io.StringIO()
            df.to_csv(output, index=False)
            return output.getvalue().encode('utf-8')

        elif format == "excel":
            import pandas as pd
            df = pd.DataFrame(df_data)
            output = io.BytesIO()
            df.to_excel(output, index=False)
            return output.getvalue()

        return b""


def get_dashboard_service() -> DashboardService:
    """获取仪表盘服务"""
    return DashboardService()


# ============ API路由 ============

@router.get("/summary", response_model=DashboardSummary, summary="获取仪表盘汇总")
async def get_dashboard_summary(
    service: DashboardService = Depends(lambda: get_dashboard_service()),
):
    """获取仪表盘汇总数据"""
    return service.get_summary()


@router.get("/nav-chart", response_model=NavChartData, summary="获取净值曲线")
async def get_nav_chart(
    start_date: date = Query(None, description="开始日期"),
    end_date: date = Query(None, description="结束日期"),
    include_benchmark: bool = Query(True, description="包含基准"),
    include_drawdown: bool = Query(True, description="包含回撤"),
    service: DashboardService = Depends(lambda: get_dashboard_service()),
):
    """获取净值曲线图表数据"""
    return service.get_nav_chart(start_date, end_date, include_benchmark, include_drawdown)


@router.get("/position-distribution", response_model=PositionChartData, summary="获取持仓分布")
async def get_position_distribution(
    by: str = Query("code", description="分组方式: code, sector, rating"),
    service: DashboardService = Depends(lambda: get_dashboard_service()),
):
    """获取持仓分布图表数据"""
    return service.get_position_distribution(by)


@router.get("/return-distribution", response_model=ReturnChartData, summary="获取收益分布")
async def get_return_distribution(
    start_date: date = Query(None, description="开始日期"),
    end_date: date = Query(None, description="结束日期"),
    service: DashboardService = Depends(lambda: get_dashboard_service()),
):
    """获取收益分布图表数据"""
    return service.get_return_distribution(start_date, end_date)


@router.get("/signal-chart", response_model=SignalChartData, summary="获取信号统计")
async def get_signal_chart(
    start_date: date = Query(None, description="开始日期"),
    end_date: date = Query(None, description="结束日期"),
    service: DashboardService = Depends(lambda: get_dashboard_service()),
):
    """获取信号统计图表数据"""
    return service.get_signal_chart(start_date, end_date)


@router.get("/risk-chart", response_model=RiskChartData, summary="获取风险指标")
async def get_risk_chart(
    start_date: date = Query(None, description="开始日期"),
    end_date: date = Query(None, description="结束日期"),
    service: DashboardService = Depends(lambda: get_dashboard_service()),
):
    """获取风险指标图表数据"""
    return service.get_risk_chart(start_date, end_date)


@router.get("/performance-heatmap", response_model=HeatmapData, summary="获取绩效热力图")
async def get_performance_heatmap(
    year: int = Query(None, description="年份"),
    metric: str = Query("return", description="指标: return, volatility, sharpe"),
    service: DashboardService = Depends(lambda: get_dashboard_service()),
):
    """获取绩效热力图数据"""
    return service.get_performance_heatmap(year, metric)


@router.get("/sector-rotation", summary="获取板块轮动")
async def get_sector_rotation(
    periods: int = Query(6, ge=1, le=12, description="周期数"),
    service: DashboardService = Depends(lambda: get_dashboard_service()),
):
    """获取板块轮动数据"""
    return service.get_sector_rotation(periods)


@router.get("/top-holdings", summary="获取Top持仓")
async def get_top_holdings(
    limit: int = Query(10, ge=1, le=100, description="数量"),
    service: DashboardService = Depends(lambda: get_dashboard_service()),
):
    """获取Top持仓列表"""
    return service.get_top_holdings(limit)


@router.get("/recent-trades", summary="获取最近交易")
async def get_recent_trades(
    limit: int = Query(20, ge=1, le=100, description="数量"),
    service: DashboardService = Depends(lambda: get_dashboard_service()),
):
    """获取最近交易列表"""
    return service.get_recent_trades(limit)


@router.get("/export", summary="导出数据")
async def export_data(
    data_type: str = Query(..., description="数据类型: nav, position, trade, signal"),
    start_date: date = Query(None, description="开始日期"),
    end_date: date = Query(None, description="结束日期"),
    format: str = Query("csv", description="格式: csv, excel, json"),
    service: DashboardService = Depends(lambda: get_dashboard_service()),
):
    """导出数据"""
    data = service.export_data(data_type, start_date, end_date, format)

    media_types = {
        "csv": "text/csv",
        "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "json": "application/json",
    }

    filename = f"{data_type}_{date.today().isoformat()}.{format}"

    return Response(
        content=data,
        media_type=media_types.get(format, "application/octet-stream"),
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/widget/nav-ticker", summary="净值滚动组件数据")
async def get_nav_ticker(
    service: DashboardService = Depends(lambda: get_dashboard_service()),
):
    """获取净值滚动组件数据"""
    summary = service.get_summary()
    return {
        "nav": summary.nav,
        "daily_return": summary.daily_return,
        "drawdown": summary.drawdown,
        "position_count": summary.position_count,
        "sharpe": summary.sharpe_ratio,
    }


@router.get("/widget/mini-chart", summary="迷你图表数据")
async def get_mini_chart(
    chart_type: str = Query("nav", description="图表类型: nav, return, risk"),
    days: int = Query(30, ge=7, le=90, description="天数"),
    service: DashboardService = Depends(lambda: get_dashboard_service()),
):
    """获取迷你图表数据"""
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    if chart_type == "nav":
        data = service.get_nav_chart(start_date, end_date, False, False)
        return {"values": data.nav_values[-days:]}
    elif chart_type == "return":
        data = service.get_return_distribution(start_date, end_date)
        return {"values": data.daily_returns[-days:]}
    else:
        data = service.get_risk_chart(start_date, end_date)
        return {"var": data.var_95[-days:], "drawdown": data.drawdown[-days:]}
