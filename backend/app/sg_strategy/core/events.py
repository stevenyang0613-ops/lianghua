"""松岗量化可转债策略 V3.0 事件驱动子策略

四大事件驱动策略:
1. 下修博弈策略: 多因子概率模型
2. 强赎预警策略: 正股价连续25日中有15日>转股价×130%
3. 折价套利策略: 转股溢价率<-2%
4. 回售套利策略: 进入回售期+正股<回售价×70%+转债<回售价-2元
"""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Dict, Optional, Tuple
import logging

from app.sg_strategy.core.types import (
    ConvertibleBondData, StockData, TradeSignal, TradeAction, SignalType,
    DownwardRevisionScore,
)
from app.sg_strategy.config.settings import params

logger = logging.getLogger(__name__)


@dataclass
class EventOpportunity:
    """事件机会"""
    cb_code: str
    cb_name: str
    event_type: str  # revision/forced_call/discount_arb/put_arb
    probability: float  # 成功概率(0-100)
    expected_return: float  # 预期收益(%)
    max_position: float  # 最高仓位
    holding_period: int  # 预期持有天数
    trigger_conditions: List[str]  # 触发条件
    risk_warnings: List[str]  # 风险提示

    def to_dict(self) -> dict:
        return {
            "cb_code": self.cb_code,
            "cb_name": self.cb_name,
            "event_type": self.event_type,
            "probability": round(self.probability, 1),
            "expected_return": round(self.expected_return, 2),
            "max_position": self.max_position,
            "holding_period": self.holding_period,
            "trigger_conditions": self.trigger_conditions,
            "risk_warnings": self.risk_warnings,
        }


class DownwardRevisionStrategy:
    """下修博弈策略

    多因子概率模型:
    - 财务压力 (30%): 资产负债率
    - 回售剩余时间 (25%): 距回售日时间
    - 大股东转债持仓 (25%): 大股东持有比例
    - 下修历史 (20%): 是否有成功下修记录
    """

    def __init__(self):
        """初始化"""
        self._revision_history: Dict[str, bool] = {}  # {code: has_revision}

    def calculate_revision_probability(
        self,
        cb: ConvertibleBondData,
        stock: Optional[StockData] = None,
    ) -> DownwardRevisionScore:
        """计算下修概率

        Args:
            cb: 可转债数据
            stock: 正股数据

        Returns:
            DownwardRevisionScore: 下修概率评分
        """
        score = DownwardRevisionScore(cb_code=cb.code, date=cb.date)

        # 1. 财务压力得分 (30分)
        if stock and stock.debt_ratio > 0:
            if stock.debt_ratio > 70:
                score.financial_pressure = 30.0
            elif stock.debt_ratio > 50:
                score.financial_pressure = 15.0
            else:
                score.financial_pressure = 0.0
        else:
            score.financial_pressure = 10.0

        # 2. 回售时间压力得分 (25分)
        if cb.put_date:
            days_to_put = (cb.put_date - cb.date).days
            if days_to_put < 180:  # <6个月
                score.put_time_pressure = 25.0
            elif days_to_put < 365:  # 6-12个月
                score.put_time_pressure = 12.5
            else:
                score.put_time_pressure = 0.0
        else:
            score.put_time_pressure = 0.0

        # 3. 大股东利益得分 (25分)
        if cb.major_holder_ratio > 0:
            if cb.major_holder_ratio > 20:
                score.major_holder_interest = 25.0
            elif cb.major_holder_ratio > 5:
                score.major_holder_interest = 12.5
            else:
                score.major_holder_interest = 0.0
        else:
            score.major_holder_interest = 0.0

        # 4. 下修历史得分 (20分)
        has_revision = self._revision_history.get(cb.code, False)
        if has_revision:
            score.revision_history = 20.0
        else:
            score.revision_history = 0.0

        # 总分
        score.total_score = (
            score.financial_pressure
            + score.put_time_pressure
            + score.major_holder_interest
            + score.revision_history
        )

        # 概率等级
        if score.total_score >= 60:
            score.probability_level = "high"
        elif score.total_score >= 30:
            score.probability_level = "medium"
        else:
            score.probability_level = "low"

        return score

    def check_opportunity(
        self,
        cb: ConvertibleBondData,
        revision_score: DownwardRevisionScore,
    ) -> Optional[EventOpportunity]:
        """检查下修博弈机会

        Args:
            cb: 可转债数据
            revision_score: 下修概率评分

        Returns:
            EventOpportunity: 机会详情，无机会返回None
        """
        # 条件: 下修概率>60分 + 转债价格<115元 + 转股溢价率>30%
        if revision_score.total_score < params.revision_prob_threshold:
            return None
        if cb.close > params.revision_max_price:
            return None
        if cb.conversion_premium < params.revision_min_premium:
            return None

        return EventOpportunity(
            cb_code=cb.code,
            cb_name=cb.name,
            event_type="revision",
            probability=revision_score.total_score,
            expected_return=6.0,  # 平均收益约6%
            max_position=params.revision_max_position,
            holding_period=90,
            trigger_conditions=[
                f"下修概率{revision_score.total_score:.0f}分",
                f"价格{cb.close:.1f}元<{params.revision_max_price}元",
                f"溢价率{cb.conversion_premium:.1f}%>{params.revision_min_premium}%",
            ],
            risk_warnings=[
                "可能3个月内未触发下修",
                "下修幅度可能不及预期",
            ],
        )


