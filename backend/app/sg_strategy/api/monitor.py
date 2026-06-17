"""松岗量化可转债策略 V3.0 策略监控API

功能:
- 实时净值监控
- 持仓监控
- 风险指标监控
- 信号监控
- 性能指标监控
- 告警推送
"""
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Any
from enum import Enum
import logging
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitor", tags=["监控"])


# ============ 数据模型 ============

class MetricType(str, Enum):
    """指标类型"""
    NAV = "nav"                   # 净值
    RETURN = "return"             # 收益率
    DRAWDOWN = "drawdown"         # 回撤
    VOLATILITY = "volatility"     # 波动率
    SHARPE = "sharpe"             # 夏普比率
    POSITION = "position"         # 持仓
    SIGNAL = "signal"             # 信号


class AlertLevel(str, Enum):
    """告警级别"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class MonitorStatus(BaseModel):
    """监控状态"""
    is_running: bool
    last_update: datetime
    strategy_version: str
    data_source: str
    health_status: str


class NAVData(BaseModel):
    """净值数据"""
    date: date
    nav: float
    daily_return: float
    cumulative_return: float
    drawdown: float


class PositionSummary(BaseModel):
    """持仓摘要"""
    total_count: int
    total_value: float
    total_cost: float
    total_profit: float
    total_profit_pct: float
    top_positions: List[Dict[str, Any]]


class RiskMetrics(BaseModel):
    """风险指标"""
    var_95: float
    var_99: float
    max_drawdown: float
    current_drawdown: float
    volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    beta: float
    concentration: float


class SignalSummary(BaseModel):
    """信号摘要"""
    pending_count: int
    executed_count: int
    cancelled_count: int
    today_signals: List[Dict[str, Any]]
    recent_signals: List[Dict[str, Any]]


class PerformanceMetrics(BaseModel):
    """性能指标"""
    total_return: float
    annual_return: float
    monthly_return: float
    weekly_return: float
    daily_return: float
    win_rate: float
    profit_factor: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    average_holding_days: float


class AlertInfo(BaseModel):
    """告警信息"""
    alert_id: str
    level: AlertLevel
    type: str
    message: str
    timestamp: datetime
    is_read: bool


# ============ 监控服务 ============

class MonitorService:
    """监控服务"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._is_running = False
        self._last_update = datetime.now()
        self._alerts: List[AlertInfo] = []
        self._subscribers: List[callable] = []

        self._initialized = True

    def get_status(self) -> MonitorStatus:
        """获取监控状态"""
        return MonitorStatus(
            is_running=self._is_running,
            last_update=self._last_update,
            strategy_version="3.0.0",
            data_source="akshare",
            health_status="healthy",
        )

    def get_nav_history(
        self,
        start_date: date = None,
        end_date: date = None,
    ) -> List[NAVData]:
        """获取净值历史"""
        # 模拟数据
        end_date = end_date or date.today()
        start_date = start_date or (end_date - timedelta(days=30))

        nav_data = []
        nav = 1.0
        cumulative = 0.0

        current = start_date
        while current <= end_date:
            if current.weekday() < 5:
                daily_return = (hash(current) % 100 - 50) / 10000  # -0.5% ~ 0.5%
                nav *= (1 + daily_return)
                cumulative += daily_return

                nav_data.append(NAVData(
                    date=current,
                    nav=round(nav, 4),
                    daily_return=round(daily_return, 4),
                    cumulative_return=round(cumulative, 4),
                    drawdown=round(max(0, 1 - nav), 4),
                ))

            current += timedelta(days=1)

        return nav_data

    def get_position_summary(self) -> PositionSummary:
        """获取持仓摘要 - 需要对接真实持仓数据"""
        return PositionSummary(
            total_count=0,
            total_value=0.0,
            total_cost=0.0,
            total_profit=0.0,
            total_profit_pct=0.0,
            top_positions=[],
        )

    def get_risk_metrics(self) -> RiskMetrics:
        """获取风险指标 - 需要对接真实风控引擎"""
        return RiskMetrics(
            var_95=0.0, var_99=0.0, max_drawdown=0.0,
            current_drawdown=0.0, volatility=0.0,
            sharpe_ratio=0.0, sortino_ratio=0.0,
            beta=0.0, concentration=0.0,
        )

    def get_signal_summary(self) -> SignalSummary:
        """获取信号摘要"""
        return SignalSummary(
            pending_count=0,
            executed_count=0,
            cancelled_count=0,
            today_signals=[],
            recent_signals=[],
        )

    def get_performance_metrics(self) -> PerformanceMetrics:
        """获取性能指标 - 需要对接真实绩效计算"""
        return PerformanceMetrics(
            total_return=0.0, annual_return=0.0, monthly_return=0.0,
            weekly_return=0.0, daily_return=0.0, win_rate=0.0,
            profit_factor=0.0, max_consecutive_wins=0,
            max_consecutive_losses=0, average_holding_days=0.0,
        )

    def get_alerts(
        self,
        level: AlertLevel = None,
        limit: int = 20,
    ) -> List[AlertInfo]:
        """获取告警"""
        alerts = self._alerts

        if level:
            alerts = [a for a in alerts if a.level == level]

        return alerts[-limit:]

    def add_alert(self, alert: AlertInfo):
        """添加告警"""
        self._alerts.append(alert)
        # 保留最近100条
        if len(self._alerts) > 100:
            self._alerts = self._alerts[-100:]

        # 通知订阅者
        for subscriber in self._subscribers:
            try:
                subscriber(alert)
            except Exception as e:
                logger.error(f"[MonitorService] 通知订阅者失败: {e}")

    def subscribe(self, callback: callable):
        """订阅告警"""
        self._subscribers.append(callback)

    def unsubscribe(self, callback: callable):
        """取消订阅"""
        if callback in self._subscribers:
            self._subscribers.remove(callback)


