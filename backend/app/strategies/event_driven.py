"""
事件驱动策略 V3.0

四大事件驱动子策略：
1. 下修博弈策略（四因子概率模型）
2. 强赎预警策略
3. 折价套利策略（阈值-2%）
4. 回售套利策略
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from enum import Enum
import pandas as pd
import numpy as np


class EventType(Enum):
    """事件类型"""
    DOWNSIDE = 'downside'      # 下修博弈
    REDEMPTION = 'redemption'  # 强赎预警
    ARBITRAGE = 'arbitrage'    # 折价套利
    PUT_BACK = 'put_back'      # 回售套利


@dataclass
class EventSignal:
    """事件驱动信号"""
    event_type: EventType
    code: str
    name: str
    price: float
    probability: float  # 触发概率 0-1
    expected_return: float  # 预期收益
    max_position: float  # 最大仓位
    action: str  # buy/sell/hold
    reason: str
    ts: datetime
    details: dict


class DownsideProbabilityModel:
    """下修概率模型（满分100分）"""

    WEIGHTS = {
        'financial_pressure': 0.30,    # 财务压力
        'put_remaining_time': 0.25,    # 回售剩余时间
        'major_holder': 0.25,          # 大股东转债持仓
        'downside_history': 0.20,      # 下修历史
    }

    def calc_financial_pressure_score(
        self,
        asset_liability_ratio: float,
        interest_coverage_ratio: float,
    ) -> float:
        """
        财务压力评分（满分30分）
        资产负债率 > 70%得满分；50-70%得一半；< 50%得0分
        """
        if asset_liability_ratio > 70:
            return 30
        elif asset_liability_ratio > 50:
            return 15
        else:
            return 0

    def calc_put_remaining_time_score(self, days_to_put: int) -> float:
        """
        回售剩余时间评分（满分25分）
        < 6个月得满分；6-12个月得一半；> 12个月得0分
        """
        if days_to_put < 180:
            return 25
        elif days_to_put < 365:
            return 12.5
        else:
            return 0

    def calc_major_holder_score(self, holder_ratio: float) -> float:
        """
        大股东转债持仓评分（满分25分）
        > 20%得满分；5-20%得一半；< 5%得0分
        """
        if holder_ratio > 20:
            return 25
        elif holder_ratio > 5:
            return 12.5
        else:
            return 0

    def calc_downside_history_score(self, has_downside: bool, downside_failed: bool) -> float:
        """
        下修历史评分（满分20分）
        近3年有成功下修得满分；有提议但失败得一半；无记录得0分
        """
        if has_downside:
            return 20
        elif downside_failed:
            return 10
        else:
            return 0

    def calc_probability(
        self,
        asset_liability_ratio: float,
        days_to_put: int,
        holder_ratio: float,
        has_downside: bool,
        downside_failed: bool = False,
    ) -> float:
        """计算下修概率"""
        score = 0
        score += self.calc_financial_pressure_score(asset_liability_ratio, 0)
        score += self.calc_put_remaining_time_score(days_to_put)
        score += self.calc_major_holder_score(holder_ratio)
        score += self.calc_downside_history_score(has_downside, downside_failed)

        return score / 100  # 转换为0-1概率


class EventDrivenStrategy:
    """事件驱动策略"""

    # 策略参数
    DOWNSIDE_PROB_THRESHOLD = 0.60  # 下修概率阈值
    DOWNSIDE_PRICE_MAX = 115  # 下修博弈最高价格
    DOWNSIDE_PREMIUM_MIN = 30  # 下修博弈最低溢价率

    REDEMPTION_TRIGGER_DAYS = 15  # 强赎触发天数
    REDEMPTION_TOTAL_DAYS = 25  # 强赎观察期总天数

    ARBITRAGE_PREMIUM_THRESHOLD = -2.0  # 折价套利阈值（-2%）
    ARBITRAGE_MAX_POSITION = 0.03  # 单次套利最大仓位

    PUT_BACK_PRICE_THRESHOLD = 103  # 回售价
    PUT_BACK_DISCOUNT = 2  # 回售套利折扣（元）

    def __init__(self):
        self._downside_model = DownsideProbabilityModel()
        self._signals: list[EventSignal] = []
        self._event_history: list[dict] = []

    # ==================== 下修博弈策略 ====================

    def check_downside_opportunity(
        self,
        row: pd.Series,
        asset_liability_ratio: float,
        days_to_put: int,
        holder_ratio: float,
        has_downside_history: bool,
    ) -> Optional[EventSignal]:
        """
        检查下修博弈机会
        条件：下修概率 > 60% + 转债价格 < 115元 + 转股溢价率 > 30%
        """
        prob = self._downside_model.calc_probability(
            asset_liability_ratio,
            days_to_put,
            holder_ratio,
            has_downside_history,
        )

        price = row.get('price', 0)
        premium = row.get('premium_ratio', 0)

        if (prob >= self.DOWNSIDE_PROB_THRESHOLD and
            price < self.DOWNSIDE_PRICE_MAX and
            premium > self.DOWNSIDE_PREMIUM_MIN):

            # 计算预期收益（下修后价格上升）
            expected_return = (110 - price) / price  # 假设下修后价格回到110
            expected_return = max(0.05, min(0.15, expected_return))

            signal = EventSignal(
                event_type=EventType.DOWNSIDE,
                code=row['code'],
                name=row.get('name', ''),
                price=price,
                probability=round(prob, 2),
                expected_return=round(expected_return, 3),
                max_position=0.02,  # 单只2%
                action='buy',
                reason=f'下修概率{prob*100:.0f}%，价格{price}元，溢价率{premium:.0f}%',
                ts=datetime.now(),
                details={
                    'asset_liability_ratio': asset_liability_ratio,
                    'days_to_put': days_to_put,
                    'holder_ratio': holder_ratio,
                    'premium': premium,
                },
            )
            self._signals.append(signal)
            return signal

        return None

    # ==================== 强赎预警策略 ====================

    def check_redemption_opportunity(
        self,
        row: pd.Series,
        days_above_threshold: int,
        conversion_price: float,
        stock_price: float,
        announced: bool = False,
    ) -> Optional[EventSignal]:
        """
        检查强赎预警机会
        条件：正股价连续25个交易日中有15日 > 转股价 × 130%，且公司未发布强赎公告
        """
        if announced:
            return None

        threshold_price = conversion_price * 1.30
        is_triggered = stock_price > threshold_price

        if is_triggered and days_above_threshold >= self.REDEMPTION_TRIGGER_DAYS:
            # 计算预期收益
            expected_return = 0.04  # 历史平均收益4%

            signal = EventSignal(
                event_type=EventType.REDEMPTION,
                code=row['code'],
                name=row.get('name', ''),
                price=row.get('price', 0),
                probability=round(days_above_threshold / self.REDEMPTION_TOTAL_DAYS, 2),
                expected_return=round(expected_return, 3),
                max_position=0.02,
                action='buy',
                reason=f'强赎倒计时{days_above_threshold}/{self.REDEMPTION_TOTAL_DAYS}天',
                ts=datetime.now(),
                details={
                    'days_above_threshold': days_above_threshold,
                    'threshold_price': round(threshold_price, 2),
                    'stock_price': stock_price,
                    'conversion_price': conversion_price,
                },
            )
            self._signals.append(signal)
            return signal

        return None

    # ==================== 折价套利策略 ====================

    def check_arbitrage_opportunity(
        self,
        row: pd.Series,
        stock_tradable: bool = True,
        stock_not_st: bool = True,
        stock_not_limit_down: bool = True,
    ) -> Optional[EventSignal]:
        """
        检查折价套利机会
        条件：转股溢价率 < -2%，正股非ST、非跌停、非重大事项停牌
        操作：买入转债 → 当日转股 → 次日卖出正股
        """
        premium = row.get('premium_ratio', 0)
        price = row.get('price', 0)

        # 前置条件检查
        if not (stock_tradable and stock_not_st and stock_not_limit_down):
            return None

        if premium < self.ARBITRAGE_PREMIUM_THRESHOLD:
            # 计算预期收益（扣除成本）
            gross_return = abs(premium) / 100
            cost = 0.005  # 交易成本约0.5%
            net_return = gross_return - cost

            signal = EventSignal(
                event_type=EventType.ARBITRAGE,
                code=row['code'],
                name=row.get('name', ''),
                price=price,
                probability=0.9,  # 折价套利确定性较高
                expected_return=round(max(0, net_return), 3),
                max_position=self.ARBITRAGE_MAX_POSITION,
                action='buy',
                reason=f'折价{premium:.2f}%，套利空间{net_return*100:.2f}%',
                ts=datetime.now(),
                details={
                    'premium': premium,
                    'gross_return': round(gross_return, 4),
                    'cost': round(cost, 4),
                },
            )
            self._signals.append(signal)
            return signal

        return None

    # ==================== 回售套利策略 ====================

    def check_put_back_opportunity(
        self,
        row: pd.Series,
        in_put_period: bool,
        days_to_put: int,
        put_price: float = 103,
        stock_price: float = 0,
        conversion_price: float = 0,
    ) -> Optional[EventSignal]:
        """
        检查回售套利机会
        条件：转债进入回售期 + 正股价格 < 回售价 × 70% + 转债价格 < 回售价 - 2元
        """
        price = row.get('price', 0)

        if not in_put_period:
            return None

        # 正股价格条件
        stock_condition = stock_price < put_price * 0.7 if stock_price > 0 else True

        # 价格条件
        price_condition = price < put_price - self.PUT_BACK_DISCOUNT

        if stock_condition and price_condition:
            expected_return = (put_price - price) / price

            signal = EventSignal(
                event_type=EventType.PUT_BACK,
                code=row['code'],
                name=row.get('name', ''),
                price=price,
                probability=0.8,
                expected_return=round(expected_return, 3),
                max_position=0.03,
                action='buy',
                reason=f'回售价{put_price}元，当前价{price}元，收益空间{(put_price-price):.2f}元',
                ts=datetime.now(),
                details={
                    'put_price': put_price,
                    'days_to_put': days_to_put,
                    'stock_price': stock_price,
                    'conversion_price': conversion_price,
                },
            )
            self._signals.append(signal)
            return signal

        return None

    # ==================== 综合检测 ====================

    def scan_all_opportunities(
        self,
        bonds_df: pd.DataFrame,
        fundamental_data: dict,
    ) -> list[EventSignal]:
        """扫描所有事件驱动机会"""
        signals = []

        for _, row in bonds_df.iterrows():
            code = row['code']
            fund = fundamental_data.get(code, {})

            # 检查下修博弈
            sig = self.check_downside_opportunity(
                row,
                asset_liability_ratio=fund.get('asset_liability_ratio', 50),
                days_to_put=fund.get('days_to_put', 365),
                holder_ratio=fund.get('holder_ratio', 0),
                has_downside_history=fund.get('has_downside', False),
            )
            if sig:
                signals.append(sig)

            # 检查强赎预警
            sig = self.check_redemption_opportunity(
                row,
                days_above_threshold=fund.get('redemption_days', 0),
                conversion_price=row.get('conversion_price', 0),
                stock_price=row.get('stock_price', 0),
                announced=fund.get('redemption_announced', False),
            )
            if sig:
                signals.append(sig)

            # 检查折价套利
            sig = self.check_arbitrage_opportunity(
                row,
                stock_tradable=fund.get('stock_tradable', True),
                stock_not_st=fund.get('stock_not_st', True),
                stock_not_limit_down=fund.get('stock_not_limit_down', True),
            )
            if sig:
                signals.append(sig)

            # 检查回售套利
            sig = self.check_put_back_opportunity(
                row,
                in_put_period=fund.get('in_put_period', False),
                days_to_put=fund.get('days_to_put', 365),
                put_price=fund.get('put_price', 103),
                stock_price=row.get('stock_price', 0),
                conversion_price=row.get('conversion_price', 0),
            )
            if sig:
                signals.append(sig)

        return signals

    @property
    def current_signals(self) -> list[EventSignal]:
        return self._signals.copy()

    def clear_signals(self) -> None:
        self._signals.clear()

    def get_event_history(self, days: int = 30) -> list[dict]:
        """获取事件历史"""
        cutoff = datetime.now() - timedelta(days=days)
        return [
            {
                'event_type': e['event_type'],
                'code': e['code'],
                'action': e['action'],
                'ts': e['ts'].isoformat(),
            }
            for e in self._event_history
            if e['ts'] >= cutoff
        ]
