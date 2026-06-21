"""西部量化可转债策略 V3.0 动态对冲策略

对冲启动条件(三项同时满足):
- 多维度择时得分 < 30分
- 转债组合与沪深300 60日滚动相关性 > 0.65
- 中证转债指数 20日均线跌破且斜率向下

动态对冲比率:
- 相关性 > 0.75: 股指期货40% + 认沽期权25% + 纯债性转债25%
- 相关性 0.65-0.75: 股指期货25% + 认沽期权20% + 纯债性转债30%
- 相关性 < 0.65: 不启动股指期货，认沽期权15% + 纯债性转债40%
"""
from dataclasses import dataclass
from datetime import date
from typing import List, Dict, Optional, Tuple
import logging

from app.xb_strategy.core.types import HedgeStatus, Portfolio, Position, TimingSignal
from app.xb_strategy.config.settings import params

logger = logging.getLogger(__name__)


@dataclass
class CorrelationState:
    """相关性状态"""
    date: date
    portfolio_return: float  # 组合收益率
    index_return: float  # 指数收益率
    correlation_60d: float  # 60日滚动相关性
    correlation_20d: float  # 20日滚动相关性


class HedgeEngine:
    """动态对冲引擎"""

    def __init__(self, aum: float = 10000.0):
        """初始化

        Args:
            aum: 资产规模(万元)
        """
        self.aum = aum
        self._status = HedgeStatus()
        self._correlation_history: List[CorrelationState] = []
        self._hedge_active = False
        self._hedge_start_date: Optional[date] = None

    def calculate_correlation(
        self,
        portfolio_returns: List[float],
        index_returns: List[float],
        window: int = 60,
    ) -> float:
        """计算滚动相关性

        Args:
            portfolio_returns: 组合收益率列表
            index_returns: 指数收益率列表
            window: 计算窗口

        Returns:
            相关系数
        """
        if len(portfolio_returns) < window or len(index_returns) < window:
            return 0.0

        import numpy as np
        p = np.array(portfolio_returns[-window:])
        i = np.array(index_returns[-window:])

        if np.std(p) == 0 or np.std(i) == 0:
            return 0.0

        return float(np.corrcoef(p, i)[0, 1])

    def check_hedge_conditions(
        self,
        timing_signal: TimingSignal,
        correlation: float,
        index_ma20: float,
        index_current: float,
        index_ma_slope: float,
    ) -> Tuple[bool, str]:
        """检查对冲启动条件

        Args:
            timing_signal: 择时信号
            correlation: 相关性
            index_ma20: 指数20日均线
            index_current: 指数当前值
            index_ma_slope: 均线斜率

        Returns:
            (是否启动, 原因)
        """
        conditions_met = []
        reasons = []

        # 条件1: 择时得分 < 30
        if timing_signal.total_score < params.hedge_timing_threshold:
            conditions_met.append(True)
            reasons.append(f"择时得分{timing_signal.total_score:.1f}<{params.hedge_timing_threshold}")
        else:
            conditions_met.append(False)

        # 条件2: 相关性 > 0.65
        if correlation > params.hedge_correlation_threshold:
            conditions_met.append(True)
            reasons.append(f"相关性{correlation:.2f}>{params.hedge_correlation_threshold}")
        else:
            conditions_met.append(False)

        # 条件3: 跌破20日均线且斜率向下
        if index_current < index_ma20 and index_ma_slope < 0:
            conditions_met.append(True)
            reasons.append("指数跌破20日均线且斜率向下")
        else:
            conditions_met.append(False)

        # 三项同时满足
        all_met = all(conditions_met)

        return all_met, " | ".join(reasons) if all_met else "不满足对冲条件"

    def determine_hedge_ratio(
        self,
        correlation: float,
    ) -> Tuple[float, float, float]:
        """确定对冲比率

        Args:
            correlation: 相关系数

        Returns:
            (股指期货比例, 认沽期权比例, 纯债性转债比例)
        """
        if correlation > 0.75:
            return (
                params.hedge_csi300_ratio_high,
                params.hedge_put_ratio_high,
                params.hedge_pure_bond_high,
            )
        elif correlation >= 0.65:
            return (
                params.hedge_csi300_ratio_mid,
                params.hedge_put_ratio_mid,
                params.hedge_pure_bond_mid,
            )
        else:
            # 相关性过低，不使用股指期货
            return (
                0.0,
                0.15,
                params.hedge_pure_bond_low,
            )

    def activate_hedge(
        self,
        correlation: float,
        current_date: date,
    ) -> HedgeStatus:
        """启动对冲

        Args:
            correlation: 相关系数
            current_date: 当前日期

        Returns:
            HedgeStatus: 对冲状态
        """
        csi300_ratio, put_ratio, pure_bond_ratio = self.determine_hedge_ratio(correlation)

        self._status = HedgeStatus(
            active=True,
            correlation=correlation,
            csi300_hedge_ratio=csi300_ratio,
            put_hedge_ratio=put_ratio,
            pure_bond_ratio=pure_bond_ratio,
        )
        self._hedge_active = True
        self._hedge_start_date = current_date

        logger.info(
            f"[Hedge] 启动对冲: 相关性{correlation:.2f}, "
            f"股指期货{csi300_ratio*100:.0f}%, "
            f"认沽期权{put_ratio*100:.0f}%, "
            f"纯债性转债{pure_bond_ratio*100:.0f}%"
        )

        return self._status

    def deactivate_hedge(self) -> HedgeStatus:
        """关闭对冲"""
        self._status = HedgeStatus()
        self._hedge_active = False
        self._hedge_start_date = None

        logger.info("[Hedge] 关闭对冲")
        return self._status

    def calculate_hedge_cost(
        self,
        days: int = 30,
    ) -> Dict[str, float]:
        """计算对冲成本

        Args:
            days: 计算天数

        Returns:
            成本详情
        """
        aum_yuan = self.aum * 10000

        # 期货成本(年化)
        futures_cost = aum_yuan * self._status.csi300_hedge_ratio * params.futures_cost_annual * days / 365

        # 期权成本(年化)
        put_cost = aum_yuan * self._status.put_hedge_ratio * params.put_cost_annual * days / 365

        # 纯债性转债机会成本(假设放弃2%的权益弹性)
        pure_bond_cost = aum_yuan * self._status.pure_bond_ratio * 0.02 * days / 365

        total_cost = futures_cost + put_cost + pure_bond_cost

        return {
            "futures_cost": round(futures_cost, 2),
            "put_cost": round(put_cost, 2),
            "pure_bond_cost": round(pure_bond_cost, 2),
            "total_cost": round(total_cost, 2),
            "daily_cost": round(total_cost / days, 2),
        }

    def select_pure_bond_cbs(
        self,
        positions: Dict[str, Position],
        cb_data: Dict[str, dict],
        target_ratio: float,
    ) -> List[str]:
        """选择纯债性转债

        Args:
            positions: 持仓
            cb_data: 转债数据
            target_ratio: 目标比例

        Returns:
            选中的转债代码列表
        """
        # 筛选条件: 高YTM、低溢价率、高评级
        pure_bond_candidates = []

        for code, pos in positions.items():
            cb = cb_data.get(code)
            if not cb:
                continue

            # 纯债性评分
            ytm = cb.get("ytm", 0)
            premium = cb.get("conversion_premium", 0)
            rating = cb.get("issuer_rating", "")

            # 高YTM(>3%)、低溢价(<20%)、高评级(AA及以上)
            score = 0
            if ytm > 3:
                score += 40
            if premium < 20:
                score += 30
            if rating in ["AAA", "AA+", "AA"]:
                score += 30

            if score >= 50:
                pure_bond_candidates.append((code, score))

        # 按评分排序
        pure_bond_candidates.sort(key=lambda x: x[1], reverse=True)

        # 计算需要多少持仓达到目标比例
        aum_yuan = self.aum * 10000
        target_value = aum_yuan * target_ratio

        selected = []
        current_value = 0

        for code, _ in pure_bond_candidates:
            pos = positions.get(code)
            if pos:
                selected.append(code)
                current_value += pos.market_value
                if current_value >= target_value:
                    break

        return selected

    def update(
        self,
        timing_signal: TimingSignal,
        portfolio_returns: List[float],
        index_returns: List[float],
        index_ma20: float,
        index_current: float,
        index_ma_slope: float,
        current_date: date,
    ) -> HedgeStatus:
        """更新对冲状态

        Args:
            timing_signal: 择时信号
            portfolio_returns: 组合收益率历史
            index_returns: 指数收益率历史
            index_ma20: 指数20日均线
            index_current: 指数当前值
            index_ma_slope: 均线斜率
            current_date: 当前日期

        Returns:
            HedgeStatus: 对冲状态
        """
        # 计算相关性
        correlation = self.calculate_correlation(portfolio_returns, index_returns)
        self._status.correlation = correlation

        # 记录相关性历史
        if portfolio_returns and index_returns:
            self._correlation_history.append(CorrelationState(
                date=current_date,
                portfolio_return=portfolio_returns[-1] if portfolio_returns else 0,
                index_return=index_returns[-1] if index_returns else 0,
                correlation_60d=correlation,
                correlation_20d=self.calculate_correlation(portfolio_returns, index_returns, 20),
            ))

        # 检查对冲条件
        should_hedge, reason = self.check_hedge_conditions(
            timing_signal, correlation, index_ma20, index_current, index_ma_slope
        )

        if should_hedge and not self._hedge_active:
            return self.activate_hedge(correlation, current_date)
        elif not should_hedge and self._hedge_active:
            return self.deactivate_hedge()
        elif self._hedge_active:
            # 更新对冲比率
            csi300_ratio, put_ratio, pure_bond_ratio = self.determine_hedge_ratio(correlation)
            self._status.csi300_hedge_ratio = csi300_ratio
            self._status.put_hedge_ratio = put_ratio
            self._status.pure_bond_ratio = pure_bond_ratio

        return self._status

    def get_status(self) -> HedgeStatus:
        """获取当前对冲状态"""
        return self._status

    def get_hedge_report(self) -> dict:
        """获取对冲报告"""
        return {
            "active": self._status.active,
            "correlation": round(self._status.correlation, 3),
            "csi300_hedge_ratio": round(self._status.csi300_hedge_ratio, 3),
            "put_hedge_ratio": round(self._status.put_hedge_ratio, 3),
            "pure_bond_ratio": round(self._status.pure_bond_ratio, 3),
            "hedge_start_date": self._hedge_start_date.isoformat() if self._hedge_start_date else None,
            "monthly_cost": self.calculate_hedge_cost(30),
        }
