from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


class StrategyParam(BaseModel):
    """策略参数定义"""
    name: str
    label: str
    type: str = "float"  # float, int, string, select
    default: float = 0.0
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    options: Optional[list[str]] = None  # for select type


class TradeRecord(BaseModel):
    """单笔交易记录"""
    code: str
    name: str = ""
    buy_date: date
    sell_date: Optional[date] = None
    buy_price: float = 0.0
    sell_price: Optional[float] = None
    volume: int = 0
    profit_pct: Optional[float] = None
    profit_amount: Optional[float] = None
    hold_days: Optional[int] = None
    reason: str = ""


class MonthlyReturn(BaseModel):
    """月度收益"""
    year: int
    month: int
    return_pct: float


class PerformanceMetrics(BaseModel):
    """绩效指标"""
    total_return_pct: float = 0.0
    annual_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    win_rate: float = 0.0
    profit_loss_ratio: float = 0.0
    total_trades: int = 0
    avg_hold_days: float = 0.0


class BacktestResult(BaseModel):
    """完整回测结果"""
    strategy_name: str
    strategy_params: dict = {}
    start_date: date
    end_date: date
    metrics: PerformanceMetrics = Field(default_factory=PerformanceMetrics)
    equity_curve: list[dict] = []  # [{"date": "2024-01-01", "value": 1.0}]
    trades: list[TradeRecord] = []
    monthly_returns: list[MonthlyReturn] = []
    benchmark_curve: Optional[list[dict]] = None
    created_at: datetime = Field(default_factory=datetime.now)
    execution_time_ms: int = 0
