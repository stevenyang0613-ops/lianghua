"""西部量化可转债策略 V3.0 策略回放仿真模块

功能:
- 历史数据回放
- 滑点模拟
- 延迟注入
- 实盘对比分析
- 回放控制
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Callable, Generator
from enum import Enum
import logging
import json
import time
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class ReplayMode(str, Enum):
    """回放模式"""
    REALTIME = "realtime"       # 实时回放
    FAST = "fast"               # 快速回放
    STEP = "step"               # 单步回放
    BENCHMARK = "benchmark"     # 基准测试


class ReplayStatus(str, Enum):
    """回放状态"""
    IDLE = "idle"
    LOADING = "loading"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"


class SlippageModel(str, Enum):
    """滑点模型"""
    NONE = "none"               # 无滑点
    FIXED = "fixed"             # 固定滑点
    PROPORTIONAL = "proportional"  # 比例滑点
    QUADRATIC = "quadratic"     # 二次滑点
    MARKET_IMPACT = "impact"    # 市场冲击


class LatencyModel(str, Enum):
    """延迟模型"""
    NONE = "none"               # 无延迟
    FIXED = "fixed"             # 固定延迟
    RANDOM = "random"           # 随机延迟
    DISTRIBUTION = "distribution"  # 分布延迟


# ============ 配置类 ============

@dataclass
class ReplayConfig:
    """回放配置"""
    mode: ReplayMode = ReplayMode.FAST
    start_date: datetime = None
    end_date: datetime = None
    speed_multiplier: float = 10.0  # 回放速度倍数
    enable_slippage: bool = True
    slippage_model: SlippageModel = SlippageModel.PROPORTIONAL
    slippage_bps: float = 5.0       # 基点
    enable_latency: bool = True
    latency_model: LatencyModel = LatencyModel.RANDOM
    latency_ms_mean: float = 50     # 平均延迟
    latency_ms_std: float = 20      # 延迟标准差
    initial_capital: float = 1000000
    commission_rate: float = 0.0003
    min_commission: float = 5.0


@dataclass
class ReplayTick:
    """回放Tick"""
    code: str
    timestamp: datetime
    price: float
    volume: int
    bid_price: float
    ask_price: float
    bid_volume: int
    ask_volume: int
    sequence: int = 0

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "timestamp": self.timestamp.isoformat(),
            "price": self.price,
            "volume": self.volume,
            "bid": self.bid_price,
            "ask": self.ask_price,
        }


@dataclass
class SimulatedOrder:
    """模拟订单"""
    order_id: str
    code: str
    side: str
    quantity: int
    price: float
    order_type: str
    created_at: datetime
    execute_at: datetime = None
    filled_quantity: int = 0
    filled_price: float = 0
    slippage: float = 0
    latency_ms: float = 0
    status: str = "pending"

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "code": self.code,
            "side": self.side,
            "quantity": self.quantity,
            "price": self.price,
            "filled_quantity": self.filled_quantity,
            "filled_price": self.filled_price,
            "slippage": self.slippage,
            "latency_ms": self.latency_ms,
            "status": self.status,
        }


@dataclass
class ReplayStatistics:
    """回放统计"""
    start_time: datetime = None
    end_time: datetime = None
    ticks_processed: int = 0
    orders_submitted: int = 0
    orders_filled: int = 0
    total_volume: int = 0
    total_turnover: float = 0
    total_commission: float = 0
    total_slippage: float = 0
    avg_latency_ms: float = 0
    fill_rate: float = 0
    error_count: int = 0


# ============ 滑点模拟器 ============

class SlippageSimulator:
    """滑点模拟器"""

    def __init__(self, config: ReplayConfig):
        self.config = config
        self._impact_history: List[float] = []

    def apply_slippage(
        self,
        order: SimulatedOrder,
        market_price: float,
        market_volume: int = 0,
        adv: float = 0,
    ) -> float:
        """应用滑点"""
        if not self.config.enable_slippage:
            return market_price

        slippage = 0.0

        if self.config.slippage_model == SlippageModel.FIXED:
            # 固定滑点
            slippage = self.config.slippage_bps / 10000

        elif self.config.slippage_model == SlippageModel.PROPORTIONAL:
            # 比例滑点 (与订单大小相关)
            base_slippage = self.config.slippage_bps / 10000
            volume_factor = order.quantity / 10000 if order.quantity > 0 else 1
            slippage = base_slippage * min(5, 1 + volume_factor)

        elif self.config.slippage_model == SlippageModel.QUADRATIC:
            # 二次滑点模型
            base_slippage = self.config.slippage_bps / 10000
            volume_factor = (order.quantity / 10000) ** 2 if order.quantity > 0 else 0
            slippage = base_slippage * (1 + volume_factor)

        elif self.config.slippage_model == SlippageModel.MARKET_IMPACT:
            # 市场冲击模型
            base_slippage = self.config.slippage_bps / 10000
            if adv > 0:
                participation = order.quantity / adv
                # Almgren-Chriss简化
                impact = 0.1 * participation + 0.05 * (participation ** 0.5)
                slippage = base_slippage + impact
            else:
                slippage = base_slippage

        # 买单价格上浮，卖单价格下浮
        if order.side == "buy":
            filled_price = market_price * (1 + slippage)
        else:
            filled_price = market_price * (1 - slippage)

        order.slippage = slippage
        self._impact_history.append(slippage)

        return filled_price

    def get_statistics(self) -> Dict:
        """获取统计"""
        if not self._impact_history:
            return {"avg_slippage": 0, "max_slippage": 0}

        return {
            "avg_slippage": sum(self._impact_history) / len(self._impact_history),
            "max_slippage": max(self._impact_history),
            "min_slippage": min(self._impact_history),
        }


# ============ 延迟模拟器 ============

class LatencySimulator:
    """延迟模拟器"""

    def __init__(self, config: ReplayConfig):
        self.config = config
        self._latency_history: List[float] = []

    def inject_latency(self, order: SimulatedOrder) -> float:
        """注入延迟"""
        if not self.config.enable_latency:
            order.latency_ms = 0
            return 0

        latency_ms = 0.0

        if self.config.latency_model == LatencyModel.FIXED:
            latency_ms = self.config.latency_ms_mean

        elif self.config.latency_model == LatencyModel.RANDOM:
            # 正态分布随机延迟
            import random
            latency_ms = random.gauss(
                self.config.latency_ms_mean,
                self.config.latency_ms_std,
            )
            latency_ms = max(0, latency_ms)

        elif self.config.latency_model == LatencyModel.DISTRIBUTION:
            # 复杂分布延迟
            latency_ms = self._sample_latency_distribution()

        order.latency_ms = latency_ms
        self._latency_history.append(latency_ms)

        return latency_ms / 1000  # 返回秒

    def _sample_latency_distribution(self) -> float:
        """采样延迟分布"""
        import random

        # 混合分布: 70%正常 + 20%高延迟 + 10%极端延迟
        r = random.random()

        if r < 0.7:
            return random.gauss(self.config.latency_ms_mean, self.config.latency_ms_std)
        elif r < 0.9:
            return random.gauss(self.config.latency_ms_mean * 2, self.config.latency_ms_std * 2)
        else:
            return random.gauss(self.config.latency_ms_mean * 5, self.config.latency_ms_std * 3)

    def get_statistics(self) -> Dict:
        """获取统计"""
        if not self._latency_history:
            return {"avg_latency_ms": 0, "p99_latency_ms": 0}

        sorted_latencies = sorted(self._latency_history)
        n = len(sorted_latencies)

        return {
            "avg_latency_ms": sum(sorted_latencies) / n,
            "p50_latency_ms": sorted_latencies[int(n * 0.5)],
            "p95_latency_ms": sorted_latencies[int(n * 0.95)],
            "p99_latency_ms": sorted_latencies[int(n * 0.99)],
            "max_latency_ms": sorted_latencies[-1],
        }


# ============ 数据回放器 ============

class DataReplayer:
    """数据回放器"""

    def __init__(self, config: ReplayConfig):
        self.config = config
        self._tick_buffer: deque = deque()
        self._order_buffer: deque = deque()
        self._current_time: datetime = None
        self._status = ReplayStatus.IDLE
        self._lock = threading.Lock()

    def load_data(
        self,
        data_source: str,
        codes: List[str] = None,
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> int:
        """加载数据"""
        self._status = ReplayStatus.LOADING

        # 模拟加载数据
        # 实际实现应从数据库或文件读取
        tick_count = self._load_ticks_from_source(data_source, codes, start_date, end_date)

        self._status = ReplayStatus.READY
        logger.info(f"[DataReplayer] 加载 {tick_count} 条数据")

        return tick_count

    def _load_ticks_from_source(
        self,
        source: str,
        codes: List[str],
        start_date: datetime,
        end_date: datetime,
    ) -> int:
        """从数据源加载Tick"""
        # 模拟生成测试数据
        tick_count = 0
        current = start_date or datetime(2024, 1, 1, 9, 30)
        end = end_date or datetime(2024, 1, 1, 15, 0)

        codes = codes or ["128001", "128002", "128003"]

        while current < end:
            for code in codes:
                # 生成模拟Tick
                import random
                base_price = 100 + random.random() * 50

                tick = ReplayTick(
                    code=code,
                    timestamp=current,
                    price=base_price,
                    volume=random.randint(100, 10000),
                    bid_price=base_price - 0.01,
                    ask_price=base_price + 0.01,
                    bid_volume=random.randint(100, 5000),
                    ask_volume=random.randint(100, 5000),
                    sequence=tick_count,
                )
                self._tick_buffer.append(tick)
                tick_count += 1

            # 时间推进
            current += timedelta(seconds=3)

        return tick_count

    def get_next_tick(self) -> Optional[ReplayTick]:
        """获取下一个Tick"""
        with self._lock:
            if self._tick_buffer:
                tick = self._tick_buffer.popleft()
                self._current_time = tick.timestamp
                return tick
            return None

    def peek_next_tick(self) -> Optional[ReplayTick]:
        """预览下一个Tick"""
        with self._lock:
            if self._tick_buffer:
                return self._tick_buffer[0]
            return None

    def get_tick_count(self) -> int:
        """获取Tick数量"""
        return len(self._tick_buffer)

    def seek_to_time(self, target_time: datetime):
        """跳转到指定时间"""
        with self._lock:
            while self._tick_buffer and self._tick_buffer[0].timestamp < target_time:
                self._tick_buffer.popleft()

    def reset(self):
        """重置"""
        with self._lock:
            self._tick_buffer.clear()
            self._order_buffer.clear()
            self._current_time = None
            self._status = ReplayStatus.IDLE


# ============ 策略回放引擎 ============

class StrategyReplayEngine:
    """策略回放引擎"""

    def __init__(self, config: ReplayConfig = None):
        self.config = config or ReplayConfig()
        self.data_replayer = DataReplayer(self.config)
        self.slippage_sim = SlippageSimulator(self.config)
        self.latency_sim = LatencySimulator(self.config)

        # 回调函数
        self._tick_callbacks: List[Callable] = []
        self._order_callbacks: List[Callable] = []
        self._signal_callbacks: List[Callable] = []

        # 模拟账户
        self._positions: Dict[str, int] = {}
        self._cash: float = self.config.initial_capital
        self._orders: Dict[str, SimulatedOrder] = {}
        self._pending_orders: deque = deque()

        # 统计
        self._stats = ReplayStatistics()

        # 控制变量
        self._status = ReplayStatus.IDLE
        self._running = False
        self._paused = False
        self._lock = threading.Lock()

    def load_data(
        self,
        data_source: str,
        codes: List[str] = None,
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> int:
        """加载数据"""
        return self.data_replayer.load_data(
            data_source=data_source,
            codes=codes,
            start_date=start_date or self.config.start_date,
            end_date=end_date or self.config.end_date,
        )

    def register_tick_callback(self, callback: Callable):
        """注册Tick回调"""
        self._tick_callbacks.append(callback)

    def register_order_callback(self, callback: Callable):
        """注册订单回调"""
        self._order_callbacks.append(callback)

    def submit_order(
        self,
        code: str,
        side: str,
        quantity: int,
        price: float = 0,
        order_type: str = "market",
    ) -> str:
        """提交订单"""
        order_id = f"order_{int(time.time() * 1000000)}"

        order = SimulatedOrder(
            order_id=order_id,
            code=code,
            side=side,
            quantity=quantity,
            price=price,
            order_type=order_type,
            created_at=self.data_replayer._current_time or datetime.now(),
        )

        with self._lock:
            self._orders[order_id] = order
            self._pending_orders.append(order)

        self._stats.orders_submitted += 1

        return order_id

    def start(self):
        """开始回放"""
        self._status = ReplayStatus.RUNNING
        self._running = True
        self._paused = False
        self._stats.start_time = datetime.now()

        logger.info("[StrategyReplayEngine] 开始回放")

        # 启动回放线程
        thread = threading.Thread(target=self._replay_loop, daemon=True)
        thread.start()

    def pause(self):
        """暂停回放"""
        self._paused = True
        self._status = ReplayStatus.PAUSED

    def resume(self):
        """恢复回放"""
        self._paused = False
        self._status = ReplayStatus.RUNNING

    def stop(self):
        """停止回放"""
        self._running = False
        self._status = ReplayStatus.COMPLETED
        self._stats.end_time = datetime.now()

    def _replay_loop(self):
        """回放循环"""
        last_tick_time = None

        while self._running:
            if self._paused:
                time.sleep(0.01)
                continue

            tick = self.data_replayer.get_next_tick()
            if tick is None:
                self.stop()
                break

            # 回放速度控制
            if self.config.mode == ReplayMode.REALTIME and last_tick_time:
                real_interval = (tick.timestamp - last_tick_time).total_seconds()
                time.sleep(real_interval)
            elif self.config.mode == ReplayMode.FAST:
                time.sleep(0.001 / self.config.speed_multiplier)
            elif self.config.mode == ReplayMode.STEP:
                # 单步模式需要手动触发
                self._paused = True

            last_tick_time = tick.timestamp

            # 处理Tick
            self._process_tick(tick)

            # 处理待执行订单
            self._process_pending_orders(tick)

            self._stats.ticks_processed += 1

        logger.info("[StrategyReplayEngine] 回放完成")

    def _process_tick(self, tick: ReplayTick):
        """处理Tick"""
        # 触发回调
        for callback in self._tick_callbacks:
            try:
                callback(tick)
            except Exception as e:
                logger.error(f"[StrategyReplayEngine] Tick回调失败: {e}")

    def _process_pending_orders(self, tick: ReplayTick):
        """处理待执行订单"""
        processed_orders = []

        while self._pending_orders:
            order = self._pending_orders.popleft()

            if order.code != tick.code:
                # 放回队列
                processed_orders.append(order)
                continue

            # 注入延迟
            delay_seconds = self.latency_sim.inject_latency(order)

            if delay_seconds > 0:
                # 简化: 直接执行 (实际应延迟处理)
                pass

            # 应用滑点
            if order.order_type == "market":
                market_price = tick.ask_price if order.side == "buy" else tick.bid_price
            else:
                market_price = order.price

            filled_price = self.slippage_sim.apply_slippage(
                order=order,
                market_price=market_price,
            )

            # 执行订单
            order.filled_quantity = order.quantity
            order.filled_price = filled_price
            order.execute_at = tick.timestamp
            order.status = "filled"

            # 更新账户
            self._update_account(order)

            # 更新统计
            self._stats.orders_filled += 1
            self._stats.total_volume += order.filled_quantity
            self._stats.total_turnover += order.filled_quantity * order.filled_price
            self._stats.total_slippage += abs(order.slippage) * order.filled_quantity * order.filled_price

            # 触发回调
            for callback in self._order_callbacks:
                try:
                    callback(order)
                except Exception as e:
                    logger.error(f"[StrategyReplayEngine] 订单回调失败: {e}")

        # 放回未处理订单
        for order in processed_orders:
            self._pending_orders.append(order)

    def _update_account(self, order: SimulatedOrder):
        """更新账户"""
        amount = order.filled_quantity * order.filled_price
        commission = max(amount * self.config.commission_rate, self.config.min_commission)

        if order.side == "buy":
            self._positions[order.code] = self._positions.get(order.code, 0) + order.filled_quantity
            self._cash -= (amount + commission)
        else:
            self._positions[order.code] = self._positions.get(order.code, 0) - order.filled_quantity
            self._cash += (amount - commission)

        self._stats.total_commission += commission

    def get_portfolio(self) -> Dict:
        """获取组合"""
        return {
            "cash": self._cash,
            "positions": dict(self._positions),
            "orders": {oid: o.to_dict() for oid, o in self._orders.items()},
        }

    def get_statistics(self) -> Dict:
        """获取统计"""
        self._stats.avg_latency_ms = self.latency_sim.get_statistics().get("avg_latency_ms", 0)

        if self._stats.orders_submitted > 0:
            self._stats.fill_rate = self._stats.orders_filled / self._stats.orders_submitted

        return {
            "status": self._status.value,
            "ticks_processed": self._stats.ticks_processed,
            "orders_submitted": self._stats.orders_submitted,
            "orders_filled": self._stats.orders_filled,
            "fill_rate": round(self._stats.fill_rate, 4),
            "total_volume": self._stats.total_volume,
            "total_turnover": round(self._stats.total_turnover, 2),
            "total_commission": round(self._stats.total_commission, 2),
            "total_slippage": round(self._stats.total_slippage, 2),
            "avg_latency_ms": round(self._stats.avg_latency_ms, 2),
            "slippage_stats": self.slippage_sim.get_statistics(),
            "latency_stats": self.latency_sim.get_statistics(),
        }


# ============ 实盘对比分析器 ============

class LiveComparisonAnalyzer:
    """实盘对比分析器"""

    def __init__(self):
        self._replay_trades: List[Dict] = []
        self._live_trades: List[Dict] = []
        self._comparison_results: Dict = {}

    def record_replay_trade(self, trade: Dict):
        """记录回放交易"""
        self._replay_trades.append(trade)

    def record_live_trade(self, trade: Dict):
        """记录实盘交易"""
        self._live_trades.append(trade)

    def compare(self) -> Dict:
        """对比分析"""
        # 收益对比
        replay_pnl = sum(t.get("pnl", 0) for t in self._replay_trades)
        live_pnl = sum(t.get("pnl", 0) for t in self._live_trades)

        # 执行对比
        replay_avg_slippage = self._calculate_avg_slippage(self._replay_trades)
        live_avg_slippage = self._calculate_avg_slippage(self._live_trades)

        # 填充率对比
        replay_fill_rate = len(self._replay_trades) / max(1, len(self._replay_trades))
        live_fill_rate = len(self._live_trades) / max(1, len(self._live_trades))

        return {
            "pnl": {
                "replay": replay_pnl,
                "live": live_pnl,
                "difference": live_pnl - replay_pnl,
            },
            "slippage": {
                "replay": replay_avg_slippage,
                "live": live_avg_slippage,
                "difference": live_avg_slippage - replay_avg_slippage,
            },
            "fill_rate": {
                "replay": replay_fill_rate,
                "live": live_fill_rate,
            },
            "trade_count": {
                "replay": len(self._replay_trades),
                "live": len(self._live_trades),
            },
        }

    def _calculate_avg_slippage(self, trades: List[Dict]) -> float:
        """计算平均滑点"""
        if not trades:
            return 0

        slippages = [t.get("slippage", 0) for t in trades if "slippage" in t]
        return sum(slippages) / len(slippages) if slippages else 0

    def generate_report(self) -> str:
        """生成报告"""
        comparison = self.compare()

        report = f"""
