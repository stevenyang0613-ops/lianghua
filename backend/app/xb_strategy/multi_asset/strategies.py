"""西部量化可转债策略 V3.0 多资产扩展模块

功能:
- ETF策略支持
- 期权策略支持
- 期货策略支持
- 跨资产套利
- 资产配置
"""
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Dict, Optional, Any, Callable
from enum import Enum
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class AssetType(str, Enum):
    """资产类型"""
    CONVERTIBLE_BOND = "convertible_bond"
    ETF = "etf"
    STOCK = "stock"
    OPTION = "option"
    FUTURE = "future"
    BOND = "bond"
    FUND = "fund"


class OptionType(str, Enum):
    """期权类型"""
    CALL = "call"
    PUT = "put"


class FutureDirection(str, Enum):
    """期货方向"""
    LONG = "long"
    SHORT = "short"


# ============ 数据模型 ============

@dataclass
class AssetInfo:
    """资产信息"""
    code: str
    name: str
    asset_type: AssetType
    exchange: str
    currency: str = "CNY"
    lot_size: int = 1
    tick_size: float = 0.01
    margin_rate: float = 1.0

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "asset_type": self.asset_type.value,
            "exchange": self.exchange,
            "currency": self.currency,
            "lot_size": self.lot_size,
            "tick_size": self.tick_size,
        }


@dataclass
class ETFData:
    """ETF数据"""
    code: str
    name: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float
    nav: float = 0.0           # 净值
    premium: float = 0.0        # 溢价率
    tracking_error: float = 0.0  # 跟踪误差
    underlying_index: str = ""

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "date": self.date.isoformat(),
            "close": self.close,
            "volume": self.volume,
            "nav": self.nav,
            "premium": self.premium,
        }


@dataclass
class OptionData:
    """期权数据"""
    code: str
    name: str
    date: date
    underlying: str             # 标的
    strike: float               # 行权价
    expiry: date                # 到期日
    option_type: OptionType
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float
    open_interest: int = 0      # 持仓量
    iv: float = 0.0             # 隐含波动率
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "underlying": self.underlying,
            "strike": self.strike,
            "expiry": self.expiry.isoformat(),
            "option_type": self.option_type.value,
            "close": self.close,
            "iv": self.iv,
        }


@dataclass
class FutureData:
    """期货数据"""
    code: str
    name: str
    date: date
    underlying: str
    expiry: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float
    open_interest: int = 0
    basis: float = 0.0          # 基差
    settlement_price: float = 0.0

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "underlying": self.underlying,
            "expiry": self.expiry.isoformat(),
            "close": self.close,
            "basis": self.basis,
        }


# ============ ETF策略 ============

class ETFStrategy:
    """ETF策略"""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self._positions: Dict[str, int] = {}

    def score_etf(self, etf_data: ETFData) -> float:
        """ETF打分"""
        score = 50.0

        # 溢价率因子
        if etf_data.premium < -0.02:
            score += 10  # 折价加分
        elif etf_data.premium > 0.05:
            score -= 10  # 高溢价减分

        # 跟踪误差因子
        if etf_data.tracking_error < 0.01:
            score += 5

        # 流动性因子
        if etf_data.amount > 100000000:  # 成交额超过1亿
            score += 5

        return max(0, min(100, score))

    def generate_signals(
        self,
        etf_list: List[ETFData],
        top_n: int = 10,
    ) -> List[Dict]:
        """生成信号"""
        # 打分
        scored = [(etf, self.score_etf(etf)) for etf in etf_list]
        scored.sort(key=lambda x: x[1], reverse=True)

        signals = []
        for etf, score in scored[:top_n]:
            if score >= 60:
                signals.append({
                    "code": etf.code,
                    "name": etf.name,
                    "action": "buy",
                    "score": score,
                    "reason": f"ETF综合得分: {score:.1f}",
                })

        return signals


# ============ 期权策略 ============

