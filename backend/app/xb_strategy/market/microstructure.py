"""西部量化可转债策略 V3.0 市场微观结构模块

功能:
- 订单簿分析
- 成交分布
- 买卖压力
- 流动性深度
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, Tuple
from enum import Enum
import logging
import math
from collections import deque, defaultdict

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class OrderSide(str, Enum):
    """订单方向"""
    BID = "bid"  # 买
    ASK = "ask"  # 卖


class TradeDirection(str, Enum):
    """成交方向"""
    BUYER_INITIATED = "buyer"   # 买方发起
    SELLER_INITIATED = "seller" # 卖方发起
    CROSS = "cross"             # 交叉


class LiquidityLevel(str, Enum):
    """流动性水平"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    ILLIQUID = "illiquid"


class MarketPressure(str, Enum):
    """市场压力"""
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    NEUTRAL = "neutral"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


# ============ 数据模型 ============

@dataclass
class OrderBookLevel:
    """订单簿层级"""
    price: float
    quantity: int
    order_count: int = 1

    def to_dict(self) -> dict:
        return {
            "price": self.price,
            "quantity": self.quantity,
            "order_count": self.order_count,
        }


@dataclass
class OrderBook:
    """订单簿"""
    code: str
    timestamp: datetime
    bids: List[OrderBookLevel]  # 降序排列
    asks: List[OrderBookLevel]  # 升序排列

    def get_best_bid(self) -> Optional[OrderBookLevel]:
        """获取最优买价"""
        return self.bids[0] if self.bids else None

    def get_best_ask(self) -> Optional[OrderBookLevel]:
        """获取最优卖价"""
        return self.asks[0] if self.asks else None

    def get_spread(self) -> float:
        """获取价差"""
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()

        if best_bid and best_ask:
            return best_ask.price - best_bid.price
        return 0

    def get_mid_price(self) -> float:
        """获取中间价"""
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()

        if best_bid and best_ask:
            return (best_bid.price + best_ask.price) / 2
        return 0

    def get_depth(self, levels: int = 5) -> Tuple[int, int]:
        """获取深度 (买单量, 卖单量)"""
        bid_volume = sum(level.quantity for level in self.bids[:levels])
        ask_volume = sum(level.quantity for level in self.asks[:levels])
        return bid_volume, ask_volume

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "timestamp": self.timestamp.isoformat(),
            "bids": [l.to_dict() for l in self.bids[:10]],
            "asks": [l.to_dict() for l in self.asks[:10]],
            "spread": round(self.get_spread(), 4),
            "mid_price": round(self.get_mid_price(), 4),
        }


@dataclass
class Trade:
    """成交"""
    trade_id: str
    code: str
    price: float
    quantity: int
    timestamp: datetime
    direction: TradeDirection
    aggressor: OrderSide = None

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "code": self.code,
            "price": self.price,
            "quantity": self.quantity,
            "timestamp": self.timestamp.isoformat(),
            "direction": self.direction.value,
        }


@dataclass
class LiquidityMetrics:
    """流动性指标"""
    code: str
    timestamp: datetime
    spread_bps: float
    depth: float
    imbalance: float
    effective_spread: float
    realized_spread: float
    price_impact: float
    resilience: float
    level: LiquidityLevel

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "timestamp": self.timestamp.isoformat(),
            "spread_bps": round(self.spread_bps, 2),
            "depth": round(self.depth, 2),
            "imbalance": round(self.imbalance, 4),
            "effective_spread": round(self.effective_spread, 6),
            "price_impact": round(self.price_impact, 6),
            "level": self.level.value,
        }


@dataclass
class PressureAnalysis:
    """压力分析"""
    code: str
    timestamp: datetime
    pressure: MarketPressure
    buy_pressure: float
    sell_pressure: float
    net_pressure: float
    volume_ratio: float
    trade_count_ratio: float

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "timestamp": self.timestamp.isoformat(),
            "pressure": self.pressure.value,
            "buy_pressure": round(self.buy_pressure, 4),
            "sell_pressure": round(self.sell_pressure, 4),
            "net_pressure": round(self.net_pressure, 4),
            "volume_ratio": round(self.volume_ratio, 4),
        }