def get_monitor_service() -> MonitorService:
    """获取监控服务"""
    return MonitorService()


# ============ API路由 ============

@router.get("/status", response_model=MonitorStatus, summary="获取监控状态")
async def get_status(
    service: MonitorService = Depends(get_monitor_service),
):
    """获取监控状态"""
    return service.get_status()


@router.get("/nav", response_model=List[NAVData], summary="获取净值历史")
async def get_nav_history(
    start_date: date = Query(None, description="开始日期"),
    end_date: date = Query(None, description="结束日期"),
    service: MonitorService = Depends(get_monitor_service),
):
    """获取净值历史数据"""
    return service.get_nav_history(start_date, end_date)


@router.get("/nav/latest", response_model=NAVData, summary="获取最新净值")
async def get_latest_nav(
    service: MonitorService = Depends(get_monitor_service),
):
    """获取最新净值"""
    nav_history = service.get_nav_history(end_date=date.today())
    if nav_history:
        return nav_history[-1]
    raise HTTPException(status_code=404, detail="无净值数据")


@router.get("/positions", response_model=PositionSummary, summary="获取持仓摘要")
async def get_positions(
    service: MonitorService = Depends(get_monitor_service),
):
    """获取持仓摘要"""
    return service.get_position_summary()


@router.get("/risk", response_model=RiskMetrics, summary="获取风险指标")
async def get_risk_metrics(
    service: MonitorService = Depends(get_monitor_service),
):
    """获取风险指标"""
    return service.get_risk_metrics()


@router.get("/signals", response_model=SignalSummary, summary="获取信号摘要")
async def get_signals(
    service: MonitorService = Depends(get_monitor_service),
):
    """获取信号摘要"""
    return service.get_signal_summary()


@router.get("/performance", response_model=PerformanceMetrics, summary="获取性能指标")
async def get_performance(
    service: MonitorService = Depends(get_monitor_service),
):
    """获取性能指标"""
    return service.get_performance_metrics()


@router.get("/alerts", response_model=List[AlertInfo], summary="获取告警列表")
async def get_alerts(
    level: AlertLevel = Query(None, description="告警级别"),
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
    service: MonitorService = Depends(get_monitor_service),
):
    """获取告警列表"""
    return service.get_alerts(level, limit)


