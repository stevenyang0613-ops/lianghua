"""延迟监控优化"""
import time
import threading
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque
from enum import Enum
import statistics
import logging
logger = logging.getLogger(__name__)


class LatencyType(Enum):
    """延迟类型"""
    NETWORK = "network"
    PROCESSING = "processing"
    ORDER_SUBMISSION = "order_submission"
    ORDER_EXECUTION = "order_execution"
    MARKET_DATA = "market_data"
    SIGNAL_GENERATION = "signal_generation"
    END_TO_END = "end_to_end"


@dataclass
class LatencyMeasurement:
    """延迟测量"""
    measurement_id: str
    latency_type: LatencyType
    value_us: float  # 微秒
    timestamp: datetime
    metadata: Dict = field(default_factory=dict)


@dataclass
class LatencyStats:
    """延迟统计"""
    latency_type: LatencyType
    count: int
    min_us: float
    max_us: float
    mean_us: float
    median_us: float
    p95_us: float
    p99_us: float
    std_us: float
    timestamp: datetime = field(default_factory=datetime.now)


class LatencyMonitor:
    """延迟监控器"""
    
    def __init__(self, history_size: int = 100000):
        self.history_size = history_size
        
        # 延迟历史
        self.latency_history: Dict[LatencyType, deque] = {
            lt: deque(maxlen=history_size) for lt in LatencyType
        }
        
        # 实时统计
        self.current_stats: Dict[LatencyType, LatencyStats] = {}
        
        # 告警阈值（微秒）
        self.alert_thresholds: Dict[LatencyType, float] = {
            LatencyType.NETWORK: 1000,
            LatencyType.PROCESSING: 500,
            LatencyType.ORDER_SUBMISSION: 100,
            LatencyType.ORDER_EXECUTION: 1000,
            LatencyType.MARKET_DATA: 100,
            LatencyType.SIGNAL_GENERATION: 1000,
            LatencyType.END_TO_END: 5000,
        }
        
        # 告警回调
        self.alert_callbacks: List[Callable] = []
        
        # 监控线程
        self._monitoring = False
        self._monitor_thread = None
    
    def start_monitoring(self, interval_seconds: float = 1.0):
        """启动监控"""
        self._monitoring = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(interval_seconds,),
            daemon=True
        )
        self._monitor_thread.start()
    
    def stop_monitoring(self):
        """停止监控"""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
    
    def record(
        self,
        latency_type: LatencyType,
        value_us: float,
        metadata: Dict = None
    ):
        """记录延迟"""
        measurement = LatencyMeasurement(
            measurement_id=f"lat_{int(time.time() * 1000000)}",
            latency_type=latency_type,
            value_us=value_us,
            timestamp=datetime.now(),
            metadata=metadata or {}
        )
        
        self.latency_history[latency_type].append(measurement)
        
        # 检查告警
        if value_us > self.alert_thresholds.get(latency_type, float('inf')):
            self._trigger_alert(latency_type, value_us)
    
    def record_with_timer(
        self,
        latency_type: LatencyType,
        start_time_ns: int,
        metadata: Dict = None
    ):
        """使用计时器记录延迟"""
        end_time_ns = time.perf_counter_ns()
        value_us = (end_time_ns - start_time_ns) / 1000
        self.record(latency_type, value_us, metadata)
    
    def start_timer(self) -> int:
        """开始计时"""
        return time.perf_counter_ns()
    
    def measure(
        self,
        latency_type: LatencyType
    ) -> 'LatencyContext':
        """延迟测量上下文"""
        return LatencyContext(self, latency_type)
    
    def get_stats(self, latency_type: LatencyType) -> Optional[LatencyStats]:
        """获取统计"""
        history = list(self.latency_history[latency_type])
        
        if not history:
            return None
        
        values = [m.value_us for m in history]
        sorted_values = sorted(values)
        
        n = len(values)
        
        return LatencyStats(
            latency_type=latency_type,
            count=n,
            min_us=min(values),
            max_us=max(values),
            mean_us=statistics.mean(values),
            median_us=statistics.median(values),
            p95_us=sorted_values[int(n * 0.95)] if n >= 20 else sorted_values[-1],
            p99_us=sorted_values[int(n * 0.99)] if n >= 100 else sorted_values[-1],
            std_us=statistics.stdev(values) if n > 1 else 0
        )
    
    def get_all_stats(self) -> Dict[LatencyType, LatencyStats]:
        """获取所有统计"""
        return {lt: self.get_stats(lt) for lt in LatencyType if self.latency_history[lt]}
    
    def get_latency_distribution(
        self,
        latency_type: LatencyType,
        buckets: List[float] = None
    ) -> Dict[str, int]:
        """获取延迟分布"""
        if buckets is None:
            buckets = [10, 50, 100, 500, 1000, 5000, 10000, 50000]
        
        history = list(self.latency_history[latency_type])
        
        if not history:
            return {}
        
        values = [m.value_us for m in history]
        
        distribution = {}
        prev_bucket = 0
        
        for bucket in buckets:
            count = sum(1 for v in values if prev_bucket <= v < bucket)
            distribution[f"{prev_bucket}-{bucket}us"] = count
            prev_bucket = bucket
        
        distribution[f">{buckets[-1]}us"] = sum(1 for v in values if v >= buckets[-1])
        
        return distribution
    
    def get_percentile_trend(
        self,
        latency_type: LatencyType,
        window_size: int = 100
    ) -> Dict[str, List[float]]:
        """获取百分位趋势"""
        history = list(self.latency_history[latency_type])
        
        if len(history) < window_size:
            return {}
        
        p50_trend = []
        p95_trend = []
        p99_trend = []
        
        for i in range(window_size, len(history)):
            window = [m.value_us for m in history[i-window_size:i]]
            sorted_window = sorted(window)
            n = len(sorted_window)
            
            p50_trend.append(sorted_window[n // 2])
            p95_trend.append(sorted_window[int(n * 0.95)])
            p99_trend.append(sorted_window[int(n * 0.99)])
        
        return {
            'p50': p50_trend,
            'p95': p95_trend,
            'p99': p99_trend
        }
    
    def identify_bottlenecks(self) -> List[Dict]:
        """识别瓶颈"""
        bottlenecks = []
        
        for latency_type in LatencyType:
            stats = self.get_stats(latency_type)
            
            if not stats:
                continue
            
            threshold = self.alert_thresholds.get(latency_type, float('inf'))
            
            if stats.p99_us > threshold:
                bottlenecks.append({
                    'type': latency_type.value,
                    'p99_us': stats.p99_us,
                    'threshold_us': threshold,
                    'impact': 'high' if stats.p99_us > threshold * 2 else 'medium',
                    'recommendation': self._get_optimization_recommendation(latency_type, stats)
                })
        
        return sorted(bottlenecks, key=lambda x: x['p99_us'], reverse=True)
    
    def _get_optimization_recommendation(self, latency_type: LatencyType, stats: LatencyStats) -> str:
        """获取优化建议"""
        recommendations = {
            LatencyType.NETWORK: "考虑使用更近的机房或优化网络路由",
            LatencyType.PROCESSING: "优化算法复杂度或使用更快的硬件",
            LatencyType.ORDER_SUBMISSION: "优化订单提交逻辑，减少不必要的验证",
            LatencyType.ORDER_EXECUTION: "考虑使用更快的交易通道",
            LatencyType.MARKET_DATA: "优化行情处理流水线",
            LatencyType.SIGNAL_GENERATION: "简化信号生成逻辑或使用增量计算",
            LatencyType.END_TO_END: "识别并优化关键路径上的瓶颈",
        }
        
        return recommendations.get(latency_type, "分析具体延迟来源")
    
    def _monitor_loop(self, interval_seconds: float):
        """监控循环"""
        while self._monitoring:
            # 更新统计
            for latency_type in LatencyType:
                stats = self.get_stats(latency_type)
                if stats:
                    self.current_stats[latency_type] = stats
            
            time.sleep(interval_seconds)
    
    def _trigger_alert(self, latency_type: LatencyType, value_us: float):
        """触发告警"""
        alert = {
            'type': latency_type.value,
            'value_us': value_us,
            'threshold_us': self.alert_thresholds[latency_type],
            'timestamp': datetime.now().isoformat()
        }
        
        for callback in self.alert_callbacks:
            try:
                callback(alert)
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
                pass
    
    def add_alert_callback(self, callback: Callable):
        """添加告警回调"""
        self.alert_callbacks.append(callback)
    
    def set_threshold(self, latency_type: LatencyType, threshold_us: float):
        """设置阈值"""
        self.alert_thresholds[latency_type] = threshold_us
    
    def export_metrics(self) -> Dict:
        """导出指标"""
        stats = self.get_all_stats()
        
        return {
            'latency_stats': {
                lt.value: {
                    'mean_us': s.mean_us,
                    'p95_us': s.p95_us,
                    'p99_us': s.p99_us,
                    'count': s.count
                }
                for lt, s in stats.items() if s
            },
            'bottlenecks': self.identify_bottlenecks(),
            'timestamp': datetime.now().isoformat()
        }


class LatencyContext:
    """延迟测量上下文"""
    
    def __init__(self, monitor: LatencyMonitor, latency_type: LatencyType):
        self.monitor = monitor
        self.latency_type = latency_type
        self.start_time_ns = None
    
    def __enter__(self):
        self.start_time_ns = time.perf_counter_ns()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        end_time_ns = time.perf_counter_ns()
        value_us = (end_time_ns - self.start_time_ns) / 1000
        self.monitor.record(self.latency_type, value_us)
        return False


class LatencyOptimizer:
    """延迟优化器"""
    
    def __init__(self, monitor: LatencyMonitor):
        self.monitor = monitor
    
    def analyze_slow_path(self, latency_type: LatencyType) -> Dict:
        """分析慢路径"""
        history = list(self.monitor.latency_history[latency_type])
        
        if not history:
            return {}
        
        # 按时间分组
        time_groups = {}
        for measurement in history:
            hour = measurement.timestamp.hour
            if hour not in time_groups:
                time_groups[hour] = []
            time_groups[hour].append(measurement.value_us)
        
        # 找出延迟较高的时段
        hourly_avg = {h: statistics.mean(v) for h, v in time_groups.items()}
        overall_avg = statistics.mean([m.value_us for m in history])
        
        slow_hours = {h: avg for h, avg in hourly_avg.items() if avg > overall_avg * 1.5}
        
        return {
            'overall_avg_us': overall_avg,
            'hourly_avg_us': hourly_avg,
            'slow_hours': slow_hours,
            'recommendation': '在慢时段考虑降低交易频率或增加资源'
        }
    
    def suggest_optimizations(self) -> List[Dict]:
        """优化建议"""
        bottlenecks = self.monitor.identify_bottlenecks()
        suggestions = []
        
        for bottleneck in bottlenecks:
            latency_type = LatencyType(bottleneck['type'])
            
            suggestion = {
                'type': bottleneck['type'],
                'current_p99_us': bottleneck['p99_us'],
                'target_us': self.monitor.alert_thresholds.get(latency_type, 0),
                'improvements': []
            }
            
            # 根据类型给出具体建议
            if latency_type == LatencyType.NETWORK:
                suggestion['improvements'] = [
                    '使用专线或VPN',
                    '部署到交易所机房',
                    '启用TCP快速打开',
                    '压缩数据传输'
                ]
            elif latency_type == LatencyType.PROCESSING:
                suggestion['improvements'] = [
                    '使用Cython或Rust重写热点代码',
                    '启用JIT编译',
                    '优化数据结构',
                    '并行化处理'
                ]
            elif latency_type == LatencyType.ORDER_SUBMISSION:
                suggestion['improvements'] = [
                    '预构建订单消息',
                    '减少订单验证步骤',
                    '使用异步IO',
                    '批量提交订单'
                ]
            
            suggestions.append(suggestion)
        
        return suggestions