# ============ 订单簿分析器 ============

class OrderBookAnalyzer:
    """订单簿分析器"""

    def __init__(self, history_size: int = 100):
        self.history_size = history_size
        self._order_books: Dict[str, deque] = defaultdict(lambda: deque(maxlen=history_size))

    def update(self, order_book: OrderBook):
        """更新订单簿"""
        self._order_books[order_book.code].append(order_book)

    def get_current(self, code: str) -> Optional[OrderBook]:
        """获取当前订单簿"""
        history = self._order_books.get(code)
        if history:
            return history[-1]
        return None

    def analyze_imbalance(self, code: str, levels: int = 5) -> float:
        """分析订单簿不平衡"""
        ob = self.get_current(code)
        if not ob:
            return 0

        bid_volume, ask_volume = ob.get_depth(levels)
        total = bid_volume + ask_volume

        if total == 0:
            return 0

        return (bid_volume - ask_volume) / total

    def analyze_depth(self, code: str, levels: int = 5) -> Dict:
        """分析深度"""
        ob = self.get_current(code)
        if not ob:
            return {}

        bid_volume, ask_volume = ob.get_depth(levels)

        return {
            "bid_depth": bid_volume,
            "ask_depth": ask_volume,
            "total_depth": bid_volume + ask_volume,
            "imbalance": self.analyze_imbalance(code, levels),
        }

    def calculate_price_impact(
        self,
        code: str,
        quantity: int,
        side: OrderSide,
    ) -> float:
        """计算价格冲击"""
        ob = self.get_current(code)
        if not ob:
            return 0

        mid_price = ob.get_mid_price()
        if mid_price == 0:
            return 0

        remaining = quantity
        total_cost = 0

        # 模拟吃单
        if side == OrderSide.BID:  # 买入, 吃卖单
            for level in ob.asks:
                if remaining <= 0:
                    break
                fill = min(remaining, level.quantity)
                total_cost += fill * level.price
                remaining -= fill
        else:  # 卖出, 吃买单
            for level in ob.bids:
                if remaining <= 0:
                    break
                fill = min(remaining, level.quantity)
                total_cost += fill * level.price
                remaining -= fill

        if quantity - remaining == 0:
            return 0

        avg_price = total_cost / (quantity - remaining)
        impact = abs(avg_price - mid_price) / mid_price

        return impact

    def detect_support_resistance(self, code: str) -> Dict:
        """检测支撑阻力"""
        ob = self.get_current(code)
        if not ob:
            return {}

        # 找大单
        large_bid_orders = [
            level for level in ob.bids[:10]
            if level.quantity > ob.bids[0].quantity * 2
        ]
        large_ask_orders = [
            level for level in ob.asks[:10]
            if level.quantity > ob.asks[0].quantity * 2
        ]

        return {
            "support_levels": [l.price for l in large_bid_orders],
            "resistance_levels": [l.price for l in large_ask_orders],
            "strongest_support": max(large_bid_orders, key=lambda x: x.quantity).price if large_bid_orders else None,
            "strongest_resistance": max(large_ask_orders, key=lambda x: x.quantity).price if large_ask_orders else None,
        }


# ============ 成交分布分析器 ============