class OptionStrategy:
    """期权策略"""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self._risk_free_rate = 0.03

    def calculate_greeks(self, option: OptionData, spot: float, time_to_expiry: float) -> Dict:
        """计算Greeks"""
        from scipy.stats import norm

        S = spot
        K = option.strike
        T = time_to_expiry
        r = self._risk_free_rate
        sigma = option.iv

        if T <= 0:
            return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0}

        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)

        if option.option_type == OptionType.CALL:
            delta = norm.cdf(d1)
        else:
            delta = norm.cdf(d1) - 1

        gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
        theta = -(S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T))
        vega = S * norm.pdf(d1) * np.sqrt(T)

        return {
            "delta": delta,
            "gamma": gamma,
            "theta": theta / 365,  # 日化
            "vega": vega / 100,     # 1%波动率变化
        }

    def find_arbitrage(
        self,
        call: OptionData,
        put: OptionData,
        spot: float,
        risk_free_rate: float = 0.03,
    ) -> Optional[Dict]:
        """期权套利机会"""
        # 期权平价公式: C + K*e^(-rT) = P + S
        T = (call.expiry - date.today()).days / 365

        if T <= 0:
            return None

        left = call.close + call.strike * np.exp(-risk_free_rate * T)
        right = put.close + spot

        diff = left - right

        # 套利阈值
        threshold = spot * 0.005  # 0.5%

        if abs(diff) > threshold:
            return {
                "call_code": call.code,
                "put_code": put.code,
                "spot": spot,
                "parity_diff": diff,
                "parity_diff_pct": diff / spot,
                "signal": "sell_call_buy_put" if diff > 0 else "buy_call_sell_put",
            }

        return None

    def covered_call(
        self,
        stock_position: int,
        call: OptionData,
        target_return: float = 0.03,
    ) -> Dict:
        """备兑看涨期权策略"""
        # 计算年化收益
        T = (call.expiry - date.today()).days / 365

        if T <= 0 or stock_position <= 0:
            return {}

        premium_return = call.close * 100 / (call.strike * stock_position)
        annualized_return = premium_return / T if T > 0 else 0

        return {
            "strategy": "covered_call",
            "stock_position": stock_position,
            "call_code": call.code,
            "premium": call.close,
            "strike": call.strike,
            "expiry": call.expiry.isoformat(),
            "premium_return": premium_return,
            "annualized_return": annualized_return,
            "recommend": annualized_return > target_return,
        }


# ============ 期货策略 ============

class FutureStrategy:
    """期货策略"""

    def __init__(self, config: Dict = None):
        self.config = config or {}

    def basis_trading(
        self,
        future: FutureData,
        spot_price: float,
        threshold: float = 0.02,
    ) -> Optional[Dict]:
        """基差交易"""
        basis_rate = future.basis / spot_price

        if abs(basis_rate) > threshold:
            return {
                "future_code": future.code,
                "spot_price": spot_price,
                "future_price": future.close,
                "basis": future.basis,
                "basis_rate": basis_rate,
                "signal": "long_basis" if basis_rate < 0 else "short_basis",
            }

        return None

    def calendar_spread(
        self,
        near_month: FutureData,
        far_month: FutureData,
        spread_threshold: float = 0.01,
    ) -> Optional[Dict]:
        """跨期套利"""
        spread = near_month.close - far_month.close
        spread_rate = spread / near_month.close

        if abs(spread_rate) > spread_threshold:
            return {
                "near_code": near_month.code,
                "far_code": far_month.code,
                "near_price": near_month.close,
                "far_price": far_month.close,
                "spread": spread,
                "spread_rate": spread_rate,
                "signal": "buy_near_sell_far" if spread_rate < -spread_threshold else "sell_near_buy_far",
            }

        return None

    def trend_following(
        self,
        prices: List[float],
        window: int = 20,
    ) -> str:
        """趋势跟踪"""
        if len(prices) < window:
            return "hold"

        ma = np.mean(prices[-window:])
        current = prices[-1]

        if current > ma * 1.02:
            return "long"
        elif current < ma * 0.98:
            return "short"
        else:
            return "hold"


# ============ 多资产组合 ============

