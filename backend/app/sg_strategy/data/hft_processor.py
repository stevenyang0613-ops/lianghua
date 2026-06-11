"""松岗量化可转债策略 V3.0 高频数据处理模块

功能:
- 纳秒级时间戳处理
- Tick数据聚合
- 订单簿快照
- 实时特征计算
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Tuple
from enum import Enum
import logging
import time
import threading
from collections import deque, defaultdict
import struct

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class TickType(str, Enum):
    """Tick类型"""
    TRADE = "trade"
    BID = "bid"
    ASK = "ask"
    QUOTE = "quote"


class AggregationPeriod(str, Enum):
    """聚合周期"""
    TICK_100 = "100tick"
    SECOND_1 = "1s"
    SECOND_5 = "5s"
    SECOND_10 = "10s"
    MINUTE_1 = "1m"
    MINUTE_5 = "5m"


class SnapshotType(str, Enum):
    """快照类型"""
    FULL = "full"
    INCREMENTAL = "incremental"
    DELTA = "delta"


# ============ 数据模型 ============

@dataclass
class NanoTimestamp:
    """纳秒级时间戳"""
    seconds: int
    nanoseconds: int

    @classmethod
    def now(cls) -> 'NanoTimestamp':
        """获取当前时间"""
        t = time.time_ns()
        return cls(seconds=t // 1_000_000_000, nanoseconds=t % 1_000_000_000)

    @classmethod
    def from_datetime(cls, dt: datetime) -> 'NanoTimestamp':
        """从datetime创建"""
        ts = dt.timestamp()
        seconds = int(ts)
        nanoseconds = int((ts - seconds) * 1_000_000_000)
        return cls(seconds=seconds, nanoseconds=nanoseconds)

    def to_datetime(self) -> datetime:
        """转换为datetime"""
        return datetime.fromtimestamp(self.seconds + self.nanoseconds / 1e9)

    def to_nanoseconds(self) -> int:
        """转换为纳秒"""
        return self.seconds * 1_000_000_000 + self.nanoseconds

    def to_microseconds(self) -> int:
        """转换为微秒"""
        return self.to_nanoseconds() // 1000

    def to_milliseconds(self) -> int:
        """转换为毫秒"""
        return self.to_nanoseconds() // 1_000_000

    def __sub__(self, other: 'NanoTimestamp') -> int:
        """计算差值(纳秒)"""
        return self.to_nanoseconds() - other.to_nanoseconds()

    def __lt__(self, other: 'NanoTimestamp') -> bool:
        return self.to_nanoseconds() < other.to_nanoseconds()

    def __le__(self, other: 'NanoTimestamp') -> bool:
        return self.to_nanoseconds() <= other.to_nanoseconds()


@dataclass
class HFTTick:
    """高频Tick数据"""
    code: str
    timestamp: NanoTimestamp
    tick_type: TickType
    price: float
    volume: int
    bid_price: float = 0
    bid_volume: int = 0
    ask_price: float = 0
    ask_volume: int = 0
    trade_direction: int = 0  # 1=买方发起, -1=卖方发起
    sequence: int = 0

    def to_bytes(self) -> bytes:
        """序列化为字节"""
        return struct.pack(
            '<Qqddiidddiiq',
            self.timestamp.to_nanoseconds(),
            self.sequence,
            self.price,
            self.volume,
            self.tick_type.value.encode()[0] if isinstance(self.tick_type, str) else 0,
            self.bid_price,
            self.bid_volume,
            self.ask_price,
            self.ask_volume,
            self.trade_direction,
            len(self.code),
            hash(self.code),
        )

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "timestamp": self.timestamp.to_nanoseconds(),
            "price": self.price,
            "volume": self.volume,
            "bid": self.bid_price,
            "ask": self.ask_price,
        }


@dataclass
class TickBar:
    """Tick聚合Bar"""
    code: str
    start_time: NanoTimestamp
    end_time: NanoTimestamp
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int
    vwap: float
    trade_count: int
    tick_count: int

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "start_time": self.start_time.to_nanoseconds(),
            "end_time": self.end_time.to_nanoseconds(),
            "open": self.open_price,
            "high": self.high_price,
            "low": self.low_price,
            "close": self.close_price,
            "volume": self.volume,
            "vwap": round(self.vwap, 4),
            "trade_count": self.trade_count,
        }


@dataclass
class OrderBookSnapshot:
    """订单簿快照"""
    code: str
    timestamp: NanoTimestamp
    bids: List[Tuple[float, int]]  # [(price, volume), ...]
    asks: List[Tuple[float, int]]
    snapshot_type: SnapshotType = SnapshotType.FULL
    sequence: int = 0
    checksum: int = 0

    def get_best_bid(self) -> Tuple[float, int]:
        """获取最优买价"""
        return self.bids[0] if self.bids else (0, 0)

    def get_best_ask(self) -> Tuple[float, int]:
        """获取最优卖价"""
        return self.asks[0] if self.asks else (0, 0)

    def get_spread(self) -> float:
        """获取价差"""
        best_bid, _ = self.get_best_bid()
        best_ask, _ = self.get_best_ask()
        return best_ask - best_bid if best_bid and best_ask else 0

    def get_mid_price(self) -> float:
        """获取中间价"""
        best_bid, _ = self.get_best_bid()
        best_ask, _ = self.get_best_ask()
        return (best_bid + best_ask) / 2 if best_bid and best_ask else 0

    def calculate_checksum(self) -> int:
        """计算校验和"""
        data = f"{self.code}{len(self.bids)}{len(self.asks)}"
        for price, vol in self.bids[:5]:
            data += f"{price}{vol}"
        for price, vol in self.asks[:5]:
            data += f"{price}{vol}"
        return hash(data) & 0xFFFFFFFF

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "timestamp": self.timestamp.to_nanoseconds(),
            "bids": self.bids[:10],
            "asks": self.asks[:10],
            "spread": round(self.get_spread(), 4),
            "mid_price": round(self.get_mid_price(), 4),
        }


# ============ 纳秒级时间戳处理器 ============

class NanoTimestampProcessor:
    """纳秒级时间戳处理器"""

    def __init__(self):
        self._reference_time: NanoTimestamp = None
        self._last_timestamp: NanoTimestamp = None

    def set_reference(self, timestamp: NanoTimestamp):
        """设置参考时间"""
        self._reference_time = timestamp

    def process(self, timestamp: NanoTimestamp) -> Dict[str, Any]:
        """处理时间戳"""
        result = {
            "timestamp": timestamp,
            "datetime": timestamp.to_datetime(),
            "nanoseconds": timestamp.to_nanoseconds(),
            "microseconds": timestamp.to_microseconds(),
            "milliseconds": timestamp.to_milliseconds(),
        }

        if self._reference_time:
            result["latency_ns"] = NanoTimestamp.now().to_nanoseconds() - timestamp.to_nanoseconds()
            result["elapsed_ns"] = timestamp.to_nanoseconds() - self._reference_time.to_nanoseconds()

        if self._last_timestamp:
            result["delta_ns"] = timestamp.to_nanoseconds() - self._last_timestamp.to_nanoseconds()

        self._last_timestamp = timestamp

        return result

    def normalize(self, timestamp: NanoTimestamp, resolution_ns: int = 1000) -> NanoTimestamp:
        """标准化时间戳"""
        ns = timestamp.to_nanoseconds()
        normalized = (ns // resolution_ns) * resolution_ns
        return NanoTimestamp(
            seconds=normalized // 1_000_000_000,
            nanoseconds=normalized % 1_000_000_000,
        )

    def align_to_period(self, timestamp: NanoTimestamp, period_ns: int) -> NanoTimestamp:
        """对齐到周期边界"""
        ns = timestamp.to_nanoseconds()
        aligned = (ns // period_ns) * period_ns
        return NanoTimestamp(
            seconds=aligned // 1_000_000_000,
            nanoseconds=aligned % 1_000_000_000,
        )


# ============ Tick数据聚合器 ============

class TickAggregator:
    """Tick数据聚合器"""

    def __init__(self, buffer_size: int = 10000):
        self.buffer_size = buffer_size
        self._tick_buffers: Dict[str, deque] = defaultdict(lambda: deque(maxlen=buffer_size))
        self._bars: Dict[str, List[TickBar]] = defaultdict(list)
        self._current_bar: Dict[str, Dict] = {}

    def add_tick(self, tick: HFTTick):
        """添加Tick"""
        self._tick_buffers[tick.code].append(tick)

    def aggregate_by_time(
        self,
        code: str,
        period: AggregationPeriod,
    ) -> List[TickBar]:
        """按时间聚合"""
        ticks = list(self._tick_buffers.get(code, []))
        if not ticks:
            return []

        # 确定聚合窗口(纳秒)
        period_ns = {
            AggregationPeriod.SECOND_1: 1_000_000_000,
            AggregationPeriod.SECOND_5: 5_000_000_000,
            AggregationPeriod.SECOND_10: 10_000_000_000,
            AggregationPeriod.MINUTE_1: 60_000_000_000,
            AggregationPeriod.MINUTE_5: 300_000_000_000,
        }.get(period, 1_000_000_000)

        bars = []
        current_bar_data = None
        bar_start = None

        for tick in sorted(ticks, key=lambda t: t.timestamp.to_nanoseconds()):
            tick_ns = tick.timestamp.to_nanoseconds()
            bar_index = tick_ns // period_ns
            bar_start_ns = bar_index * period_ns

            if current_bar_data is None or bar_start_ns != bar_start:
                # 新Bar
                if current_bar_data:
                    bars.append(self._create_bar(current_bar_data))

                bar_start = bar_start_ns
                current_bar_data = {
                    "code": code,
                    "start_time": NanoTimestamp(
                        seconds=bar_start_ns // 1_000_000_000,
                        nanoseconds=bar_start_ns % 1_000_000_000,
                    ),
                    "prices": [],
                    "volumes": [],
                    "tick_count": 0,
                }

            current_bar_data["prices"].append(tick.price)
            current_bar_data["volumes"].append(tick.volume)
            current_bar_data["tick_count"] += 1

        # 最后一个Bar
        if current_bar_data:
            bars.append(self._create_bar(current_bar_data))

        return bars

    def aggregate_by_tick_count(
        self,
        code: str,
        tick_count: int = 100,
    ) -> List[TickBar]:
        """按Tick数量聚合"""
        ticks = list(self._tick_buffers.get(code, []))
        if not ticks:
            return []

        bars = []

        for i in range(0, len(ticks), tick_count):
            bar_ticks = ticks[i:i + tick_count]
            if not bar_ticks:
                continue

            bar_data = {
                "code": code,
                "start_time": bar_ticks[0].timestamp,
                "prices": [t.price for t in bar_ticks],
                "volumes": [t.volume for t in bar_ticks],
                "tick_count": len(bar_ticks),
            }

            bars.append(self._create_bar(bar_data))

        return bars

    def _create_bar(self, data: Dict) -> TickBar:
        """创建Bar"""
        prices = data["prices"]
        volumes = data["volumes"]

        total_value = sum(p * v for p, v in zip(prices, volumes))
        total_volume = sum(volumes)

        return TickBar(
            code=data["code"],
            start_time=data["start_time"],
            end_time=NanoTimestamp.now(),
            open_price=prices[0] if prices else 0,
            high_price=max(prices) if prices else 0,
            low_price=min(prices) if prices else 0,
            close_price=prices[-1] if prices else 0,
            volume=total_volume,
            vwap=total_value / total_volume if total_volume > 0 else 0,
            trade_count=len([v for v in volumes if v > 0]),
            tick_count=data["tick_count"],
        )


# ============ 订单簿管理器 ============

class OrderBookManager:
    """订单簿管理器"""

    def __init__(self, max_levels: int = 20):
        self.max_levels = max_levels
        self._order_books: Dict[str, OrderBookSnapshot] = {}
        self._update_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))

    def update_from_tick(self, tick: HFTTick) -> OrderBookSnapshot:
        """从Tick更新订单簿"""
        code = tick.code

        if code not in self._order_books:
            # 初始化空订单簿
            self._order_books[code] = OrderBookSnapshot(
                code=code,
                timestamp=tick.timestamp,
                bids=[],
                asks=[],
            )

        ob = self._order_books[code]
        ob.timestamp = tick.timestamp

        # 更新买卖价
        if tick.bid_price > 0 and tick.bid_volume > 0:
            self._update_level(ob.bids, tick.bid_price, tick.bid_volume, is_bid=True)

        if tick.ask_price > 0 and tick.ask_volume > 0:
            self._update_level(ob.asks, tick.ask_price, tick.ask_volume, is_bid=False)

        # 记录历史
        self._update_history[code].append({
            "timestamp": tick.timestamp.to_nanoseconds(),
            "mid_price": ob.get_mid_price(),
            "spread": ob.get_spread(),
        })

        return ob

    def _update_level(self, levels: List[Tuple[float, int]], price: float, volume: int, is_bid: bool):
        """更新价格层级"""
        # 查找价格位置
        for i, (p, v) in enumerate(levels):
            if p == price:
                if volume == 0:
                    # 删除层级
                    levels.pop(i)
                else:
                    # 更新量
                    levels[i] = (price, volume)
                return

            # 插入位置
            if is_bid and price > p:
                levels.insert(i, (price, volume))
                # 裁剪
                if len(levels) > self.max_levels:
                    levels.pop()
                return
            elif not is_bid and price < p:
                levels.insert(i, (price, volume))
                if len(levels) > self.max_levels:
                    levels.pop()
                return

        # 添加到末尾
        if len(levels) < self.max_levels:
            levels.append((price, volume))

    def get_snapshot(self, code: str) -> Optional[OrderBookSnapshot]:
        """获取快照"""
        return self._order_books.get(code)

    def get_depth(self, code: str, levels: int = 5) -> Dict:
        """获取深度"""
        ob = self._order_books.get(code)
        if not ob:
            return {}

        return {
            "bids": ob.bids[:levels],
            "asks": ob.asks[:levels],
            "bid_volume": sum(v for _, v in ob.bids[:levels]),
            "ask_volume": sum(v for _, v in ob.asks[:levels]),
            "imbalance": self._calculate_imbalance(ob, levels),
        }

    def _calculate_imbalance(self, ob: OrderBookSnapshot, levels: int) -> float:
        """计算不平衡度"""
        bid_vol = sum(v for _, v in ob.bids[:levels])
        ask_vol = sum(v for _, v in ob.asks[:levels])
        total = bid_vol + ask_vol

        return (bid_vol - ask_vol) / total if total > 0 else 0


# ============ 实时特征计算器 ============

class RealtimeFeatureCalculator:
    """实时特征计算器"""

    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self._price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))
        self._volume_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))
        self._trade_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))

    def update(self, tick: HFTTick):
        """更新数据"""
        code = tick.code
        self._price_history[code].append(tick.price)
        self._volume_history[code].append(tick.volume)

        if tick.tick_type == TickType.TRADE:
            self._trade_history[code].append({
                "price": tick.price,
                "volume": tick.volume,
                "direction": tick.trade_direction,
            })

    def calculate_features(self, code: str) -> Dict[str, float]:
        """计算特征"""
        prices = list(self._price_history.get(code, []))
        volumes = list(self._volume_history.get(code, []))
        trades = list(self._trade_history.get(code, []))

        if not prices:
            return {}

        features = {}

        # 价格特征
        features["current_price"] = prices[-1]
        features["price_mean"] = sum(prices) / len(prices)
        features["price_std"] = self._calculate_std(prices)
        features["price_range"] = max(prices) - min(prices) if prices else 0

        # 成交量特征
        if volumes:
            features["volume_mean"] = sum(volumes) / len(volumes)
            features["volume_sum"] = sum(volumes)
            features["volume_max"] = max(volumes)

        # 动量特征
        if len(prices) >= 10:
            features["momentum_10"] = (prices[-1] - prices[-10]) / prices[-10] if prices[-10] != 0 else 0

        if len(prices) >= 20:
            features["momentum_20"] = (prices[-1] - prices[-20]) / prices[-20] if prices[-20] != 0 else 0

        # VWAP
        if trades:
            total_value = sum(t["price"] * t["volume"] for t in trades)
            total_volume = sum(t["volume"] for t in trades)
            features["vwap"] = total_value / total_volume if total_volume > 0 else 0

        # 买卖压力
        if trades:
            buy_volume = sum(t["volume"] for t in trades if t["direction"] > 0)
            sell_volume = sum(t["volume"] for t in trades if t["direction"] < 0)
            total = buy_volume + sell_volume

            features["buy_pressure"] = buy_volume / total if total > 0 else 0.5
            features["order_imbalance"] = (buy_volume - sell_volume) / total if total > 0 else 0

        # 波动率
        if len(prices) >= 20:
            returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices)) if prices[i-1] != 0]
            features["realized_vol"] = self._calculate_std(returns) * (252 ** 0.5) if returns else 0

        return features

    def _calculate_std(self, values: List[float]) -> float:
        """计算标准差"""
        if len(values) < 2:
            return 0
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return variance ** 0.5

    def calculate_microstructure_features(self, ob: OrderBookSnapshot) -> Dict[str, float]:
        """计算微观结构特征"""
        features = {}

        # 价差
        features["spread"] = ob.get_spread()
        features["spread_bps"] = ob.get_spread() / ob.get_mid_price() * 10000 if ob.get_mid_price() > 0 else 0

        # 深度
        bid_depth = sum(v for _, v in ob.bids[:5])
        ask_depth = sum(v for _, v in ob.asks[:5])
        features["bid_depth"] = bid_depth
        features["ask_depth"] = ask_depth
        features["depth_imbalance"] = (bid_depth - ask_depth) / (bid_depth + ask_depth) if (bid_depth + ask_depth) > 0 else 0

        # 斜率
        if len(ob.bids) >= 2 and len(ob.asks) >= 2:
            bid_slope = (ob.bids[0][0] - ob.bids[-1][0]) / len(ob.bids) if ob.bids else 0
            ask_slope = (ob.asks[-1][0] - ob.asks[0][0]) / len(ob.asks) if ob.asks else 0
            features["bid_slope"] = bid_slope
            features["ask_slope"] = ask_slope

        return features


# ============ 高频数据处理服务 ============

class HFTDataProcessor:
    """高频数据处理服务"""

    def __init__(self):
        self.timestamp_processor = NanoTimestampProcessor()
        self.tick_aggregator = TickAggregator()
        self.order_book_manager = OrderBookManager()
        self.feature_calculator = RealtimeFeatureCalculator()

        self._tick_handlers: List[callable] = []
        self._stats = {
            "ticks_processed": 0,
            "bars_created": 0,
            "features_calculated": 0,
        }

    def process_tick(self, tick: HFTTick) -> Dict:
        """处理Tick"""
        # 更新聚合器
        self.tick_aggregator.add_tick(tick)

        # 更新订单簿
        ob = self.order_book_manager.update_from_tick(tick)

        # 更新特征
        self.feature_calculator.update(tick)

        self._stats["ticks_processed"] += 1

        # 触发处理器
        for handler in self._tick_handlers:
            try:
                handler(tick)
            except Exception as e:
                logger.error(f"[HFTDataProcessor] 处理器执行失败: {e}")

        return {
            "tick": tick.to_dict(),
            "order_book": ob.to_dict() if ob else None,
            "features": self.feature_calculator.calculate_features(tick.code),
        }

    def get_bar(self, code: str, period: AggregationPeriod) -> List[TickBar]:
        """获取Bar数据"""
        return self.tick_aggregator.aggregate_by_time(code, period)

    def get_order_book(self, code: str) -> Optional[OrderBookSnapshot]:
        """获取订单簿"""
        return self.order_book_manager.get_snapshot(code)

    def get_features(self, code: str) -> Dict[str, float]:
        """获取特征"""
        features = self.feature_calculator.calculate_features(code)

        ob = self.order_book_manager.get_snapshot(code)
        if ob:
            features.update(self.feature_calculator.calculate_microstructure_features(ob))

        return features

    def register_tick_handler(self, handler: callable):
        """注册Tick处理器"""
        self._tick_handlers.append(handler)

    def get_stats(self) -> Dict:
        """获取统计"""
        return self._stats.copy()


# ============ 便捷函数 ============

def create_hft_processor() -> HFTDataProcessor:
    """创建高频处理器"""
    return HFTDataProcessor()


def create_tick(
    code: str,
    price: float,
    volume: int,
    bid_price: float = 0,
    ask_price: float = 0,
) -> HFTTick:
    """创建Tick"""
    return HFTTick(
        code=code,
        timestamp=NanoTimestamp.now(),
        tick_type=TickType.TRADE,
        price=price,
        volume=volume,
        bid_price=bid_price,
        ask_price=ask_price,
    )