class TradeDistributionAnalyzer:
    """成交分布分析器"""

    def __init__(self, window_size: int = 1000):
        self.window_size = window_size
        self._trades: Dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))

    def add_trade(self, trade: Trade):
        """添加成交"""
        self._trades[trade.code].append(trade)

    def get_volume_profile(
        self,
        code: str,
        price_bins: int = 20,
    ) -> Dict[float, int]:
        """获取成交量分布"""
        trades = list(self._trades.get(code, []))
        if not trades:
            return {}

        # 价格区间
        prices = [t.price for t in trades]
        min_price, max_price = min(prices), max(prices)

        if min_price == max_price:
            return {min_price: sum(t.quantity for t in trades)}

        bin_size = (max_price - min_price) / price_bins
        volume_by_price = defaultdict(int)

        for trade in trades:
            bin_idx = int((trade.price - min_price) / bin_size)
            bin_price = min_price + bin_idx * bin_size + bin_size / 2
            volume_by_price[round(bin_price, 2)] += trade.quantity

        return dict(sorted(volume_by_price.items()))

    def get_time_distribution(
        self,
        code: str,
        interval_minutes: int = 5,
    ) -> Dict[str, Dict]:
        """获取时间分布"""
        trades = list(self._trades.get(code, []))
        if not trades:
            return {}

        distribution = defaultdict(lambda: {"count": 0, "volume": 0, "value": 0})

        for trade in trades:
            # 计算时间区间
            minute = trade.timestamp.minute
            interval_start = (minute // interval_minutes) * interval_minutes
            key = trade.timestamp.replace(minute=interval_start, second=0).strftime("%H:%M")

            distribution[key]["count"] += 1
            distribution[key]["volume"] += trade.quantity
            distribution[key]["value"] += trade.quantity * trade.price

        return dict(distribution)

    def get_trade_size_distribution(self, code: str) -> Dict[str, int]:
        """获取成交规模分布"""
        trades = list(self._trades.get(code, []))
        if not trades:
            return {}

        # 定义规模区间
        ranges = [
            (0, 100, "tiny"),
            (100, 500, "small"),
            (500, 1000, "medium"),
            (1000, 5000, "large"),
            (5000, float('inf'), "huge"),
        ]

        distribution = defaultdict(int)

        for trade in trades:
            for low, high, label in ranges:
                if low <= trade.quantity < high:
                    distribution[label] += 1
                    break

        return dict(distribution)

    def calculate_vwap(self, code: str) -> float:
        """计算VWAP"""
        trades = list(self._trades.get(code, []))
        if not trades:
            return 0

        total_value = sum(t.price * t.quantity for t in trades)
        total_volume = sum(t.quantity for t in trades)

        return total_value / total_volume if total_volume > 0 else 0


# ============ 买卖压力分析器 ============

class MarketPressureAnalyzer:
    """买卖压力分析器"""

    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self._trades: Dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))
        self._order_books: Dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))

    def add_trade(self, trade: Trade):
        """添加成交"""
        self._trades[trade.code].append(trade)

    def add_order_book(self, ob: OrderBook):
        """添加订单簿"""
        self._order_books[ob.code].append(ob)

    def analyze_pressure(self, code: str) -> PressureAnalysis:
        """分析压力"""
        trades = list(self._trades.get(code, []))
        obs = list(self._order_books.get(code, []))

        if not trades:
            return PressureAnalysis(
                code=code,
                timestamp=datetime.now(),
                pressure=MarketPressure.NEUTRAL,
                buy_pressure=0,
                sell_pressure=0,
                net_pressure=0,
                volume_ratio=1,
                trade_count_ratio=1,
            )

        # 成交量分析
        buy_volume = sum(t.quantity for t in trades if t.direction == TradeDirection.BUYER_INITIATED)
        sell_volume = sum(t.quantity for t in trades if t.direction == TradeDirection.SELLER_INITIATED)
        total_volume = buy_volume + sell_volume

        # 成交次数
        buy_count = sum(1 for t in trades if t.direction == TradeDirection.BUYER_INITIATED)
        sell_count = sum(1 for t in trades if t.direction == TradeDirection.SELLER_INITIATED)

        # 计算压力
        buy_pressure = buy_volume / total_volume if total_volume > 0 else 0.5
        sell_pressure = sell_volume / total_volume if total_volume > 0 else 0.5
        net_pressure = buy_pressure - sell_pressure

        volume_ratio = buy_volume / sell_volume if sell_volume > 0 else 1
        trade_count_ratio = buy_count / sell_count if sell_count > 0 else 1

        # 订单簿不平衡
        if obs:
            ob = obs[-1]
            bid_vol, ask_vol = ob.get_depth(5)
            ob_imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol) if (bid_vol + ask_vol) > 0 else 0
            net_pressure = net_pressure * 0.7 + ob_imbalance * 0.3

        # 判断压力方向
        if net_pressure > 0.3:
            pressure = MarketPressure.STRONG_BUY
        elif net_pressure > 0.1:
            pressure = MarketPressure.BUY
        elif net_pressure < -0.3:
            pressure = MarketPressure.STRONG_SELL
        elif net_pressure < -0.1:
            pressure = MarketPressure.SELL
        else:
            pressure = MarketPressure.NEUTRAL

        return PressureAnalysis(
            code=code,
            timestamp=datetime.now(),
            pressure=pressure,
            buy_pressure=buy_pressure,
            sell_pressure=sell_pressure,
            net_pressure=net_pressure,
            volume_ratio=volume_ratio,
            trade_count_ratio=trade_count_ratio,
        )


