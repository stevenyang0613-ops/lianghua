"""
⚠️ DEPRECATED: 多模型集成模块：V3 (TimingEngine) + V4 (EnhancedTimingModel) 集成

【状态】已弃用 - 不推荐使用 V3+V4 集成

【原因】2026-06-23 实测验证：
- V3-V4 仓位一致率仅 12%（88% 时间方向相反）
- V3 集成（V3:0.3 + V4:0.7）总收益 +11.38%，跑输 V4-only (+13.02%)
- 集成甚至跑输 BuyHold (+11.94%)
- 集成仅能降低最大回撤 (-19.23% vs -21.19%)，但同时降低收益

【结论】V3 是 V4 的反向指标（不同时代开发，逻辑相反）。
真正的多模型集成需用**正交**模型：
- 趋势模型（动量/突破）+ 均值回归（V4）
- 跨市场对冲（VIX 期货 / 黄金 / 美股）

【保留原因】文档化"集成不可用"的发现，供未来参考。AGENTS.md #64 已记录。

【设计目的（已失效）】V3 和 V4 在因子选择和权重分配上存在差异：
- V3 侧重转债市场（cb_median_premium 30% + cb_avg_amount 25%）+ 流动性
- V4 侧重多因子综合（9 大类因子），但 70% 权重在估值/资金/技术/情绪

【集成方法（已失效）】
1. 简单加权：position = w_v3 * pos_v3 + w_v4 * pos_v4
2. 置信度加权：当两模型方向一致时增加权重
3. 动态权重：基于近期准确率调整（需要验证有效）

默认采用简单加权，权重 v4=0.7, v3=0.3（V4 是当前生产模型，权重更高）。
"""
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# DEPRECATED 模块加载时发出警告
logger.warning(
    "⚠️ timing_ensemble 模块已弃用 - V3+V4 集成验证为反向指标 (一致率 12%)。"
    "详见 AGENTS.md #64 和模块 docstring。"
)


@dataclass
class EnsembleSignal:
    """集成信号"""
    final_position: float          # 集成后最终仓位
    pos_v3: float                  # V3 模型仓位
    pos_v4: float                  # V4 模型仓位
    agree: bool                    # 两模型方向是否一致（>50% vs <50%）
    weight_v3: float = 0.3         # V3 权重
    weight_v4: float = 0.7         # V4 权重


class TimingEnsemble:
    """V3 + V4 集成择时引擎"""

    def __init__(
        self,
        weight_v3: float = 0.3,
        weight_v4: float = 0.7,
        min_position: float = 0.05,
        max_position: float = 1.0,
    ):
        """
        Args:
            weight_v3: V3 (TimingEngine) 权重
            weight_v4: V4 (EnhancedTimingModel) 权重
        """
        if abs(weight_v3 + weight_v4 - 1.0) > 0.01:
            raise ValueError(f"weight_v3 + weight_v4 必须 = 1.0, got {weight_v3 + weight_v4}")
        self.weight_v3 = weight_v3
        self.weight_v4 = weight_v4
        self.min_position = min_position
        self.max_position = max_position

        # 延迟导入，避免循环引用
        from app.strategies.enhanced_timing_model import EnhancedTimingModel
        from app.xb_strategy.core.timing import TimingEngine
        self._EnhancedTimingModel = EnhancedTimingModel
        self._TimingEngine = TimingEngine

        # 实例
        self._v3_engine: Optional[TimingEngine] = None
        self._v4_model: Optional[EnhancedTimingModel] = None

    def _ensure_initialized(self):
        if self._v3_engine is None:
            self._v3_engine = self._TimingEngine()
        if self._v4_model is None:
            self._v4_model = self._EnhancedTimingModel()

    def calculate(self, enhanced_data) -> EnsembleSignal:
        """
        计算集成择时信号

        Args:
            enhanced_data: EnhancedMarketData 实例

        Returns:
            EnsembleSignal
        """
        self._ensure_initialized()

        # 1. V4 计算（当前主模型）
        try:
            v4_signal = self._v4_model.calculate(enhanced_data)
            pos_v4 = v4_signal.position_ratio
        except Exception as e:
            logger.warning(f"[Ensemble] V4 计算失败: {e}, 使用中性仓位")
            pos_v4 = 0.5

        # 2. V3 计算（将 EnhancedMarketData 转换为 V3 的 MarketData）
        try:
            v3_data = self._convert_to_v3_data(enhanced_data)
            v3_signal = self._v3_engine.calculate_timing(v3_data)
            # V3 TimingSignal 有 position_limit 字段
            pos_v3 = v3_signal.position_limit
        except Exception as e:
            logger.warning(f"[Ensemble] V3 计算失败: {e}, 使用中性仓位")
            pos_v3 = 0.5

        # 3. 一致性判断
        agree = (pos_v3 > 0.5) == (pos_v4 > 0.5)

        # 4. 加权集成
        final = self.weight_v4 * pos_v4 + self.weight_v3 * pos_v3
        final = max(self.min_position, min(self.max_position, final))

        return EnsembleSignal(
            final_position=final,
            pos_v3=pos_v3,
            pos_v4=pos_v4,
            agree=agree,
            weight_v3=self.weight_v3,
            weight_v4=self.weight_v4,
        )

    def _convert_to_v3_data(self, em) -> "MarketData":
        """将 EnhancedMarketData 转换为 V3 TimingEngine 的 MarketData"""
        from datetime import datetime
        from app.xb_strategy.core.timing import MarketData
        return MarketData(
            date=em.date if isinstance(em.date, datetime) else datetime.combine(em.date, datetime.min.time()),
            cb_median_premium=getattr(em, 'cb_median_premium', 0.0) or 0.0,
            cb_avg_daily_amount=getattr(em, 'cb_avg_daily_amount', 0.0) or 0.0,
            cb_index_change=getattr(em, 'cb_idx_change', 0.0) or 0.0,
            cb_index_ma20=getattr(em, 'cb_idx_ma20', 0.0) or 0.0,
            cb_index_current=getattr(em, 'cb_idx_current', 0.0) or 0.0,
            treasury_10y_yield=getattr(em, 'treasury_10y_yield', 0.0) or 0.0,
            pmi=getattr(em, 'pmi', 50.0) or 50.0,
            pmi_prev=getattr(em, 'pmi_prev', 50.0) or 50.0,
        )

    def reset(self):
        """重置所有状态（用于新的回测或回测期切换）"""
        self._v3_engine = None
        self._v4_model = None