# 策略回放与实盘对比分析报告

## 收益对比
- 回放收益: {comparison['pnl']['replay']:.2f}
- 实盘收益: {comparison['pnl']['live']:.2f}
- 差异: {comparison['pnl']['difference']:.2f}

## 执行质量
- 回放滑点: {comparison['slippage']['replay']:.4f}%
- 实盘滑点: {comparison['slippage']['live']:.4f}%
- 滑点差异: {comparison['slippage']['difference']:.4f}%

## 成交统计
- 回放成交数: {comparison['trade_count']['replay']}
- 实盘成交数: {comparison['trade_count']['live']}
"""
        return report


# ============ 便捷函数 ============

def create_replay_engine(config: ReplayConfig = None) -> StrategyReplayEngine:
    """创建回放引擎"""
    return StrategyReplayEngine(config)


def run_backtest(
    data_source: str,
    strategy_func: Callable,
    config: ReplayConfig = None,
) -> Dict:
    """运行回测"""
    engine = StrategyReplayEngine(config)

    # 注册策略
    engine.register_tick_callback(strategy_func)

    # 加载数据
    engine.load_data(data_source)

    # 运行回放
    engine.start()

    # 等待完成
    while engine._status != ReplayStatus.COMPLETED:
        time.sleep(0.1)

    return engine.get_statistics()
