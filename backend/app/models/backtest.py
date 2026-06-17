from datetime import date, datetime
from typing import Optional, Union
from pydantic import BaseModel, Field


class StrategyParam(BaseModel):
    """策略参数定义"""
    name: str
    label: str
    type: str = "float"  # float, int, str, select
    default: Union[float, int, str] = 0.0
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    options: Optional[list[str]] = None  # for select
    description: Optional[str] = None


class BacktestConfig(BaseModel):
    """回测配置参数"""
    commission_pct: float = Field(default=0.0003, ge=0, le=0.03, description="佣金率")
    slippage_pct: float = Field(default=0.0003, ge=0, le=0.05, description="滑点率")
    min_commission: float = Field(default=1.0, ge=0, description="最低佣金(元)")
    risk_free_rate: float = Field(default=0.02, ge=0, le=0.1, description="无风险利率(年化)")
    initial_cash: float = Field(default=1_000_000.0, gt=0, description="初始资金(元), 默认100万")


class OptimizationParamRange(BaseModel):
    """参数优化范围定义"""
    name: str = Field(description="参数名")
    min_val: float = Field(description="最小值")
    max_val: float = Field(description="最大值")
    step: float = Field(default=1.0, description="步长")


class OptimizationConfig(BaseModel):
    """参数优化配置"""
    enabled: bool = Field(default=False, description="是否启用参数优化")
    param_ranges: list[OptimizationParamRange] = Field(default_factory=list, description="待优化参数范围")
    optimize_metric: str = Field(default="sharpe_ratio", description="优化目标(sharpe_ratio / total_return_pct / calmar_ratio)")
    max_iterations: int = Field(default=100, ge=1, le=10000, description="最大迭代次数")
    top_n: int = Field(default=10, ge=1, le=100, description="返回最优参数组合数")
    parallel_workers: int = Field(default=1, ge=1, le=16, description="并行工作进程数(1=顺序执行, >1使用ProcessPoolExecutor)")


class OptimizationResultItem(BaseModel):
    """单组优化结果"""
    params: dict[str, float] = Field(description="参数组合")
    metrics: Optional["PerformanceMetrics"] = None
    total_return_pct: float = 0.0
    annual_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0


class OptimizationResult(BaseModel):
    """参数优化完整结果"""
    strategy_name: str
    optimize_metric: str
    total_combinations: int = 0
    best_params: dict[str, float] = Field(default_factory=dict)
    best_metrics: Optional["PerformanceMetrics"] = None
    top_results: list[OptimizationResultItem] = Field(default_factory=list)
    execution_time_ms: int = 0


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
    annual_volatility: float = 0.0


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