class ForcedCallStrategy:
    """强赎预警策略

    触发条件: 正股价连续25个交易日中有15日>转股价×130%
    """

    def __init__(self):
        """初始化"""
        self._above_130_days: Dict[str, int] = {}  # {code: days_above_130}

    def update_tracking(
        self,
        cb: ConvertibleBondData,
    ) -> int:
        """更新强赎跟踪

        Args:
            cb: 可转债数据

        Returns:
            连续高于130%的天数
        """
        if cb.conversion_price <= 0:
            return 0

        ratio = cb.stock_price / cb.conversion_price if cb.stock_price > 0 else 0

        if ratio >= params.forced_call_ratio:
            self._above_130_days[cb.code] = self._above_130_days.get(cb.code, 0) + 1
        else:
            self._above_130_days[cb.code] = 0

        return self._above_130_days.get(cb.code, 0)

    def check_opportunity(
        self,
        cb: ConvertibleBondData,
    ) -> Optional[EventOpportunity]:
        """检查强赎预警机会

        Args:
            cb: 可转债数据

        Returns:
            EventOpportunity: 机会详情
        """
        above_days = self._above_130_days.get(cb.code, 0)

        # 条件: 连续15日以上高于130% 且 未发布强赎公告
        if above_days < params.forced_call_trigger_days:
            return None
        if cb.is_called:
            return None

        # 计算距离触发还有几天
        days_to_trigger = max(0, params.forced_call_total_days - above_days)

        return EventOpportunity(
            cb_code=cb.code,
            cb_name=cb.name,
            event_type="forced_call",
            probability=70.0,  # 历史胜率约60-70%
            expected_return=4.0,
            max_position=params.forced_call_max_position,
            holding_period=2,  # 公告后2天卖出
            trigger_conditions=[
                f"连续{above_days}日高于130%转股价",
                f"距离触发强赎还需{days_to_trigger}日",
            ],
            risk_warnings=[
                "公司可能选择不赎回",
                "溢价率快速收敛风险",
            ],
        )


