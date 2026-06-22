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
    impact_cost_pct: float = Field(default=0.0000, ge=0, le=0.01, description="冲击成本率（大资金日频调仓时显著）")
    min_commission: float = Field(default=1.0, ge=0, description="最低佣金(元)")
    risk_free_rate: float = Field(default=0.02, ge=0, le=0.1, description="无风险利率(年化)")
    initial_cash: float = Field(default=1_000_000.0, gt=0, description="初始资金(元), 默认100万")
    benchmark: Optional[str] = Field(default="equal_weight", description="基准类型: csi_convertible_bond=中证转债指数, equal_weight=等权平均, None=无基准")


class CostSensitivityItem(BaseModel):
    """单组成本敏感性结果"""
    commission_pct: float
    slippage_pct: float
    total_return_pct: float
    annual_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    total_cost: float
    cost_drag_pct: float = Field(description="成本拖累 = 无成本收益 - 实际收益")


class CostSensitivityResult(BaseModel):
    """成本敏感性分析结果"""
    baseline: CostSensitivityItem
    scenarios: list[CostSensitivityItem] = Field(default_factory=list)
    best_params: dict[str, float] = Field(default_factory=dict, description="成本最低场景参数")
    worst_params: dict[str, float] = Field(default_factory=dict, description="成本最高场景参数")


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
    search_mode: str = Field(default="random", description="搜索模式: random=随机搜索, grid=网格搜索(遍历所有组合), bayesian=贝叶斯优化(optuna)")
    # 改进 (2025-06-15g): 添加 checkpoint 开关，短优化可关闭以减少 IO 开销
    checkpoint_enabled: bool = Field(default=True, description="是否启用优化进度 checkpoint 持久化")
    # 改进 (2025-06-15h): 添加内存上限，超过时自动减少并发或降级串行
    max_memory_mb: int = Field(default=4096, ge=512, le=65536, description="最大内存使用(MB)，超过时自动调整")
    # 改进 (2025-06-15i): warm_start 从上次最优参数邻域搜索
    warm_start: bool = Field(default=False, description="是否从上次最优参数邻域开始搜索(需配合 checkpoint)")
    # 改进 (2025-06-15i): 早停 patience，连续 N 个组合无改进时提前终止
    early_stop_patience: int = Field(default=0, ge=0, le=1000, description="早停耐心值，0=禁用，>0=连续N个无改进则终止")
    # 改进 (2025-06-15i): 是否使用 ThreadPoolExecutor 替代 ProcessPoolExecutor(适合IO密集型回测)
    use_threadpool: bool = Field(default=False, description="是否使用线程池替代进程池(适合IO密集型回测)")
    # 改进 (2025-06-15i): 是否持久化优化结果到 SQLite
    persist_history: bool = Field(default=True, description="是否将优化结果持久化到 SQLite 历史库")
    # 改进 (2025-06-15j): 进度回调间隔，按完成百分比触发(1=每1%, 5=每5%, 10=每10%)
    progress_interval: int = Field(default=10, ge=1, le=100, description="进度回调间隔百分比(1=每1%, 5=每5%)")
    # 改进 (2025-06-15l): Pareto 多目标优化配置
    pareto_metrics: list[str] = Field(default_factory=list, description="多目标优化指标列表，空=单目标")
    # 改进 (2025-06-15l): 使用 multiprocessing.Pool 替代 ProcessPoolExecutor
    use_pool_map: bool = Field(default=False, description="是否使用 multiprocessing.Pool.map 替代 ProcessPoolExecutor")
    # 改进 (2025-06-15l): 使用 ray 分布式并行
    use_ray: bool = Field(default=False, description="是否使用 ray 分布式并行")

    def model_post_init(self, __context):
        """验证 search_mode 合法性"""
        if self.search_mode not in ("random", "grid", "bayesian"):
            raise ValueError(f"search_mode 必须是 'random', 'grid' 或 'bayesian',  got '{self.search_mode}'")


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

    def top_results_by(self, metric: str, n: int = 10) -> list[OptimizationResultItem]:
        """改进 (2025-06-15k): 按指定指标排序返回 top_n 结果

        Args:
            metric: 排序指标字段名 (如 'sharpe_ratio', 'max_drawdown_pct', 'total_return_pct')
            n: 返回结果数量

        Returns:
            按该指标降序排列的结果列表
        """
        return sorted(
            self.top_results,
            key=lambda x: getattr(x, metric, 0.0),
            reverse=True,
        )[:n]

    def plot_results(self, param_x: str, param_y: str, metric_color: str = 'sharpe_ratio', save_path: Optional[str] = None) -> Optional[str]:
        """改进 (2025-06-15k): 参数空间可视化热力图/散点图

        Args:
            param_x: X 轴参数名
            param_y: Y 轴参数名
            metric_color: 颜色映射指标
            save_path: 保存路径，None 则返回 base64 编码

        Returns:
            如果 save_path 为 None，返回 base64 编码的图片字符串；否则返回保存路径
        """
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        if not self.top_results:
            return None

        x_vals = [r.params.get(param_x, 0) for r in self.top_results]
        y_vals = [r.params.get(param_y, 0) for r in self.top_results]
        c_vals = [getattr(r, metric_color, 0.0) for r in self.top_results]

        fig, ax = plt.subplots(figsize=(10, 8))
        sc = ax.scatter(x_vals, y_vals, c=c_vals, cmap='RdYlGn', s=80, edgecolors='black', linewidth=0.5)
        ax.set_xlabel(param_x)
        ax.set_ylabel(param_y)
        ax.set_title(f'{self.strategy_name} 参数空间: {param_x} vs {param_y} (颜色={metric_color})')
        cbar = plt.colorbar(sc, ax=ax)
        cbar.set_label(metric_color)

        # 标注最优值
        if self.top_results:
            best = self.top_results[0]
            ax.annotate(
                f'Best\n{getattr(best, metric_color, 0.0):.2f}',
                (best.params.get(param_x, 0), best.params.get(param_y, 0)),
                textcoords="offset points", xytext=(10, 10), fontsize=9,
                bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.7)
            )

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            plt.close(fig)
            return save_path
        else:
            import io
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
            plt.close(fig)
            buf.seek(0)
            import base64
            return base64.b64encode(buf.read()).decode('utf-8')


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
    benchmark_metrics: Optional[PerformanceMetrics] = None  # 基准绩效指标
    excess_metrics: Optional[PerformanceMetrics] = None  # 超额收益指标
    created_at: datetime = Field(default_factory=datetime.now)
    execution_time_ms: int = 0
    total_cost: float = 0.0  # 总交易成本
    cost_sensitivity: Optional["CostSensitivityResult"] = None
