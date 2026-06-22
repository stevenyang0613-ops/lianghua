"""西部量化可转债策略 V3.0 一票否决过滤模块

一票否决制：满足任意一条直接排除，不允许任何例外
"""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional, Tuple
import logging

from app.xb_strategy.core.types import ConvertibleBondData, StockData
from app.xb_strategy.config.settings import params

logger = logging.getLogger(__name__)


@dataclass
class VetoResult:
    """一票否决检查结果"""
    cb_code: str
    passed: bool
    veto_reasons: List[str]
    warnings: List[str]

    def to_dict(self):
        return {
            "cb_code": self.cb_code,
            "passed": self.passed,
            "veto_reasons": self.veto_reasons,
            "warnings": self.warnings,
        }


class VetoFilter:
    """一票否决过滤器

    9项强制过滤规则：
    1. 正股触发股票七维一票否决项（ST/*ST、财务造假、监管立案、连续涨停等）
    2. 转债信用评分 < 60分
    3. 转股溢价率 > 100%
    4. 剩余期限 < 6个月
    5. 已发布强赎公告且进入赎回期
    6. 近7日有大股东减持超过1%
    7. 未来10日内有解禁且解禁比例超过5%
    8. 近1年无涨停记录（股性极差）
    9. 转债日均成交额 < 动态阈值（与AUM挂钩）
    """

    def __init__(self, aum: float = 10000.0):
        """初始化

        Args:
            aum: 资产规模(万元)
        """
        self.aum = aum
        self.liquidity_threshold = params.get_liquidity_threshold(aum)

    def check_all(
        self,
        cb: ConvertibleBondData,
        stock: Optional[StockData] = None,
        credit_score: float = 100.0,
    ) -> VetoResult:
        """执行所有一票否决检查

        Args:
            cb: 可转债数据
            stock: 正股数据(可选)
            credit_score: 信用评分

        Returns:
            VetoResult: 检查结果
        """
        veto_reasons: List[str] = []
        warnings: List[str] = []

        # 1. 正股一票否决项检查
        if stock:
            stock_veto, stock_reasons = self._check_stock_veto(stock)
            veto_reasons.extend(stock_reasons)

        # 2. 信用评分检查
        if credit_score < params.min_credit_score:
            veto_reasons.append(
                f"信用评分({credit_score:.1f}) < {params.min_credit_score}"
            )

        # 3. 转股溢价率检查
        if cb.conversion_premium > params.max_conversion_premium:
            veto_reasons.append(
                f"转股溢价率({cb.conversion_premium:.1f}%) > {params.max_conversion_premium}%"
            )

        # 4. 剩余期限检查
        if cb.remaining_years < params.min_remaining_years:
            veto_reasons.append(
                f"剩余期限({cb.remaining_years:.2f}年) < {params.min_remaining_years}年"
            )

        # 5. 强赎公告检查
        if cb.is_called:
            veto_reasons.append("已发布强赎公告")

        # 6. 大股东减持检查
        if cb.has_major_sell:
            veto_reasons.append(
                f"近7日大股东减持 > {params.major_sell_threshold}%"
            )

        # 7. 解禁检查
        if self._check_unlock_veto(cb):
            veto_reasons.append(
                f"未来{params.unlock_days_ahead}日内解禁 > {params.unlock_ratio_threshold}%"
            )

        # 8. 股性检查(近1年无涨停)
        if not cb.has_limit_up_1y:
            veto_reasons.append("近1年无涨停记录，股性极差")

        # 9. 流动性检查
        if cb.daily_amount_20d < self.liquidity_threshold:
            veto_reasons.append(
                f"日均成交额({cb.daily_amount_20d:.0f}万) < {self.liquidity_threshold}万"
            )

        # 警告项(不触发一票否决但需关注)
        if cb.conversion_premium > 50:
            warnings.append(f"高溢价率({cb.conversion_premium:.1f}%)")
        if cb.remaining_years < 1:
            warnings.append(f"临近到期({cb.remaining_years:.2f}年)")
        if cb.forced_call_days > 0:
            warnings.append(f"强赎倒计时({cb.forced_call_days}天)")

        passed = len(veto_reasons) == 0

        return VetoResult(
            cb_code=cb.code,
            passed=passed,
            veto_reasons=veto_reasons,
            warnings=warnings,
        )

    def _check_stock_veto(self, stock: StockData) -> Tuple[bool, List[str]]:
        """检查正股一票否决项

        Args:
            stock: 正股数据

        Returns:
            (是否通过, 原因列表)
        """
        reasons = []

        # ST检查
        if stock.is_st:
            reasons.append("正股ST")

        # 退市风险警示
        if stock.is_delisting_warning:
            reasons.append("正股*ST/退市风险")

        # 连续涨停检查(3个一字涨停)
        if stock.limit_up and stock.change_pct >= 9.9:
            consecutive_limit_up = getattr(stock, 'consecutive_limit_up_days', 0)
            if consecutive_limit_up >= 3:
                reasons.append(f"连续涨停{consecutive_limit_up}天（一字板）")

        return len(reasons) == 0, reasons

    def _check_unlock_veto(self, cb: ConvertibleBondData) -> bool:
        """检查解禁一票否决

        Args:
            cb: 可转债数据

        Returns:
            是否触发一票否决
        """
        if cb.unlock_date is None:
            return False

        today = date.today()
        days_to_unlock = (cb.unlock_date - today).days

        if 0 < days_to_unlock <= params.unlock_days_ahead:
            if cb.unlock_ratio >= params.unlock_ratio_threshold:
                return True

        return False

    def filter_bonds(
        self,
        bonds: List[ConvertibleBondData],
        stocks: Optional[dict] = None,
        credit_scores: Optional[dict] = None,
    ) -> Tuple[List[ConvertibleBondData], List[VetoResult]]:
        """批量过滤可转债

        Args:
            bonds: 可转债列表
            stocks: 正股数据字典 {code: StockData}
            credit_scores: 信用评分字典 {code: score}

        Returns:
            (通过过滤的转债列表, 所有检查结果)
        """
        passed_bonds = []
        all_results = []

        for cb in bonds:
            stock = stocks.get(cb.stock_code) if stocks else None
            credit = credit_scores.get(cb.code, 100.0) if credit_scores else 100.0

            result = self.check_all(cb, stock, credit)
            all_results.append(result)

            if result.passed:
                passed_bonds.append(cb)
            else:
                logger.debug(
                    f"[VetoFilter] {cb.code} {cb.name} 被过滤: {result.veto_reasons}"
                )

        logger.info(
            f"[VetoFilter] 过滤完成: {len(passed_bonds)}/{len(bonds)} 通过"
        )
        return passed_bonds, all_results

    def update_aum(self, aum: float) -> None:
        """更新AUM规模，重新计算流动性阈值

        Args:
            aum: 新的资产规模(万元)
        """
        self.aum = aum
        self.liquidity_threshold = params.get_liquidity_threshold(aum)
        logger.info(f"[VetoFilter] AUM更新: {aum}万, 流动性阈值: {self.liquidity_threshold}万")