@router.post("/alerts", response_model=AlertInfo, summary="创建告警")
async def create_alert(
    level: AlertLevel,
    alert_type: str,
    message: str,
    service: MonitorService = Depends(get_monitor_service),
):
    """创建告警"""
    import uuid

    alert = AlertInfo(
        alert_id=str(uuid.uuid4()),
        level=level,
        type=alert_type,
        message=message,
        timestamp=datetime.now(),
        is_read=False,
    )

    service.add_alert(alert)
    return alert


@router.get("/dashboard", summary="获取仪表盘数据")
async def get_dashboard(
    service: MonitorService = Depends(get_monitor_service),
):
    """获取仪表盘汇总数据"""
    return {
        "status": service.get_status(),
        "nav": service.get_nav_history(end_date=date.today())[-1] if service.get_nav_history(end_date=date.today()) else None,
        "positions": service.get_position_summary(),
        "risk": service.get_risk_metrics(),
        "signals": service.get_signal_summary(),
        "performance": service.get_performance_metrics(),
        "alerts": service.get_alerts(limit=5),
    }


@router.get("/realtime/stream", summary="实时数据流")
async def realtime_stream(
    service: MonitorService = Depends(get_monitor_service),
):
    """SSE实时数据流"""

    async def event_generator():
        while True:
            try:
                data = {
                    "timestamp": datetime.now().isoformat(),
                    "nav": service.get_nav_history(end_date=date.today())[-1].dict() if service.get_nav_history(end_date=date.today()) else None,
                    "positions": service.get_position_summary().dict(),
                    "risk": service.get_risk_metrics().dict(),
                }

                yield f"data: {data}\n\n"
                await asyncio.sleep(5)  # 每5秒推送一次

            except Exception as e:
                logger.error(f"[SSE] 推送失败: {e}")
                await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


@router.get("/metrics/prometheus", summary="Prometheus指标")
async def get_prometheus_metrics(
    service: MonitorService = Depends(get_monitor_service),
):
    """获取Prometheus格式指标"""
    status = service.get_status()
    positions = service.get_position_summary()
    risk = service.get_risk_metrics()
    performance = service.get_performance_metrics()

    metrics = f"""# HELP sg_strategy_nav_current 当前净值
# TYPE sg_strategy_nav_current gauge
sg_strategy_nav_current {service.get_nav_history(end_date=date.today())[-1].nav if service.get_nav_history(end_date=date.today()) else 0}

# HELP sg_strategy_position_count 持仓数量
# TYPE sg_strategy_position_count gauge
sg_strategy_position_count {positions.total_count}

# HELP sg_strategy_position_value 持仓市值
# TYPE sg_strategy_position_value gauge
sg_strategy_position_value {positions.total_value}

# HELP sg_strategy_profit_total 总收益
# TYPE sg_strategy_profit_total gauge
sg_strategy_profit_total {positions.total_profit}

# HELP sg_strategy_drawdown_max 最大回撤
# TYPE sg_strategy_drawdown_max gauge
sg_strategy_drawdown_max {risk.max_drawdown}

# HELP sg_strategy_drawdown_current 当前回撤
# TYPE sg_strategy_drawdown_current gauge
sg_strategy_drawdown_current {risk.current_drawdown}

# HELP sg_strategy_var_95 VaR 95%
# TYPE sg_strategy_var_95 gauge
sg_strategy_var_95 {risk.var_95}

# HELP sg_strategy_sharpe_ratio 夏普比率
# TYPE sg_strategy_sharpe_ratio gauge
sg_strategy_sharpe_ratio {risk.sharpe_ratio}

# HELP sg_strategy_return_annual 年化收益
# TYPE sg_strategy_return_annual gauge
sg_strategy_return_annual {performance.annual_return}

# HELP sg_strategy_win_rate 胜率
# TYPE sg_strategy_win_rate gauge
sg_strategy_win_rate {performance.win_rate}
"""

    return StreamingResponse(
        iter([metrics]),
        media_type="text/plain",
    )


# ============ 健康检查 ============

@router.get("/health", summary="健康检查")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "3.0.0",
    }


@router.get("/ready", summary="就绪检查")
async def readiness_check(
    service: MonitorService = Depends(get_monitor_service),
):
    """就绪检查端点"""
    status = service.get_status()
    return {
        "ready": True,
        "strategy_running": status.is_running,
        "last_update": status.last_update.isoformat(),
    }