class DiscountArbitrageStrategy:
    """折价套利策略

    触发条件: 转股溢价率<-2%
    操作: 买入转债 → 当日转股 → 次日卖出正股
    """

    def check_opportunity(
        self,
        cb: ConvertibleBondData,
    ) -> Optional[EventOpportunity]:
        """检查折价套利机会

        Args:
            cb: 可转债数据

        Returns:
            EventOpportunity: 机会详情
        """
        # 条件: 转股溢价率<-2%
        if cb.conversion_premium >= params.arb_discount_threshold:
            return None

        # 前置条件检查
        risks = []
        if cb.stock_code.startswith("ST"):
            risks.append("正股ST，转股后可能卖出困难")
        if cb.remaining_years < 0.1:
            risks.append("临近到期")

        # 预期收益 = 折价率 - 交易成本
        # 交易成本约: 买入佣金 + 卖出佣金 + 卖出印花税 + 滑点
        # 转债免印花税，正股卖出有印花税0.1%
        estimated_cost = 0.3  # 约0.3%的综合成本
        expected_return = abs(cb.conversion_premium) - estimated_cost

        return EventOpportunity(
            cb_code=cb.code,
            cb_name=cb.name,
            event_type="discount_arb",
            probability=80.0,  # 相对确定性较高
            expected_return=max(expected_return, 0.5),
            max_position=params.arb_max_position_ratio,
            holding_period=2,  # T+1转股，T+2卖出
            trigger_conditions=[
                f"转股溢价率{cb.conversion_premium:.2f}%<{params.arb_discount_threshold}%",
                f"转股价值{cb.conversion_value:.2f}元",
            ],
            risk_warnings=risks if risks else [
                "T+1隔夜波动风险",
                "正股流动性风险",
            ],
        )

    def calculate_arbitrage_return(
        self,
        cb: ConvertibleBondData,
        stock_price: float,
    ) -> Dict[str, float]:
        """计算套利收益

        Args:
            cb: 可转债数据
            stock_price: 正股价格

        Returns:
            收益计算详情
        """
        # 买入转债成本
        cb_cost = cb.close * 1.0002  # 含佣金

        # 转股获得股数
        shares_per_bond = 100 / cb.conversion_price  # 每张转债可转股数

        # 转股价值
        conversion_value = shares_per_bond * stock_price

        # 卖出正股收入(扣除印花税和佣金)
        sell_revenue = conversion_value * (1 - 0.001 - 0.0002)  # 印花税+佣金

        # 净收益
        profit = sell_revenue - cb_cost
        profit_pct = profit / cb_cost * 100

        return {
            "cb_cost": round(cb_cost, 2),
            "shares_per_bond": round(shares_per_bond, 2),
            "conversion_value": round(conversion_value, 2),
            "sell_revenue": round(sell_revenue, 2),
            "profit": round(profit, 2),
            "profit_pct": round(profit_pct, 2),
        }


class PutArbitrageStrategy:
    """回售套利策略 (V3.0新增)

    触发条件:
    - 转债进入回售期
    - 正股价格 < 回售价 × 70%
    - 转债价格 < 回售价 - 2元
    """

    def check_opportunity(
        self,
        cb: ConvertibleBondData,
    ) -> Optional[EventOpportunity]:
        """检查回售套利机会

        Args:
            cb: 可转债数据

        Returns:
            EventOpportunity: 机会详情
        """
        # 条件1: 已进入回售期
        if cb.put_date is None or cb.date < cb.put_date:
            return None

        # 条件2: 正股价格 < 回售价 × 70%
        if cb.put_price <= 0:
            return None
        if cb.stock_price > cb.put_price * params.put_arb_trigger_ratio:
            return None

        # 条件3: 转债价格 < 回售价 - 2元
        if cb.close > cb.put_price - params.put_arb_discount:
            return None

        # 预期收益 = 回售价 - 买入价
        expected_return = (cb.put_price - cb.close) / cb.close * 100

        return EventOpportunity(
            cb_code=cb.code,
            cb_name=cb.name,
            event_type="put_arb",
            probability=85.0,  # 相对确定
            expected_return=expected_return,
            max_position=params.put_arb_max_position,
            holding_period=30,  # 持有至回售申报日
            trigger_conditions=[
                f"已进入回售期",
                f"正股{cb.stock_price:.2f}元 < 回售价{cb.put_price:.0f}×70%",
                f"转债{cb.close:.2f}元 < 回售价{cb.put_price:.0f}-{params.put_arb_discount}元",
            ],
            risk_warnings=[
                "公司可能下调转股价化解回售压力",
                "回售时间成本",
            ],
        )