# ============ 流动性分析器 ============

class LiquidityAnalyzer:
    """流动性分析器"""

    def __init__(self):
        self._order_book_analyzer = OrderBookAnalyzer()
        self._trade_analyzer = TradeDistributionAnalyzer()
        self._metrics_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))

    def update_order_book(self, ob: OrderBook):
        """更新订单簿"""
        self._order_book_analyzer.update(ob)

    def add_trade(self, trade: Trade):
        """添加成交"""
        self._trade_analyzer.add_trade(trade)

    def calculate_metrics(self, code: str) -> LiquidityMetrics:
        """计算流动性指标"""
        ob = self._order_book_analyzer.get_current(code)

        if not ob:
            return LiquidityMetrics(
                code=code,
                timestamp=datetime.now(),
                spread_bps=0,
                depth=0,
                imbalance=0,
                effective_spread=0,
                realized_spread=0,
                price_impact=0,
                resilience=0,
                level=LiquidityLevel.ILLIQUID,
            )

        mid_price = ob.get_mid_price()
        spread = ob.get_spread()

        # 价差 (基点)
        spread_bps = spread / mid_price * 10000 if mid_price > 0 else 0

        # 深度
        bid_depth, ask_depth = ob.get_depth(5)
        depth = (bid_depth + ask_depth) * mid_price

        # 不平衡
        imbalance = self._order_book_analyzer.analyze_imbalance(code)

        # 有效价差 (简化)
        effective_spread = spread * 0.9

        # 价格冲击 (模拟)
        price_impact = self._order_book_analyzer.calculate_price_impact(
            code, 1000, OrderSide.BID
        )

        # 弹性 (简化)
        resilience = 1 / (1 + spread_bps / 100) if spread_bps > 0 else 1

        # 流动性等级
        level = self._determine_level(spread_bps, depth, price_impact)

        metrics = LiquidityMetrics(
            code=code,
            timestamp=datetime.now(),
            spread_bps=spread_bps,
            depth=depth,
            imbalance=imbalance,
            effective_spread=effective_spread,
            realized_spread=spread,
            price_impact=price_impact,
            resilience=resilience,
            level=level,
        )

        self._metrics_history[code].append(metrics)

        return metrics

    def _determine_level(
        self,
        spread_bps: float,
        depth: float,
        price_impact: float,
    ) -> LiquidityLevel:
        """确定流动性等级"""
        score = 0

        # 价差评分
        if spread_bps < 10:
            score += 3
        elif spread_bps < 30:
            score += 2
        elif spread_bps < 50:
            score += 1

        # 深度评分
        if depth > 1000000:
            score += 3
        elif depth > 500000:
            score += 2
        elif depth > 100000:
            score += 1

        # 冲击评分
        if price_impact < 0.001:
            score += 3
        elif price_impact < 0.005:
            score += 2
        elif price_impact < 0.01:
            score += 1

        # 综合评级
        if score >= 8:
            return LiquidityLevel.HIGH
        elif score >= 5:
            return LiquidityLevel.MEDIUM
        elif score >= 2:
            return LiquidityLevel.LOW
        else:
            return LiquidityLevel.ILLIQUID

    def get_liquidity_ranking(self, codes: List[str]) -> List[Dict]:
        """获取流动性排名"""
        rankings = []

        for code in codes:
            metrics = self.calculate_metrics(code)
            rankings.append({
                "code": code,
                "level": metrics.level.value,
                "spread_bps": metrics.spread_bps,
                "depth": metrics.depth,
                "price_impact": metrics.price_impact,
            })

        # 按流动性排序
        level_order = {
            LiquidityLevel.HIGH: 0,
            LiquidityLevel.MEDIUM: 1,
            LiquidityLevel.LOW: 2,
            LiquidityLevel.ILLIQUID: 3,
        }

        rankings.sort(key=lambda x: level_order.get(LiquidityLevel(x["level"]), 99))

        return rankings


