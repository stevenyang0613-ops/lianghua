"""
实盘成本追踪与校准模块

功能：
- 交易成本记录表
- 实际成本vs预估成本对比
- 成本模型校准
- 成本预警阈值
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
import numpy as np


@dataclass
class TradeCostRecord:
    """单笔交易成本记录"""
    trade_id: str
    code: str
    action: str  # buy/sell
    planned_price: float  # 计划价格
    actual_price: float  # 实际成交价
    volume: int
    planned_amount: float
    actual_amount: float
    planned_commission: float
    actual_commission: float
    planned_slippage: float
    actual_slippage: float
    planned_impact: float
    actual_impact: float
    total_planned_cost: float
    total_actual_cost: float
    cost_deviation: float
    ts: str


@dataclass
class CostCalibrationResult:
    """成本模型校准结果"""
    commission_deviation: float
    slippage_deviation: float
    impact_deviation: float
    total_deviation: float
    calibration_factors: dict
    recommended_adjustments: dict


@dataclass
class CostAlert:
    """成本预警"""
    alert_type: str
    threshold: float
    actual_value: float
    message: str
    ts: str


class CostTracker:
    """实盘成本追踪器"""

    # 预警阈值
    COST_WARNING_THRESHOLDS = {
        'daily_cost_ratio': 0.005,      # 日成本/AUM > 0.5%
        'trade_cost_deviation': 0.3,    # 单笔成本偏差 > 30%
        'slippage_deviation': 0.5,      # 滑点偏差 > 50%
        'impact_deviation': 0.5,        # 冲击成本偏差 > 50%
        'monthly_cost_ratio': 0.008,    # 月成本/AUM > 0.8%
    }

    def __init__(self, aum: float = 100000000):
        """
        初始化成本追踪器

        aum: 资产管理规模
        """
        self._aum = aum
        self._records: list[TradeCostRecord] = []
        self._alerts: list[CostAlert] = []
        self._daily_costs: dict[str, float] = {}
        self._calibration_factors = {
            'commission': 1.0,
            'slippage': 1.0,
            'impact': 1.0,
        }

    def record_trade(
        self,
        trade_id: str,
        code: str,
        action: str,
        planned_price: float,
        actual_price: float,
        volume: int,
        planned_commission: float,
        actual_commission: float,
        planned_slippage: float,
        actual_slippage: float,
        planned_impact: float,
        actual_impact: float,
    ) -> TradeCostRecord:
        """记录交易成本"""
        planned_amount = planned_price * volume
        actual_amount = actual_price * volume

        total_planned = planned_commission + planned_slippage + planned_impact
        total_actual = actual_commission + actual_slippage + actual_impact

        cost_deviation = (total_actual - total_planned) / total_planned if total_planned > 0 else 0

        record = TradeCostRecord(
            trade_id=trade_id,
            code=code,
            action=action,
            planned_price=planned_price,
            actual_price=actual_price,
            volume=volume,
            planned_amount=planned_amount,
            actual_amount=actual_amount,
            planned_commission=planned_commission,
            actual_commission=actual_commission,
            planned_slippage=planned_slippage,
            actual_slippage=actual_slippage,
            planned_impact=planned_impact,
            actual_impact=actual_impact,
            total_planned_cost=total_planned,
            total_actual_cost=total_actual,
            cost_deviation=cost_deviation,
            ts=datetime.now().isoformat(),
        )

        self._records.append(record)

        # 更新日成本统计
        trade_date = datetime.now().strftime('%Y-%m-%d')
        if trade_date not in self._daily_costs:
            self._daily_costs[trade_date] = 0
        self._daily_costs[trade_date] += total_actual

        # 检查预警
        self._check_alerts(record, trade_date)

        return record

    def _check_alerts(self, record: TradeCostRecord, trade_date: str) -> None:
        """检查成本预警"""
        now = datetime.now().isoformat()

        # 单笔成本偏差预警
        if abs(record.cost_deviation) > self.COST_WARNING_THRESHOLDS['trade_cost_deviation']:
            self._alerts.append(CostAlert(
                alert_type='trade_cost_deviation',
                threshold=self.COST_WARNING_THRESHOLDS['trade_cost_deviation'],
                actual_value=abs(record.cost_deviation),
                message=f"交易{record.trade_id}成本偏差{record.cost_deviation*100:.1f}%超过阈值",
                ts=now,
            ))

        # 滑点偏差预警
        if record.planned_slippage > 0:
            slippage_dev = abs(record.actual_slippage - record.planned_slippage) / record.planned_slippage
            if slippage_dev > self.COST_WARNING_THRESHOLDS['slippage_deviation']:
                self._alerts.append(CostAlert(
                    alert_type='slippage_deviation',
                    threshold=self.COST_WARNING_THRESHOLDS['slippage_deviation'],
                    actual_value=slippage_dev,
                    message=f"交易{record.trade_id}滑点偏差{slippage_dev*100:.1f}%超过阈值",
                    ts=now,
                ))

        # 日成本比例预警
        daily_cost = self._daily_costs.get(trade_date, 0)
        daily_ratio = daily_cost / self._aum
        if daily_ratio > self.COST_WARNING_THRESHOLDS['daily_cost_ratio']:
            self._alerts.append(CostAlert(
                alert_type='daily_cost_ratio',
                threshold=self.COST_WARNING_THRESHOLDS['daily_cost_ratio'],
                actual_value=daily_ratio,
                message=f"日成本{daily_cost:.0f}元占AUM{daily_ratio*100:.2f}%超过阈值",
                ts=now,
            ))

    def calibrate_model(self, lookback_days: int = 30) -> CostCalibrationResult:
        """校准成本模型"""
        cutoff = datetime.now() - timedelta(days=lookback_days)
        recent_records = [
            r for r in self._records
            if datetime.fromisoformat(r.ts) >= cutoff
        ]

        if not recent_records:
            return CostCalibrationResult(
                commission_deviation=0,
                slippage_deviation=0,
                impact_deviation=0,
                total_deviation=0,
                calibration_factors=self._calibration_factors,
                recommended_adjustments={},
            )

        # 计算各成本项偏差
        commission_devs = []
        slippage_devs = []
        impact_devs = []

        for r in recent_records:
            if r.planned_commission > 0:
                commission_devs.append(r.actual_commission / r.planned_commission)
            if r.planned_slippage > 0:
                slippage_devs.append(r.actual_slippage / r.planned_slippage)
            if r.planned_impact > 0:
                impact_devs.append(r.actual_impact / r.planned_impact)

        # 计算校准因子
        commission_factor = np.mean(commission_devs) if commission_devs else 1.0
        slippage_factor = np.mean(slippage_devs) if slippage_devs else 1.0
        impact_factor = np.mean(impact_devs) if impact_devs else 1.0

        # 更新校准因子（加权平均，保留历史信息）
        self._calibration_factors['commission'] = (
            0.7 * self._calibration_factors['commission'] + 0.3 * commission_factor
        )
        self._calibration_factors['slippage'] = (
            0.7 * self._calibration_factors['slippage'] + 0.3 * slippage_factor
        )
        self._calibration_factors['impact'] = (
            0.7 * self._calibration_factors['impact'] + 0.3 * impact_factor
        )

        # 计算总偏差
        total_planned = sum(r.total_planned_cost for r in recent_records)
        total_actual = sum(r.total_actual_cost for r in recent_records)
        total_deviation = (total_actual - total_planned) / total_planned if total_planned > 0 else 0

        # 生成调整建议
        adjustments = {}
        if commission_factor > 1.2:
            adjustments['commission'] = f"建议上调佣金预估{(commission_factor-1)*100:.0f}%"
        if slippage_factor > 1.3:
            adjustments['slippage'] = f"建议上调滑点预估{(slippage_factor-1)*100:.0f}%"
        if impact_factor > 1.5:
            adjustments['impact'] = f"建议上调冲击成本预估{(impact_factor-1)*100:.0f}%"

        return CostCalibrationResult(
            commission_deviation=round(commission_factor - 1, 4),
            slippage_deviation=round(slippage_factor - 1, 4),
            impact_deviation=round(impact_factor - 1, 4),
            total_deviation=round(total_deviation, 4),
            calibration_factors={k: round(v, 3) for k, v in self._calibration_factors.items()},
            recommended_adjustments=adjustments,
        )

    def get_daily_report(self, date: str = None) -> dict:
        """获取日成本报告"""
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')

        day_records = [
            r for r in self._records
            if r.ts.startswith(date)
        ]

        if not day_records:
            return {
                'date': date,
                'total_trades': 0,
                'total_cost': 0,
                'cost_ratio': 0,
                'avg_deviation': 0,
            }

        total_cost = sum(r.total_actual_cost for r in day_records)
        avg_dev = np.mean([r.cost_deviation for r in day_records])

        return {
            'date': date,
            'total_trades': len(day_records),
            'total_cost': round(total_cost, 2),
            'cost_ratio': round(total_cost / self._aum, 6),
            'avg_deviation': round(avg_dev, 4),
            'buy_trades': len([r for r in day_records if r.action == 'buy']),
            'sell_trades': len([r for r in day_records if r.action == 'sell']),
            'total_commission': round(sum(r.actual_commission for r in day_records), 2),
            'total_slippage': round(sum(r.actual_slippage for r in day_records), 2),
            'total_impact': round(sum(r.actual_impact for r in day_records), 2),
        }

    def get_monthly_report(self, year: int, month: int) -> dict:
        """获取月度成本报告"""
        month_records = [
            r for r in self._records
            if datetime.fromisoformat(r.ts).year == year and
               datetime.fromisoformat(r.ts).month == month
        ]

        if not month_records:
            return {
                'year': year,
                'month': month,
                'total_trades': 0,
                'total_cost': 0,
                'cost_ratio': 0,
            }

        total_cost = sum(r.total_actual_cost for r in month_records)

        return {
            'year': year,
            'month': month,
            'total_trades': len(month_records),
            'total_cost': round(total_cost, 2),
            'cost_ratio': round(total_cost / self._aum, 6),
            'exceeded_warning': total_cost / self._aum > self.COST_WARNING_THRESHOLDS['monthly_cost_ratio'],
            'daily_avg_cost': round(total_cost / 21, 2),  # 假设21个交易日
            'cost_breakdown': {
                'commission': round(sum(r.actual_commission for r in month_records), 2),
                'slippage': round(sum(r.actual_slippage for r in month_records), 2),
                'impact': round(sum(r.actual_impact for r in month_records), 2),
            },
        }

    def get_unread_alerts(self) -> list[dict]:
        """获取未读预警"""
        return [
            {
                'type': a.alert_type,
                'threshold': a.threshold,
                'actual_value': a.actual_value,
                'message': a.message,
                'ts': a.ts,
            }
            for a in self._alerts[-20:]  # 最近20条
        ]

    def clear_alerts(self) -> int:
        """清除预警"""
        count = len(self._alerts)
        self._alerts.clear()
        return count

    @property
    def calibration_factors(self) -> dict:
        """获取当前校准因子"""
        return self._calibration_factors.copy()

    def set_aum(self, aum: float) -> None:
        """设置AUM"""
        self._aum = aum

    def get_cost_records(self, days: int = 30) -> list[dict]:
        """获取成本记录"""
        cutoff = datetime.now() - timedelta(days=days)
        return [
            {
                'trade_id': r.trade_id,
                'code': r.code,
                'action': r.action,
                'actual_cost': r.total_actual_cost,
                'deviation': r.cost_deviation,
                'ts': r.ts,
            }
            for r in self._records
            if datetime.fromisoformat(r.ts) >= cutoff
        ]