class EventDrivenEngine:
    """事件驱动引擎"""

    def __init__(self):
        """初始化"""
        self.revision_strategy = DownwardRevisionStrategy()
        self.forced_call_strategy = ForcedCallStrategy()
        self.discount_arb_strategy = DiscountArbitrageStrategy()
        self.put_arb_strategy = PutArbitrageStrategy()

        self._opportunities: List[EventOpportunity] = []

    def scan_opportunities(
        self,
        bonds: List[ConvertibleBondData],
        stocks: Optional[Dict[str, StockData]] = None,
    ) -> List[EventOpportunity]:
        """扫描所有事件驱动机会

        Args:
            bonds: 可转债列表
            stocks: 正股数据字典

        Returns:
            机会列表
        """
        opportunities = []

        for cb in bonds:
            stock = stocks.get(cb.stock_code) if stocks else None

            # 1. 下修博弈
            revision_score = self.revision_strategy.calculate_revision_probability(cb, stock)
            opp = self.revision_strategy.check_opportunity(cb, revision_score)
            if opp:
                opportunities.append(opp)

            # 2. 强赎预警
            self.forced_call_strategy.update_tracking(cb)
            opp = self.forced_call_strategy.check_opportunity(cb)
            if opp:
                opportunities.append(opp)

            # 3. 折价套利
            opp = self.discount_arb_strategy.check_opportunity(cb)
            if opp:
                opportunities.append(opp)

            # 4. 回售套利
            opp = self.put_arb_strategy.check_opportunity(cb)
            if opp:
                opportunities.append(opp)

        self._opportunities = opportunities

        logger.info(
            f"[Events] 扫描完成: 发现{len(opportunities)}个事件机会 "
            f"(下修{sum(1 for o in opportunities if o.event_type == 'revision')}, "
            f"强赎{sum(1 for o in opportunities if o.event_type == 'forced_call')}, "
            f"折价{sum(1 for o in opportunities if o.event_type == 'discount_arb')}, "
            f"回售{sum(1 for o in opportunities if o.event_type == 'put_arb')})"
        )

        return opportunities

    def generate_signals(
        self,
        opportunities: List[EventOpportunity],
        aum: float,
    ) -> List[TradeSignal]:
        """根据机会生成交易信号

        Args:
            opportunities: 机会列表
            aum: 资产规模

        Returns:
            交易信号列表
        """
        signals = []

        for opp in opportunities:
            # 计算交易数量
            position_value = aum * 10000 * opp.max_position
            # 假设均价100元
            quantity = int(position_value / 100 / 100) * 100

            signals.append(TradeSignal(
                signal_id=str(hash(opp.cb_code + opp.event_type))[:8],
                cb_code=opp.cb_code,
                cb_name=opp.cb_name,
                action=TradeAction.BUY,
                signal_type=SignalType.NEW_BUY,
                price=100,  # 需要实际价格
                quantity=quantity,
                reason=f"[{opp.event_type}] {', '.join(opp.trigger_conditions[:2])}",
                confidence=opp.probability / 100,
            ))

        return signals

    def get_opportunities_by_type(self, event_type: str) -> List[EventOpportunity]:
        """按类型获取机会

        Args:
            event_type: 事件类型

        Returns:
            机会列表
        """
        return [o for o in self._opportunities if o.event_type == event_type]

    def get_high_probability_opportunities(
        self,
        min_prob: float = 70.0,
    ) -> List[EventOpportunity]:
        """获取高概率机会

        Args:
            min_prob: 最低概率阈值

        Returns:
            机会列表
        """
        return [o for o in self._opportunities if o.probability >= min_prob]