# ============ 市场微观结构服务 ============

class MicrostructureService:
    """市场微观结构服务"""

    def __init__(self):
        self.order_book_analyzer = OrderBookAnalyzer()
        self.trade_analyzer = TradeDistributionAnalyzer()
        self.pressure_analyzer = MarketPressureAnalyzer()
        self.liquidity_analyzer = LiquidityAnalyzer()

    def process_order_book(self, ob: OrderBook):
        """处理订单簿"""
        self.order_book_analyzer.update(ob)
        self.pressure_analyzer.add_order_book(ob)
        self.liquidity_analyzer.update_order_book(ob)

    def process_trade(self, trade: Trade):
        """处理成交"""
        self.trade_analyzer.add_trade(trade)
        self.pressure_analyzer.add_trade(trade)
        self.liquidity_analyzer.add_trade(trade)

    def get_full_analysis(self, code: str) -> Dict:
        """获取完整分析"""
        return {
            "order_book": self.order_book_analyzer.get_current(code).to_dict() if self.order_book_analyzer.get_current(code) else None,
            "depth": self.order_book_analyzer.analyze_depth(code),
            "support_resistance": self.order_book_analyzer.detect_support_resistance(code),
            "pressure": self.pressure_analyzer.analyze_pressure(code).to_dict(),
            "liquidity": self.liquidity_analyzer.calculate_metrics(code).to_dict(),
            "volume_profile": self.trade_analyzer.get_volume_profile(code),
            "vwap": self.trade_analyzer.calculate_vwap(code),
        }


# ============ 便捷函数 ============

def create_microstructure_service() -> MicrostructureService:
    """创建微观结构服务"""
    return MicrostructureService()


def calculate_spread(best_bid: float, best_ask: float) -> Dict:
    """计算价差"""
    spread = best_ask - best_bid
    mid = (best_bid + best_ask) / 2
    spread_bps = spread / mid * 10000 if mid > 0 else 0

    return {
        "spread": spread,
        "spread_bps": spread_bps,
        "mid_price": mid,
    }


def estimate_price_impact(
    bids: List[Tuple[float, int]],
    asks: List[Tuple[float, int]],
    quantity: int,
    side: str,
) -> float:
    """估算价格冲击"""
    mid = (bids[0][0] + asks[0][0]) / 2 if bids and asks else 0

    if mid == 0:
        return 0

    remaining = quantity
    total_cost = 0

    if side == "buy":
        for price, vol in asks:
            if remaining <= 0:
                break
            fill = min(remaining, vol)
            total_cost += fill * price
            remaining -= fill
    else:
        for price, vol in bids:
            if remaining <= 0:
                break
            fill = min(remaining, vol)
            total_cost += fill * price
            remaining -= fill

    filled = quantity - remaining
    if filled == 0:
        return 0

    avg_price = total_cost / filled
    return abs(avg_price - mid) / mid
