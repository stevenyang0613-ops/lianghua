"""松岗量化可转债策略 V3.0 实时流处理模块

功能:
- Flink流处理集成
- 实时行情处理
- 毫秒级信号计算
- 流式聚合
- 窗口计算
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Callable
from enum import Enum
import logging
import json
import time
import asyncio
from collections import deque

logger = logging.getLogger(__name__)

# 检查Flink是否可用
try:
    from pyflink.datastream import StreamExecutionEnvironment
    from pyflink.datastream.functions import MapFunction, FilterFunction, WindowFunction
    from pyflink.datastream.window import TumblingEventTimeWindows, SlidingEventTimeWindows
    from pyflink.common import Types, WatermarkStrategy
    FLINK_AVAILABLE = True
except ImportError:
    FLINK_AVAILABLE = False


# ============ 枚举类型 ============

class StreamType(str, Enum):
    """流类型"""
    QUOTE = "quote"           # 行情流
    TRADE = "trade"           # 成交流
    SIGNAL = "signal"         # 信号流
    POSITION = "position"     # 持仓流
    RISK = "risk"             # 风控流


class WindowType(str, Enum):
    """窗口类型"""
    TUMBLING = "tumbling"     # 滚动窗口
    SLIDING = "sliding"       # 滑动窗口
    SESSION = "session"       # 会话窗口


# ============ 配置类 ============

@dataclass
class StreamConfig:
    """流处理配置"""
    # Kafka配置
    kafka_brokers: str = "localhost:9092"
    kafka_group_id: str = "sg-strategy-group"
    kafka_auto_offset_reset: str = "latest"

    # 窗口配置
    window_size_ms: int = 5000        # 5秒窗口
    window_slide_ms: int = 1000       # 1秒滑动

    # 水印配置
    watermark_delay_ms: int = 1000    # 1秒延迟

    # 并行度
    parallelism: int = 4

    # 检查点配置
    checkpoint_interval_ms: int = 60000  # 1分钟
    checkpoint_timeout_ms: int = 600000   # 10分钟


# ============ 数据模型 ============

@dataclass
class QuoteEvent:
    """行情事件"""
    code: str
    timestamp: int
    price: float
    volume: int
    amount: float
    bid_price: float = 0.0
    ask_price: float = 0.0
    bid_volume: int = 0
    ask_volume: int = 0

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "timestamp": self.timestamp,
            "price": self.price,
            "volume": self.volume,
            "amount": self.amount,
            "bid_price": self.bid_price,
            "ask_price": self.ask_price,
        }


@dataclass
class TradeEvent:
    """成交事件"""
    trade_id: str
    code: str
    timestamp: int
    price: float
    volume: int
    side: str  # buy, sell
    amount: float

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "code": self.code,
            "timestamp": self.timestamp,
            "price": self.price,
            "volume": self.volume,
            "side": self.side,
        }


@dataclass
class SignalEvent:
    """信号事件"""
    signal_id: str
    code: str
    timestamp: int
    action: str
    quantity: int
    price: float
    confidence: float
    reason: str

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "code": self.code,
            "timestamp": self.timestamp,
            "action": self.action,
            "quantity": self.quantity,
            "price": self.price,
            "confidence": self.confidence,
        }


@dataclass
class AggregatedQuote:
    """聚合行情"""
    code: str
    window_start: int
    window_end: int
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    total_volume: int
    total_amount: float
    vwap: float
    trade_count: int

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "open": self.open_price,
            "high": self.high_price,
            "low": self.low_price,
            "close": self.close_price,
            "volume": self.total_volume,
            "amount": self.total_amount,
            "vwap": self.vwap,
            "trade_count": self.trade_count,
        }


# ============ 流处理引擎 ============

class StreamProcessor:
    """流处理引擎"""

    def __init__(self, config: StreamConfig = None):
        self.config = config or StreamConfig()
        self._env = None
        self._running = False
        self._handlers: Dict[str, List[Callable]] = {}
        self._buffers: Dict[str, deque] = {}

    def initialize(self):
        """初始化"""
        if FLINK_AVAILABLE:
            self._init_flink()
        else:
            logger.warning("[StreamProcessor] Flink不可用，使用内存流处理")

        # 初始化缓冲区
        for stream_type in StreamType:
            self._buffers[stream_type.value] = deque(maxlen=100000)

        logger.info("[StreamProcessor] 初始化完成")

    def _init_flink(self):
        """初始化Flink环境"""
        self._env = StreamExecutionEnvironment.get_execution_environment()
        self._env.set_parallelism(self.config.parallelism)

        # 启用检查点
        self._env.enable_checkpointing(self.config.checkpoint_interval_ms)

        logger.info("[StreamProcessor] Flink环境初始化完成")

    def process_quote(self, quote: QuoteEvent):
        """处理行情事件"""
        # 存入缓冲区
        self._buffers[StreamType.QUOTE.value].append(quote)

        # 触发处理器
        self._trigger_handlers(StreamType.QUOTE, quote)

    def process_trade(self, trade: TradeEvent):
        """处理成交事件"""
        self._buffers[StreamType.TRADE.value].append(trade)
        self._trigger_handlers(StreamType.TRADE, trade)

    def process_signal(self, signal: SignalEvent):
        """处理信号事件"""
        self._buffers[StreamType.SIGNAL.value].append(signal)
        self._trigger_handlers(StreamType.SIGNAL, signal)

    def register_handler(self, stream_type: StreamType, handler: Callable):
        """注册事件处理器"""
        if stream_type.value not in self._handlers:
            self._handlers[stream_type.value] = []
        self._handlers[stream_type.value].append(handler)

    def _trigger_handlers(self, stream_type: StreamType, event: Any):
        """触发处理器"""
        handlers = self._handlers.get(stream_type.value, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"[StreamProcessor] 处理器执行失败: {e}")

    def aggregate_quotes(
        self,
        code: str,
        window_ms: int = None,
    ) -> AggregatedQuote:
        """聚合行情"""
        window_ms = window_ms or self.config.window_size_ms
        buffer = self._buffers[StreamType.QUOTE.value]

        # 过滤代码和时间窗口
        now = int(time.time() * 1000)
        window_start = now - window_ms

        quotes = [
            q for q in buffer
            if q.code == code and q.timestamp >= window_start
        ]

        if not quotes:
            return None

        # 聚合计算
        prices = [q.price for q in quotes]
        volumes = [q.volume for q in quotes]
        amounts = [q.amount for q in quotes]

        return AggregatedQuote(
            code=code,
            window_start=window_start,
            window_end=now,
            open_price=prices[0],
            high_price=max(prices),
            low_price=min(prices),
            close_price=prices[-1],
            total_volume=sum(volumes),
            total_amount=sum(amounts),
            vwap=sum(amounts) / sum(volumes) if sum(volumes) > 0 else 0,
            trade_count=len(quotes),
        )

    def calculate_realtime_metrics(self, code: str) -> Dict[str, Any]:
        """计算实时指标"""
        agg = self.aggregate_quotes(code)
        if not agg:
            return {}

        # 计算动量
        momentum = (agg.close_price - agg.open_price) / agg.open_price if agg.open_price > 0 else 0

        # 计算波动率
        buffer = self._buffers[StreamType.QUOTE.value]
        quotes = [q for q in buffer if q.code == code][-100:]
        if len(quotes) > 1:
            prices = [q.price for q in quotes]
            returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
            volatility = (sum(r**2 for r in returns) / len(returns)) ** 0.5 if returns else 0
        else:
            volatility = 0

        return {
            "code": code,
            "price": agg.close_price,
            "momentum": momentum,
            "volatility": volatility,
            "volume": agg.total_volume,
            "vwap": agg.vwap,
            "trade_count": agg.trade_count,
            "timestamp": datetime.now().isoformat(),
        }

    def start(self):
        """启动流处理"""
        self._running = True
        logger.info("[StreamProcessor] 流处理启动")

    def stop(self):
        """停止流处理"""
        self._running = False
        logger.info("[StreamProcessor] 流处理停止")

    def get_stats(self) -> Dict[str, int]:
        """获取统计"""
        return {
            stream_type: len(buffer)
            for stream_type, buffer in self._buffers.items()
        }


# ============ 实时信号生成器 ============

class RealtimeSignalGenerator:
    """实时信号生成器"""

    def __init__(self, processor: StreamProcessor = None):
        self.processor = processor or StreamProcessor()
        self._signal_handlers: List[Callable] = []

    def initialize(self):
        """初始化"""
        self.processor.initialize()

        # 注册行情处理器
        self.processor.register_handler(StreamType.QUOTE, self._on_quote)

        logger.info("[RealtimeSignalGenerator] 初始化完成")

    def _on_quote(self, quote: QuoteEvent):
        """行情事件处理"""
        # 计算实时指标
        metrics = self.processor.calculate_realtime_metrics(quote.code)

        if not metrics:
            return

        # 简单信号逻辑
        signal = self._evaluate_signal(quote, metrics)

        if signal:
            self._emit_signal(signal)

    def _evaluate_signal(self, quote: QuoteEvent, metrics: Dict) -> Optional[SignalEvent]:
        """评估信号"""
        momentum = metrics.get("momentum", 0)
        volatility = metrics.get("volatility", 0)

        # 简单策略：动量突破
        if momentum > 0.02 and volatility < 0.03:
            return SignalEvent(
                signal_id=f"sig_{int(time.time()*1000)}_{quote.code}",
                code=quote.code,
                timestamp=int(time.time() * 1000),
                action="buy",
                quantity=1000,
                price=quote.price,
                confidence=min(0.9, momentum * 10),
                reason=f"动量突破: {momentum*100:.2f}%",
            )

        elif momentum < -0.02:
            return SignalEvent(
                signal_id=f"sig_{int(time.time()*1000)}_{quote.code}",
                code=quote.code,
                timestamp=int(time.time() * 1000),
                action="sell",
                quantity=1000,
                price=quote.price,
                confidence=min(0.9, abs(momentum) * 10),
                reason=f"动量跌破: {momentum*100:.2f}%",
            )

        return None

    def _emit_signal(self, signal: SignalEvent):
        """发射信号"""
        self.processor.process_signal(signal)

        # 通知处理器
        for handler in self._signal_handlers:
            try:
                handler(signal)
            except Exception as e:
                logger.error(f"[RealtimeSignalGenerator] 信号处理失败: {e}")

    def on_signal(self, handler: Callable):
        """注册信号处理器"""
        self._signal_handlers.append(handler)

    def start(self):
        """启动"""
        self.processor.start()

    def stop(self):
        """停止"""
        self.processor.stop()


# ============ Kafka集成 ============

class KafkaStreamConsumer:
    """Kafka流消费者"""

    def __init__(self, config: StreamConfig = None):
        self.config = config or StreamConfig()
        self._consumer = None
        self._running = False

    def connect(self):
        """连接Kafka"""
        try:
            from kafka import KafkaConsumer

            self._consumer = KafkaConsumer(
                bootstrap_servers=self.config.kafka_brokers,
                group_id=self.config.kafka_group_id,
                auto_offset_reset=self.config.kafka_auto_offset_reset,
                value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            )

            logger.info(f"[Kafka] 连接成功: {self.config.kafka_brokers}")
            return True

        except ImportError:
            logger.warning("[Kafka] kafka-python未安装")
            return False
        except Exception as e:
            logger.error(f"[Kafka] 连接失败: {e}")
            return False

    def subscribe(self, topics: List[str]):
        """订阅主题"""
        if self._consumer:
            self._consumer.subscribe(topics)
            logger.info(f"[Kafka] 订阅主题: {topics}")

    def consume(self, handler: Callable):
        """消费消息"""
        if not self._consumer:
            return

        self._running = True

        try:
            for message in self._consumer:
                if not self._running:
                    break

                try:
                    handler(message.value)
                except Exception as e:
                    logger.error(f"[Kafka] 消息处理失败: {e}")

        except Exception as e:
            logger.error(f"[Kafka] 消费异常: {e}")

    def stop(self):
        """停止"""
        self._running = False
        if self._consumer:
            self._consumer.close()


class KafkaStreamProducer:
    """Kafka流生产者"""

    def __init__(self, config: StreamConfig = None):
        self.config = config or StreamConfig()
        self._producer = None

    def connect(self):
        """连接Kafka"""
        try:
            from kafka import KafkaProducer

            self._producer = KafkaProducer(
                bootstrap_servers=self.config.kafka_brokers,
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            )

            logger.info(f"[Kafka] 生产者连接成功")
            return True

        except ImportError:
            logger.warning("[Kafka] kafka-python未安装")
            return False
        except Exception as e:
            logger.error(f"[Kafka] 生产者连接失败: {e}")
            return False

    def send(self, topic: str, message: Dict):
        """发送消息"""
        if not self._producer:
            return False

        try:
            self._producer.send(topic, message)
            self._producer.flush()
            return True
        except Exception as e:
            logger.error(f"[Kafka] 发送失败: {e}")
            return False

    def close(self):
        """关闭"""
        if self._producer:
            self._producer.close()


# ============ 便捷函数 ============

def get_stream_processor(config: StreamConfig = None) -> StreamProcessor:
    """获取流处理器"""
    return StreamProcessor(config)


def get_realtime_signal_generator() -> RealtimeSignalGenerator:
    """获取实时信号生成器"""
    return RealtimeSignalGenerator()


def init_streaming(
    kafka_brokers: str = "localhost:9092",
    parallelism: int = 4,
) -> StreamProcessor:
    """初始化流处理"""
    config = StreamConfig(
        kafka_brokers=kafka_brokers,
        parallelism=parallelism,
    )
    processor = StreamProcessor(config)
    processor.initialize()
    return processor