class MultiAssetPortfolio:
    """多资产组合"""

    def __init__(self):
        self._positions: Dict[AssetType, Dict[str, Any]] = {}
        self._allocations: Dict[AssetType, float] = {}

    def set_allocation(self, asset_type: AssetType, weight: float):
        """设置配置权重"""
        self._allocations[asset_type] = weight

    def add_position(
        self,
        asset_type: AssetType,
        code: str,
        quantity: int,
        price: float,
    ):
        """添加持仓"""
        if asset_type not in self._positions:
            self._positions[asset_type] = {}

        self._positions[asset_type][code] = {
            "quantity": quantity,
            "price": price,
            "market_value": quantity * price,
        }

    def get_total_value(self) -> float:
        """获取总市值"""
        total = 0.0
        for asset_positions in self._positions.values():
            for pos in asset_positions.values():
                total += pos["market_value"]
        return total

    def get_allocation(self) -> Dict[AssetType, float]:
        """获取当前配置"""
        total = self.get_total_value()
        if total == 0:
            return {}

        allocation = {}
        for asset_type, positions in self._positions.items():
            type_value = sum(p["market_value"] for p in positions.values())
            allocation[asset_type] = type_value / total

        return allocation

    def rebalance(
        self,
        target_allocations: Dict[AssetType, float],
    ) -> List[Dict]:
        """再平衡"""
        current_alloc = self.get_allocation()
        total_value = self.get_total_value()

        trades = []

        for asset_type, target_weight in target_allocations.items():
            current_weight = current_alloc.get(asset_type, 0)
            diff = target_weight - current_weight

            if abs(diff) > 0.01:  # 1%阈值
                trades.append({
                    "asset_type": asset_type.value,
                    "action": "buy" if diff > 0 else "sell",
                    "current_weight": current_weight,
                    "target_weight": target_weight,
                    "adjust_amount": abs(diff) * total_value,
                })

        return trades

    def get_risk_metrics(self) -> Dict[str, float]:
        """获取风险指标"""
        allocation = self.get_allocation()

        # 集中度
        max_allocation = max(allocation.values()) if allocation else 0

        # 分散度
        n_assets = len([v for v in allocation.values() if v > 0.01])
        diversification = min(1.0, n_assets / 5)  # 5种资产为满分

        return {
            "max_concentration": max_allocation,
            "diversification_score": diversification,
            "n_asset_types": n_assets,
        }


# ============ 跨资产套利 ============

class CrossAssetArbitrage:
    """跨资产套利"""

    def __init__(self):
        self._opportunities: List[Dict] = []

    def find_cb_stock_arbitrage(
        self,
        cb_data: Dict,
        stock_data: Dict,
        conversion_ratio: float,
        threshold: float = 0.02,
    ) -> Optional[Dict]:
        """转债-正股套利"""
        cb_price = cb_data.get("close", 0)
        stock_price = stock_data.get("close", 0)

        # 转股价值
        conversion_value = stock_price * conversion_ratio

        # 套利空间
        arb_spread = (conversion_value - cb_price) / cb_price

        if arb_spread > threshold:
            return {
                "type": "cb_stock",
                "cb_code": cb_data.get("code"),
                "stock_code": stock_data.get("code"),
                "cb_price": cb_price,
                "stock_price": stock_price,
                "conversion_value": conversion_value,
                "arb_spread": arb_spread,
                "signal": "buy_cb_convert_stock",
            }

        return None

    def find_etf_basket_arbitrage(
        self,
        etf_price: float,
        basket_value: float,
        threshold: float = 0.01,
    ) -> Optional[Dict]:
        """ETF-一篮子股票套利"""
        spread = (etf_price - basket_value) / basket_value

        if abs(spread) > threshold:
            return {
                "type": "etf_basket",
                "etf_price": etf_price,
                "basket_value": basket_value,
                "spread": spread,
                "signal": "buy_etf_sell_basket" if spread < 0 else "sell_etf_buy_basket",
            }

        return None

    def scan_opportunities(
        self,
        cb_list: List[Dict],
        stock_list: List[Dict],
        etf_list: List[Dict],
    ) -> List[Dict]:
        """扫描套利机会"""
        opportunities = []

        # 转债-正股套利
        for cb in cb_list:
            stock_code = cb.get("stock_code")
            stock = next((s for s in stock_list if s.get("code") == stock_code), None)
            if stock:
                arb = self.find_cb_stock_arbitrage(
                    cb, stock,
                    cb.get("conversion_ratio", 1),
                )
                if arb:
                    opportunities.append(arb)

        self._opportunities = opportunities
        return opportunities


# ============ 便捷函数 ============

def get_etf_strategy(config: Dict = None) -> ETFStrategy:
    """获取ETF策略"""
    return ETFStrategy(config)


def get_option_strategy(config: Dict = None) -> OptionStrategy:
    """获取期权策略"""
    return OptionStrategy(config)


def get_future_strategy(config: Dict = None) -> FutureStrategy:
    """获取期货策略"""
    return FutureStrategy(config)


def get_multi_asset_portfolio() -> MultiAssetPortfolio:
    """获取多资产组合"""
    return MultiAssetPortfolio()


def get_cross_asset_arbitrage() -> CrossAssetArbitrage:
    """获取跨资产套利"""
    return CrossAssetArbitrage()
