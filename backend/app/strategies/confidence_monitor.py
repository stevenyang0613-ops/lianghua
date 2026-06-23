"""
置信度分布退化检测器

问题：当数据源大面积失效时，所有大类得分退化为中性默认值 50，
但综合得分看起来仍然"正常"。此时用户无法察觉模型已变成盲人。

方案：追踪各子因子置信度的分布，用 PSI（Population Stability Index）
检测分布从"健康"到"退化"的偏移，并提供 health_score 供仓位调整参考。
"""
import math
import logging
from collections import deque
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── PSI 阈值定义 ──
PSI_NO_CHANGE = 0.10       # < 0.10: 分布无显著变化
PSI_MODERATE = 0.25        # 0.10-0.25: 中度偏移，建议关注
# > 0.25: 显著偏移，建议降仓或告警

# 置信度分桶边界（用于 PSI 计算）
# 0-0.3=数据缺失, 0.3-0.7=部分可靠, 0.7-0.95=可靠, 0.95-1.0=非常可靠
CONFIDENCE_BUCKETS = [0.0, 0.3, 0.7, 0.95, 1.001]


class ConfidenceMonitor:
    """追踪置信度分布，检测退化偏移

    用法：
        monitor = ConfidenceMonitor(window=60)
        # 每次模型计算后传入所有子因子的置信度
        monitor.update([0.95, 0.88, 0.72, 0.60, ...])
        health = monitor.health_score  # 0.0-1.0
        alert = monitor.get_alert()    # 退化告警信息
    """

    def __init__(self, window: int = 60, psi_threshold: float = PSI_MODERATE):
        """
        Args:
            window: 滚动窗口大小（交易日数），用于构建参考分布
            psi_threshold: PSI 告警阈值，超过此值触发 alert
        """
        self._window = window
        self._psi_threshold = psi_threshold

        # 参考分布：滚动窗口中所有子因子置信度的扁平化列表
        self._reference_buffer: deque = deque(maxlen=window * 50)  # 估计每轮~50个因子

        # 当前轮置信度列表（未提交到 buffer）
        self._current_batch: List[float] = []

        # 历史 health_score
        self._health_history: deque = deque(maxlen=10)

        # 连续告警天数
        self._alert_days: int = 0

    # ── 公开接口 ──

    def update(self, confidences: List[float]) -> None:
        """提交本轮所有子因子的置信度

        Args:
            confidences: 本轮所有子因子的置信度列表（0-1 之间的浮点数）
        """
        # 过滤无效值
        valid = [c for c in confidences if isinstance(c, (int, float)) and 0 <= c <= 1]
        if not valid:
            return

        self._current_batch = valid

        # 当参考分布足够大时才计算 PSI
        if len(self._reference_buffer) < 50:
            # 冷启动阶段：直接填充参考分布
            self._reference_buffer.extend(valid)
            self._health_history.append(1.0)
            return

        # 计算当前批次的分布
        current_dist = self._bucket_distribution(valid)

        # 计算参考分布
        ref_sample = list(self._reference_buffer)[-min(len(self._reference_buffer), 500):]
        ref_dist = self._bucket_distribution(ref_sample)

        # 计算 PSI
        psi = self._psi(ref_dist, current_dist)

        # 计算 health_score
        health = self._psi_to_health(psi)
        self._health_history.append(health)

        # 更新告警计数器
        if psi > self._psi_threshold:
            self._alert_days += 1
        else:
            self._alert_days = 0

        # 将本轮置信度加入参考分布
        self._reference_buffer.extend(valid)

    def reset(self) -> None:
        """重置监控状态"""
        self._reference_buffer.clear()
        self._current_batch = []
        self._health_history.clear()
        self._alert_days = 0

    # ── 属性 ──

    @property
    def health_score(self) -> float:
        """综合健康度 0.0-1.0

        1.0 = 完全健康，分布无偏移
        0.0 = 完全退化，所有因子置信度极低
        """
        if not self._health_history:
            return 1.0
        # 取最近几轮的平均值，平滑单次波动
        return sum(self._health_history) / len(self._health_history)

    @property
    def psi(self) -> Optional[float]:
        """最近一轮的 PSI 值，None 表示数据不足"""
        if len(self._reference_buffer) < 50 or not self._current_batch:
            return None
        ref_sample = list(self._reference_buffer)[-min(len(self._reference_buffer), 500):]
        return self._psi(
            self._bucket_distribution(ref_sample),
            self._bucket_distribution(self._current_batch),
        )

    @property
    def alert_days(self) -> int:
        """连续告警天数"""
        return self._alert_days

    def get_alert(self) -> Optional[Dict]:
        """退化告警信息

        Returns:
            None 表示健康，Dict 表示告警
        """
        psi = self.psi
        if psi is None:
            return None
        if psi <= self._psi_threshold and self._alert_days == 0:
            return None

        severity = (
            "严重退化" if psi > PSI_MODERATE * 2
            else "中度退化" if psi > PSI_MODERATE
            else "轻度退化"
        )
        return {
            "type": "confidence_degradation",
            "severity": severity,
            "psi": round(psi, 4),
            "health_score": round(self.health_score, 3),
            "alert_days": self._alert_days,
            "message": (
                f"置信度分布{severity}（PSI={psi:.3f}，"
                f"连续{self._alert_days}天），"
                f"建议检查数据源可用性或降低仓位比例"
            ),
        }

    # ── 内部方法 ──

    @staticmethod
    def _bucket_distribution(values: List[float]) -> List[float]:
        """将置信度值分配到分桶，返回各桶占比（百分比 0-100）"""
        if not values:
            return [0.0] * (len(CONFIDENCE_BUCKETS) - 1)

        counts = [0] * (len(CONFIDENCE_BUCKETS) - 1)
        for v in values:
            for i in range(len(CONFIDENCE_BUCKETS) - 1):
                if CONFIDENCE_BUCKETS[i] <= v < CONFIDENCE_BUCKETS[i + 1]:
                    counts[i] += 1
                    break

        total = len(values)
        return [c / total * 100.0 for c in counts]

    @staticmethod
    def _psi(expected: List[float], actual: List[float]) -> float:
        """计算 Population Stability Index

        PSI = sum((actual_i - expected_i) * ln(actual_i / expected_i))
        """
        if len(expected) != len(actual):
            return 0.0

        psi = 0.0
        for e, a in zip(expected, actual):
            # 避免除零和 ln(0)
            e_safe = max(e, 0.5)   # 最小 0.5% 避免 ln(0)
            a_safe = max(a, 0.5)
            psi += (a_safe - e_safe) * math.log(a_safe / e_safe)

        return psi

    @staticmethod
    def _psi_to_health(psi: float) -> float:
        """PSI → health_score 映射

        使用指数衰减：health = exp(-psi / threshold)
        当 psi = threshold 时 health ≈ 0.37
        """
        threshold = PSI_MODERATE
        return math.exp(-psi / threshold)