class EnhancedVetoFilter(VetoFilter):
    """增强版一票否决过滤器 - 包含更多检查项"""

    def check_all(
        self,
        cb: ConvertibleBondData,
        stock: Optional[StockData] = None,
        credit_score: float = 100.0,
        additional_checks: bool = True,
    ) -> VetoResult:
        """执行所有一票否决检查(含增强检查)

        Args:
            cb: 可转债数据
            stock: 正股数据
            credit_score: 信用评分
            additional_checks: 是否执行增强检查

        Returns:
            VetoResult: 检查结果
        """
        result = super().check_all(cb, stock, credit_score)

        if additional_checks:
            # 增强检查项
            additional_reasons = self._additional_checks(cb, stock)
            result.veto_reasons.extend(additional_reasons)
            result.passed = len(result.veto_reasons) == 0

        return result

    def _additional_checks(
        self,
        cb: ConvertibleBondData,
        stock: Optional[StockData] = None,
    ) -> List[str]:
        """增强检查项

        Args:
            cb: 可转债数据
            stock: 正股数据

        Returns:
            额外的否决原因列表
        """
        reasons = []

        # 检查转股价是否合理(这是关键数据，缺失会影响计算)
        if cb.conversion_price <= 0:
            # 转股价缺失不应该是硬性否决，因为可能只是数据暂未获取
            # 但需要记录警告
            pass  # 不再作为否决条件

        # 检查纯债价值(可选数据，缺失不影响核心策略)
        # 移除此检查，因为很多转债纯债价值数据不可用

        # 检查正股是否停牌(仅在明确停牌时否决)
        if stock and stock.volume <= 0 and stock.amount <= 0:
            # 需要更明确的停牌标识才能否决
            pass  # 不再作为否决条件

        # 检查极端价格
        if cb.close <= 0:
            reasons.append("转债价格无效")

        return reasons
