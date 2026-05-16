"""异常交易检测"""
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict, deque
import statistics


class AnomalyType(Enum):
    """异常类型"""
    VOLUME_SPIKE = "volume_spike"          # 交易量激增
    PRICE_MANIPULATION = "price_manipulation"  # 价格操纵
    WASH_TRADING = "wash_trading"          # 对倒交易
    SPOOFING = "spoofing"                  # 虚假报价
    LAYERING = "layering"                  # 分层挂单
    FRONT_RUNNING = "front_running"        # 抢先交易
    UNUSUAL_TIMING = "unusual_timing"      # 异常时间交易
    UNUSUAL_SIZE = "unusual_size"          # 异常交易规模
    RAPID_TRADING = "rapid_trading"        # 快速交易
    COORDINATED_TRADING = "coordinated_trading"  # 协同交易


class AnomalySeverity(Enum):
    """异常严重程度"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class TradingPattern:
    """交易模式"""
    trader_id: str
    symbol: str
    avg_volume: float
    avg_frequency: float
    typical_times: List[int]  # 通常交易的小时
    typical_sizes: List[float]
    price_sensitivity: float
    history_length: int


@dataclass
class Anomaly:
    """异常记录"""
    anomaly_id: str
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    trader_id: str
    symbol: str
    description: str
    evidence: Dict
    detected_at: datetime
    confidence: float
    status: str = "detected"
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    resolution: str = ""


class AnomalyDetector:
    """异常检测器"""
    
    def __init__(self):
        # 交易模式库
        self.patterns: Dict[str, TradingPattern] = {}
        
        # 异常记录
        self.anomalies: List[Anomaly] = []
        
        # 实时数据
        self.recent_trades: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.recent_orders: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        
        # 检测参数
        self.thresholds = {
            'volume_spike_zscore': 3.0,
            'rapid_trading_count': 20,
            'rapid_trading_window_seconds': 60,
            'wash_trade_similarity': 0.9,
            'unusual_size_zscore': 2.5,
            'spoof_cancel_rate': 0.8,
        }
        
        # 历史统计
        self.volume_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self.price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
    
    def update_pattern(self, trader_id: str, symbol: str, trades: List[Dict]):
        """更新交易模式"""
        if not trades:
            return
        
        volumes = [t['quantity'] * t.get('price', 1) for t in trades]
        times = [t['timestamp'].hour for t in trades if 'timestamp' in t]
        
        pattern = TradingPattern(
            trader_id=trader_id,
            symbol=symbol,
            avg_volume=statistics.mean(volumes) if volumes else 0,
            avg_frequency=len(trades) / 30 if trades else 0,  # 日均交易次数
            typical_times=list(set(times)) if times else [],
            typical_sizes=sorted(volumes)[:10] if volumes else [],
            price_sensitivity=0.5,  # 默认值
            history_length=len(trades)
        )
        
        key = f"{trader_id}_{symbol}"
        self.patterns[key] = pattern
    
    def detect(self, trade: Dict) -> List[Anomaly]:
        """检测异常"""
        anomalies = []
        
        trader_id = trade.get('trader_id', '')
        symbol = trade.get('symbol', '')
        
        # 记录交易
        trade_key = f"{trader_id}_{symbol}"
        self.recent_trades[trade_key].append(trade)
        
        # 更新历史
        volume = trade['quantity'] * trade.get('price', 1)
        self.volume_history[symbol].append(volume)
        
        # 执行各种检测
        anomalies.extend(self._detect_volume_spike(trade))
        anomalies.extend(self._detect_rapid_trading(trade))
        anomalies.extend(self._detect_unusual_size(trade))
        anomalies.extend(self._detect_unusual_timing(trade))
        anomalies.extend(self._detect_wash_trading(trade))
        anomalies.extend(self._detect_spoofing(trade))
        
        # 记录异常
        for anomaly in anomalies:
            self.anomalies.append(anomaly)
        
        return anomalies
    
    def _detect_volume_spike(self, trade: Dict) -> List[Anomaly]:
        """检测交易量激增"""
        anomalies = []
        symbol = trade.get('symbol', '')
        
        history = list(self.volume_history[symbol])
        
        if len(history) < 10:
            return anomalies
        
        current_volume = trade['quantity'] * trade.get('price', 1)
        
        mean_vol = statistics.mean(history)
        std_vol = statistics.stdev(history) if len(history) > 1 else 0
        
        if std_vol > 0:
            zscore = (current_volume - mean_vol) / std_vol
            
            if zscore > self.thresholds['volume_spike_zscore']:
                anomalies.append(Anomaly(
                    anomaly_id=f"anom_{int(datetime.now().timestamp() * 1000000)}",
                    anomaly_type=AnomalyType.VOLUME_SPIKE,
                    severity=AnomalySeverity.HIGH if zscore > 5 else AnomalySeverity.MEDIUM,
                    trader_id=trade.get('trader_id', ''),
                    symbol=symbol,
                    description=f"交易量异常激增，Z-score: {zscore:.2f}",
                    evidence={
                        'current_volume': current_volume,
                        'avg_volume': mean_vol,
                        'zscore': zscore
                    },
                    detected_at=datetime.now(),
                    confidence=min(zscore / 5, 1.0)
                ))
        
        return anomalies
    
    def _detect_rapid_trading(self, trade: Dict) -> List[Anomaly]:
        """检测快速交易"""
        anomalies = []
        trader_id = trade.get('trader_id', '')
        symbol = trade.get('symbol', '')
        trade_key = f"{trader_id}_{symbol}"
        
        recent = list(self.recent_trades[trade_key])
        
        if len(recent) < self.thresholds['rapid_trading_count']:
            return anomalies
        
        # 检查时间窗口内的交易次数
        now = trade.get('timestamp', datetime.now())
        if isinstance(now, str):
            now = datetime.fromisoformat(now)
        
        window_start = now - timedelta(seconds=self.thresholds['rapid_trading_window_seconds'])
        
        recent_count = sum(
            1 for t in recent
            if t.get('timestamp', datetime.min) > window_start
        )
        
        if recent_count >= self.thresholds['rapid_trading_count']:
            anomalies.append(Anomaly(
                anomaly_id=f"anom_{int(datetime.now().timestamp() * 1000000)}",
                anomaly_type=AnomalyType.RAPID_TRADING,
                severity=AnomalySeverity.HIGH,
                trader_id=trader_id,
                symbol=symbol,
                description=f"短时间内频繁交易: {recent_count}次/{self.thresholds['rapid_trading_window_seconds']}秒",
                evidence={
                    'trade_count': recent_count,
                    'window_seconds': self.thresholds['rapid_trading_window_seconds']
                },
                detected_at=datetime.now(),
                confidence=0.9
            ))
        
        return anomalies
    
    def _detect_unusual_size(self, trade: Dict) -> List[Anomaly]:
        """检测异常交易规模"""
        anomalies = []
        trader_id = trade.get('trader_id', '')
        symbol = trade.get('symbol', '')
        
        pattern_key = f"{trader_id}_{symbol}"
        pattern = self.patterns.get(pattern_key)
        
        if not pattern or pattern.history_length < 10:
            return anomalies
        
        current_size = trade['quantity'] * trade.get('price', 1)
        avg_size = pattern.avg_volume
        
        if avg_size > 0:
            ratio = current_size / avg_size
            
            if ratio > 5:  # 超过平均5倍
                anomalies.append(Anomaly(
                    anomaly_id=f"anom_{int(datetime.now().timestamp() * 1000000)}",
                    anomaly_type=AnomalyType.UNUSUAL_SIZE,
                    severity=AnomalySeverity.MEDIUM if ratio < 10 else AnomalySeverity.HIGH,
                    trader_id=trader_id,
                    symbol=symbol,
                    description=f"交易规模异常，是平均的{ratio:.1f}倍",
                    evidence={
                        'current_size': current_size,
                        'avg_size': avg_size,
                        'ratio': ratio
                    },
                    detected_at=datetime.now(),
                    confidence=min(ratio / 10, 1.0)
                ))
        
        return anomalies
    
    def _detect_unusual_timing(self, trade: Dict) -> List[Anomaly]:
        """检测异常交易时间"""
        anomalies = []
        trader_id = trade.get('trader_id', '')
        symbol = trade.get('symbol', '')
        
        pattern_key = f"{trader_id}_{symbol}"
        pattern = self.patterns.get(pattern_key)
        
        if not pattern or not pattern.typical_times:
            return anomalies
        
        trade_time = trade.get('timestamp', datetime.now())
        if isinstance(trade_time, str):
            trade_time = datetime.fromisoformat(trade_time)
        
        hour = trade_time.hour
        
        # 检查是否在非典型时间交易
        if hour not in pattern.typical_times:
            # 检查是否在非常规交易时间
            if hour < 9 or hour > 15:
                anomalies.append(Anomaly(
                    anomaly_id=f"anom_{int(datetime.now().timestamp() * 1000000)}",
                    anomaly_type=AnomalyType.UNUSUAL_TIMING,
                    severity=AnomalySeverity.LOW,
                    trader_id=trader_id,
                    symbol=symbol,
                    description=f"在非常规时间{hour}:00交易",
                    evidence={
                        'trade_hour': hour,
                        'typical_hours': pattern.typical_times
                    },
                    detected_at=datetime.now(),
                    confidence=0.7
                ))
        
        return anomalies
    
    def _detect_wash_trading(self, trade: Dict) -> List[Anomaly]:
        """检测对倒交易"""
        anomalies = []
        trader_id = trade.get('trader_id', '')
        symbol = trade.get('symbol', '')
        trade_key = f"{trader_id}_{symbol}"
        
        recent = list(self.recent_trades[trade_key])
        
        if len(recent) < 4:
            return anomalies
        
        # 检查是否有相近时间、相近数量、相反方向的交易
        current_side = trade.get('side', '')
        current_qty = trade.get('quantity', 0)
        current_time = trade.get('timestamp', datetime.now())
        
        for prev_trade in recent[-10:]:
            if prev_trade.get('side', '') != current_side:
                qty_ratio = min(current_qty, prev_trade.get('quantity', 0)) / max(current_qty, prev_trade.get('quantity', 1))
                
                if qty_ratio > self.thresholds['wash_trade_similarity']:
                    time_diff = abs((current_time - prev_trade.get('timestamp', datetime.min)).total_seconds())
                    
                    if time_diff < 60:  # 1分钟内
                        anomalies.append(Anomaly(
                            anomaly_id=f"anom_{int(datetime.now().timestamp() * 1000000)}",
                            anomaly_type=AnomalyType.WASH_TRADING,
                            severity=AnomalySeverity.HIGH,
                            trader_id=trader_id,
                            symbol=symbol,
                            description="疑似对倒交易：短时间内有相近数量的买卖",
                            evidence={
                                'buy_qty': max(current_qty, prev_trade.get('quantity', 0)),
                                'sell_qty': min(current_qty, prev_trade.get('quantity', 0)),
                                'time_diff_seconds': time_diff,
                                'similarity': qty_ratio
                            },
                            detected_at=datetime.now(),
                            confidence=qty_ratio
                        ))
                        break
        
        return anomalies
    
    def _detect_spoofing(self, trade: Dict) -> List[Anomaly]:
        """检测虚假报价"""
        anomalies = []
        trader_id = trade.get('trader_id', '')
        symbol = trade.get('symbol', '')
        
        order_key = f"{trader_id}_{symbol}"
        recent_orders = list(self.recent_orders[order_key])
        
        if len(recent_orders) < 10:
            return anomalies
        
        # 检查撤单率
        total_orders = len(recent_orders)
        cancelled_orders = sum(1 for o in recent_orders if o.get('status') == 'cancelled')
        
        cancel_rate = cancelled_orders / total_orders if total_orders > 0 else 0
        
        if cancel_rate > self.thresholds['spoof_cancel_rate']:
            anomalies.append(Anomaly(
                anomaly_id=f"anom_{int(datetime.now().timestamp() * 1000000)}",
                anomaly_type=AnomalyType.SPOOFING,
                severity=AnomalySeverity.HIGH,
                trader_id=trader_id,
                symbol=symbol,
                description=f"高撤单率疑似虚假报价: {cancel_rate:.1%}",
                evidence={
                    'total_orders': total_orders,
                    'cancelled_orders': cancelled_orders,
                    'cancel_rate': cancel_rate
                },
                detected_at=datetime.now(),
                confidence=cancel_rate
            ))
        
        return anomalies
    
    def record_order(self, order: Dict):
        """记录订单"""
        trader_id = order.get('trader_id', '')
        symbol = order.get('symbol', '')
        order_key = f"{trader_id}_{symbol}"
        
        self.recent_orders[order_key].append(order)
    
    def get_anomalies(
        self,
        trader_id: str = None,
        symbol: str = None,
        anomaly_type: AnomalyType = None,
        severity: AnomalySeverity = None,
        days: int = 30
    ) -> List[Anomaly]:
        """获取异常记录"""
        cutoff = datetime.now() - timedelta(days=days)
        
        result = [
            a for a in self.anomalies
            if a.detected_at >= cutoff
        ]
        
        if trader_id:
            result = [a for a in result if a.trader_id == trader_id]
        
        if symbol:
            result = [a for a in result if a.symbol == symbol]
        
        if anomaly_type:
            result = [a for a in result if a.anomaly_type == anomaly_type]
        
        if severity:
            result = [a for a in result if a.severity == severity]
        
        return result
    
    def get_anomaly_statistics(self, days: int = 30) -> Dict:
        """获取异常统计"""
        anomalies = self.get_anomalies(days=days)
        
        by_type = defaultdict(int)
        by_severity = defaultdict(int)
        by_trader = defaultdict(int)
        
        for anomaly in anomalies:
            by_type[anomaly.anomaly_type.value] += 1
            by_severity[anomaly.severity.value] += 1
            by_trader[anomaly.trader_id] += 1
        
        return {
            'total': len(anomalies),
            'by_type': dict(by_type),
            'by_severity': dict(by_severity),
            'top_traders': sorted(by_trader.items(), key=lambda x: x[1], reverse=True)[:10]
        }
    
    def review_anomaly(self, anomaly_id: str, reviewer: str, resolution: str):
        """审核异常"""
        for anomaly in self.anomalies:
            if anomaly.anomaly_id == anomaly_id:
                anomaly.status = "reviewed"
                anomaly.reviewed_at = datetime.now()
                anomaly.reviewed_by = reviewer
                anomaly.resolution = resolution
                break
    
    def set_threshold(self, name: str, value: float):
        """设置检测阈值"""
        self.thresholds[name] = value
