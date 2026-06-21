"""西部量化可转债策略 V3.0 智能对冲系统模块

功能:
- 动态对冲比率
- Delta中性策略
- 跨品种对冲
- 成本优化对冲
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, Tuple
from enum import Enum
import logging
import math
import numpy as np
from collections import defaultdict

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class HedgeType(str, Enum):
    """对冲类型"""
    DELTA = "delta"             # Delta对冲
    BETA = "beta"               # Beta对冲
    SECTOR = "sector"           # 行业对冲
    FACTOR = "factor"           # 因子对冲
    CROSS_ASSET = "cross_asset" # 跨资产对冲


class HedgeFrequency(str, Enum):
    """对冲频率"""
    CONTINUOUS = "continuous"   # 连续对冲
    HOURLY = "hourly"           # 每小时
    DAILY = "daily"             # 每日
    THRESHOLD = "threshold"     # 阈值触发


class HedgeStatus(str, Enum):
    """对冲状态"""
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"


# ============ 数据模型 ============

@dataclass
class HedgePosition:
    """对冲头寸"""
    position_id: str
    hedge_type: HedgeType
    underlying: str
    hedge_instrument: str
    quantity: float
    entry_price: float
    current_price: float
    hedge_ratio: float
    pnl: float = 0
    status: HedgeStatus = HedgeStatus.ACTIVE
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()

    def calculate_pnl(self, market_price: float) -> float:
        """计算盈亏"""
        self.pnl = (market_price - self.entry_price) * self.quantity
        self.current_price = market_price
        return self.pnl

    def to_dict(self) -> dict:
        return {
            "position_id": self.position_id,
            "hedge_type": self.hedge_type.value,
            "underlying": self.underlying,
            "hedge_instrument": self.hedge_instrument,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "hedge_ratio": self.hedge_ratio,
            "pnl": round(self.pnl, 4),
            "status": self.status.value,
        }


@dataclass
class HedgeAccount:
    """对冲账户"""
    account_id: str
    total_hedge_value: float
    positions: List[HedgePosition] = field(default_factory=list)
    total_pnl: float = 0
    hedge_effectiveness: float = 0

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "total_hedge_value": round(self.total_hedge_value, 2),
            "position_count": len(self.positions),
            "total_pnl": round(self.total_pnl, 2),
            "hedge_effectiveness": round(self.hedge_effectiveness, 4),
        }


@dataclass
class HedgeResult:
    """对冲结果"""
    hedge_ratio: float
    hedge_quantity: float
    hedge_instrument: str
    estimated_cost: float
    effectiveness: float
    recommendation: str

    def to_dict(self) -> dict:
        return {
            "hedge_ratio": round(self.hedge_ratio, 4),
            "hedge_quantity": round(self.hedge_quantity, 2),
            "hedge_instrument": self.hedge_instrument,
            "estimated_cost": round(self.estimated_cost, 4),
            "effectiveness": round(self.effectiveness, 4),
            "recommendation": self.recommendation,
        }


# ============ Delta对冲器 ============

class DeltaHedger:
    """Delta对冲器"""

    def __init__(self):
        self._positions: Dict[str, HedgePosition] = {}
        self._delta_history: Dict[str, List[float]] = defaultdict(list)

    def calculate_delta(
        self,
        spot_price: float,
        strike_price: float,
        time_to_maturity: float,
        volatility: float,
        risk_free_rate: float = 0.03,
        option_type: str = "call",
    ) -> float:
        """计算Delta (Black-Scholes)"""
        if time_to_maturity <= 0 or volatility <= 0:
            return 0.5 if option_type == "call" else -0.5

        # 标准化
        d1 = self._calculate_d1(
            spot_price, strike_price, time_to_maturity, volatility, risk_free_rate
        )

        # Delta
        if option_type == "call":
            delta = self._normal_cdf(d1)
        else:
            delta = self._normal_cdf(d1) - 1

        return delta

    def _calculate_d1(
        self,
        S: float, K: float, T: float, sigma: float, r: float,
    ) -> float:
        """计算d1"""
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            return 0

        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        return d1

    def _normal_cdf(self, x: float) -> float:
        """标准正态累积分布"""
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    def calculate_hedge_ratio(
        self,
        position_delta: float,
        position_quantity: int,
        hedge_instrument_delta: float = 1.0,
    ) -> float:
        """计算对冲比率"""
        if hedge_instrument_delta == 0:
            return 0

        # 需要对冲的Delta
        total_delta = position_delta * position_quantity

        # 对冲比率
        hedge_ratio = -total_delta / hedge_instrument_delta

        return hedge_ratio

    def create_hedge(
        self,
        underlying: str,
        position_delta: float,
        position_quantity: int,
        hedge_instrument: str,
        hedge_instrument_delta: float,
        current_price: float,
    ) -> HedgePosition:
        """创建对冲"""
        hedge_ratio = self.calculate_hedge_ratio(
            position_delta, position_quantity, hedge_instrument_delta
        )

        position_id = f"hedge_{underlying}_{int(datetime.now().timestamp() * 1000)}"

        position = HedgePosition(
            position_id=position_id,
            hedge_type=HedgeType.DELTA,
            underlying=underlying,
            hedge_instrument=hedge_instrument,
            quantity=hedge_ratio,
            entry_price=current_price,
            current_price=current_price,
            hedge_ratio=hedge_ratio,
        )

        self._positions[position_id] = position
        self._delta_history[underlying].append(position_delta)

        logger.info(f"[DeltaHedger] 创建对冲: {position_id}, 比率: {hedge_ratio:.4f}")

        return position

    def rebalance(
        self,
        position_id: str,
        new_delta: float,
        current_price: float,
    ) -> float:
        """再平衡"""
        position = self._positions.get(position_id)
        if not position:
            return 0

        old_ratio = position.hedge_ratio
        new_ratio = -new_delta * position.quantity / 1.0  # 假设对冲工具delta=1

        adjustment = new_ratio - old_ratio
        position.hedge_ratio = new_ratio
        position.current_price = current_price

        return adjustment


# ============ Beta对冲器 ============

class BetaHedger:
    """Beta对冲器"""

    def __init__(self):
        self._beta_cache: Dict[str, float] = {}
        self._hedge_positions: Dict[str, HedgePosition] = {}

    def calculate_beta(
        self,
        asset_returns: List[float],
        benchmark_returns: List[float],
    ) -> float:
        """计算Beta"""
        if len(asset_returns) < 10 or len(benchmark_returns) < 10:
            return 1.0

        # 协方差和方差
        min_len = min(len(asset_returns), len(benchmark_returns))
        asset = np.array(asset_returns[:min_len])
        benchmark = np.array(benchmark_returns[:min_len])

        cov_matrix = np.cov(asset, benchmark)
        var_benchmark = np.var(benchmark)

        if var_benchmark == 0:
            return 1.0

        beta = cov_matrix[0, 1] / var_benchmark
        return beta

    def calculate_hedge_ratio(
        self,
        portfolio_beta: float,
        portfolio_value: float,
        hedge_index_beta: float,
        hedge_index_value: float,
    ) -> float:
        """计算对冲比率"""
        # 需要对冲的Beta敞口
        beta_exposure = portfolio_beta * portfolio_value

        # 对冲工具的Beta敞口
        hedge_beta_per_unit = hedge_index_beta * hedge_index_value

        if hedge_beta_per_unit == 0:
            return 0

        # 对冲比率
        hedge_ratio = -beta_exposure / hedge_beta_per_unit

        return hedge_ratio

    def create_beta_hedge(
        self,
        portfolio_beta: float,
        portfolio_value: float,
        hedge_instrument: str,
        hedge_beta: float,
        instrument_value: float,
        current_price: float,
    ) -> HedgePosition:
        """创建Beta对冲"""
        hedge_ratio = self.calculate_hedge_ratio(
            portfolio_beta, portfolio_value, hedge_beta, instrument_value
        )

        position_id = f"beta_hedge_{int(datetime.now().timestamp() * 1000)}"

        position = HedgePosition(
            position_id=position_id,
            hedge_type=HedgeType.BETA,
            underlying="portfolio",
            hedge_instrument=hedge_instrument,
            quantity=hedge_ratio,
            entry_price=current_price,
            current_price=current_price,
            hedge_ratio=hedge_ratio,
        )

        self._hedge_positions[position_id] = position

        return position


# ============ 跨品种对冲器 ============

class CrossAssetHedger:
    """跨品种对冲器"""

    def __init__(self):
        # 相关性矩阵
        self._correlation_matrix: Dict[Tuple[str, str], float] = {}

        # 对冲映射
        self._hedge_map = {
            "convertible_bond": ["stock", "index_futures"],
            "stock": ["index_futures", "options"],
            "index": ["index_futures", "etf"],
        }

        self._positions: Dict[str, HedgePosition] = {}

    def update_correlation(self, asset1: str, asset2: str, correlation: float):
        """更新相关性"""
        self._correlation_matrix[(asset1, asset2)] = correlation
        self._correlation_matrix[(asset2, asset1)] = correlation

    def get_correlation(self, asset1: str, asset2: str) -> float:
        """获取相关性"""
        return self._correlation_matrix.get((asset1, asset2), 0)

    def find_best_hedge(
        self,
        underlying: str,
        exposure_value: float,
        available_instruments: List[str],
    ) -> HedgeResult:
        """寻找最佳对冲工具"""
        best_instrument = None
        best_correlation = 0
        best_ratio = 0

        for instrument in available_instruments:
            corr = abs(self.get_correlation(underlying, instrument))

            if corr > best_correlation:
                best_correlation = corr
                best_instrument = instrument
                # 对冲比率 = 相关性 * 敞口 / 工具价值
                best_ratio = corr * exposure_value / 1000000  # 假设工具价值100万

        effectiveness = best_correlation ** 2  # R²作为有效性度量

        return HedgeResult(
            hedge_ratio=best_ratio,
            hedge_quantity=best_ratio,
            hedge_instrument=best_instrument or "N/A",
            estimated_cost=best_ratio * 0.0003,  # 假设0.03%成本
            effectiveness=effectiveness,
            recommendation=f"使用{best_instrument}对冲{underlying}敞口" if best_instrument else "未找到合适对冲工具",
        )

    def create_cross_hedge(
        self,
        underlying: str,
        exposure_value: float,
        hedge_instrument: str,
        correlation: float,
        current_price: float,
    ) -> HedgePosition:
        """创建跨品种对冲"""
        hedge_ratio = correlation * exposure_value / current_price

        position_id = f"cross_hedge_{int(datetime.now().timestamp() * 1000)}"

        position = HedgePosition(
            position_id=position_id,
            hedge_type=HedgeType.CROSS_ASSET,
            underlying=underlying,
            hedge_instrument=hedge_instrument,
            quantity=hedge_ratio,
            entry_price=current_price,
            current_price=current_price,
            hedge_ratio=hedge_ratio,
        )

        self._positions[position_id] = position

        return position


# ============ 成本优化对冲器 ============

class CostOptimizedHedger:
    """成本优化对冲器"""

    def __init__(self):
        self._cost_threshold = 0.001  # 成本阈值
        self._rebalance_threshold = 0.1  # 再平衡阈值

    def optimize_hedge_timing(
        self,
        current_hedge_ratio: float,
        target_hedge_ratio: float,
        current_price: float,
        volatility: float,
        time_to_expiry: float,
    ) -> Dict[str, Any]:
        """优化对冲时机"""
        ratio_diff = abs(target_hedge_ratio - current_hedge_ratio)

        # 再平衡成本
        transaction_cost = ratio_diff * current_price * 0.0003

        # 不对冲的风险成本
        unhedged_risk = volatility * math.sqrt(time_to_expiry) * ratio_diff * current_price

        # 是否应该再平衡
        should_rebalance = ratio_diff > self._rebalance_threshold or transaction_cost < unhedged_risk * 0.5

        # 最优再平衡时机
        if should_rebalance:
            timing = "immediate"
            reason = "偏离超过阈值或风险成本高于交易成本"
        else:
            timing = "wait"
            reason = "等待更好的再平衡时机"

        return {
            "should_rebalance": should_rebalance,
            "timing": timing,
            "reason": reason,
            "ratio_diff": round(ratio_diff, 4),
            "transaction_cost": round(transaction_cost, 4),
            "unhedged_risk": round(unhedged_risk, 4),
            "cost_saving": round(unhedged_risk - transaction_cost, 4),
        }

    def minimize_hedge_cost(
        self,
        hedge_requirement: float,
        available_instruments: List[Dict],
    ) -> Dict[str, Any]:
        """最小化对冲成本"""
        # 按成本排序
        sorted_instruments = sorted(
            available_instruments,
            key=lambda x: x.get("cost", float('inf'))
        )

        remaining = hedge_requirement
        allocations = []

        for instrument in sorted_instruments:
            if remaining <= 0:
                break

            available = instrument.get("available_quantity", 0)
            cost = instrument.get("cost", 0)

            allocated = min(remaining, available)
            allocations.append({
                "instrument": instrument.get("name"),
                "quantity": allocated,
                "cost": allocated * cost,
            })

            remaining -= allocated

        total_cost = sum(a["cost"] for a in allocations)
        hedge_coverage = (hedge_requirement - remaining) / hedge_requirement if hedge_requirement > 0 else 0

        return {
            "allocations": allocations,
            "total_cost": round(total_cost, 4),
            "hedge_coverage": round(hedge_coverage, 4),
            "unhedged": remaining,
        }


# ============ 智能对冲服务 ============

class SmartHedgeService:
    """智能对冲服务"""

    def __init__(self):
        self.delta_hedger = DeltaHedger()
        self.beta_hedger = BetaHedger()
        self.cross_hedger = CrossAssetHedger()
        self.cost_hedger = CostOptimizedHedger()

        self._accounts: Dict[str, HedgeAccount] = {}

    def create_account(self, account_id: str) -> HedgeAccount:
        """创建对冲账户"""
        account = HedgeAccount(
            account_id=account_id,
            total_hedge_value=0,
        )
        self._accounts[account_id] = account
        return account

    def hedge_position(
        self,
        account_id: str,
        position: Dict,
        hedge_type: HedgeType = HedgeType.DELTA,
    ) -> HedgePosition:
        """对冲持仓"""
        account = self._accounts.get(account_id)
        if not account:
            return None

        if hedge_type == HedgeType.DELTA:
            hedge = self.delta_hedger.create_hedge(
                underlying=position.get("code"),
                position_delta=position.get("delta", 0.5),
                position_quantity=position.get("quantity", 0),
                hedge_instrument=position.get("hedge_instrument", "index"),
                hedge_instrument_delta=1.0,
                current_price=position.get("price", 0),
            )
        elif hedge_type == HedgeType.BETA:
            hedge = self.beta_hedger.create_beta_hedge(
                portfolio_beta=position.get("beta", 1.0),
                portfolio_value=position.get("value", 0),
                hedge_instrument=position.get("hedge_instrument", "index_futures"),
                hedge_beta=1.0,
                instrument_value=position.get("instrument_value", 1000000),
                current_price=position.get("price", 0),
            )
        else:
            hedge = self.cross_hedger.create_cross_hedge(
                underlying=position.get("code"),
                exposure_value=position.get("value", 0),
                hedge_instrument=position.get("hedge_instrument"),
                correlation=position.get("correlation", 0.8),
                current_price=position.get("price", 0),
            )

        account.positions.append(hedge)
        account.total_hedge_value += abs(hedge.quantity * hedge.entry_price)

        return hedge

    def get_hedge_status(self, account_id: str) -> Dict:
        """获取对冲状态"""
        account = self._accounts.get(account_id)
        if not account:
            return {}

        total_pnl = sum(p.pnl for p in account.positions)
        account.total_pnl = total_pnl

        return {
            "account": account.to_dict(),
            "positions": [p.to_dict() for p in account.positions],
        }

    def calculate_hedge_effectiveness(
        self,
        account_id: str,
        underlying_returns: List[float],
        hedge_returns: List[float],
    ) -> float:
        """计算对冲有效性"""
        if not underlying_returns or not hedge_returns:
            return 0

        min_len = min(len(underlying_returns), len(hedge_returns))
        underlying = np.array(underlying_returns[:min_len])
        hedge = np.array(hedge_returns[:min_len])

        # 对冲后收益
        hedged_returns = underlying + hedge

        # 有效性 = 1 - Var(hedged) / Var(underlying)
        var_underlying = np.var(underlying)
        var_hedged = np.var(hedged_returns)

        effectiveness = 1 - var_hedged / var_underlying if var_underlying > 0 else 0

        account = self._accounts.get(account_id)
        if account:
            account.hedge_effectiveness = effectiveness

        return effectiveness


# ============ 便捷函数 ============

def create_hedge_service() -> SmartHedgeService:
    """创建对冲服务"""
    return SmartHedgeService()


def calculate_delta(
    spot_price: float,
    strike_price: float,
    time_to_maturity: float,
    volatility: float,
    option_type: str = "call",
) -> float:
    """计算Delta"""
    hedger = DeltaHedger()
    return hedger.calculate_delta(spot_price, strike_price, time_to_maturity, volatility, 0.03, option_type)


def calculate_hedge_ratio(
    position_delta: float,
    position_quantity: int,
) -> float:
    """计算对冲比率"""
    hedger = DeltaHedger()
    return hedger.calculate_hedge_ratio(position_delta, position_quantity)
