"""
Brison策略归因分析模块

实现Brison归因分解：
- 配置效应（Allocation Effect）
- 选券效应（Selection Effect）
- 交互效应（Interaction Effect）
- 交易成本效应
- 行业偏离度分析
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
import numpy as np


@dataclass
class AttributionResult:
    """归因分析结果"""
    period_start: str
    period_end: str
    portfolio_return: float
    benchmark_return: float
    total_excess: float
    allocation_effect: float
    selection_effect: float
    interaction_effect: float
    trading_cost_effect: float
    industry_attribution: dict
    top_contributors: list[dict]
    top_detractors: list[dict]


@dataclass
class IndustryAttribution:
    """行业归因"""
    industry: str
    portfolio_weight: float
    benchmark_weight: float
    portfolio_return: float
    benchmark_return: float
    allocation_effect: float
    selection_effect: float
    interaction_effect: float
    total_contribution: float


class BrisonAttribution:
    """Brison归因分析器"""

    def __init__(
        self,
        portfolio_positions: pd.DataFrame,
        portfolio_returns: pd.DataFrame,
        benchmark_weights: pd.DataFrame,
        benchmark_returns: pd.DataFrame,
        trading_costs: Optional[pd.DataFrame] = None,
    ):
        """
        初始化归因分析器

        portfolio_positions: 组合持仓权重 (code, industry, weight, date)
        portfolio_returns: 组合收益 (code, return, date)
        benchmark_weights: 基准权重 (industry, weight, date)
        benchmark_returns: 基准收益 (industry, return, date)
        trading_costs: 交易成本 (date, cost)
        """
        self._portfolio_positions = portfolio_positions
        self._portfolio_returns = portfolio_returns
        self._benchmark_weights = benchmark_weights
        self._benchmark_returns = benchmark_returns
        self._trading_costs = trading_costs

    def calc_allocation_effect(
        self,
        portfolio_weight: float,
        benchmark_weight: float,
        benchmark_return: float,
        total_benchmark_return: float,
    ) -> float:
        """
        计算配置效应
        Allocation = (Wp - Wb) × (Rb - Rb_total)
        """
        return (portfolio_weight - benchmark_weight) * (benchmark_return - total_benchmark_return)

    def calc_selection_effect(
        self,
        portfolio_return: float,
        benchmark_return: float,
        benchmark_weight: float,
    ) -> float:
        """
        计算选券效应
        Selection = Wb × (Rp - Rb)
        """
        return benchmark_weight * (portfolio_return - benchmark_return)

    def calc_interaction_effect(
        self,
        portfolio_weight: float,
        benchmark_weight: float,
        portfolio_return: float,
        benchmark_return: float,
    ) -> float:
        """
        计算交互效应
        Interaction = (Wp - Wb) × (Rp - Rb)
        """
        return (portfolio_weight - benchmark_weight) * (portfolio_return - benchmark_return)

    def analyze_period(
        self,
        start_date: str,
        end_date: str,
    ) -> AttributionResult:
        """分析单个期间的归因"""
        # 筛选数据
        portfolio_pos = self._portfolio_positions[
            (self._portfolio_positions['date'] >= start_date) &
            (self._portfolio_positions['date'] <= end_date)
        ]
        portfolio_ret = self._portfolio_returns[
            (self._portfolio_returns['date'] >= start_date) &
            (self._portfolio_returns['date'] <= end_date)
        ]
        benchmark_w = self._benchmark_weights[
            (self._benchmark_weights['date'] >= start_date) &
            (self._benchmark_weights['date'] <= end_date)
        ]
        benchmark_r = self._benchmark_returns[
            (self._benchmark_returns['date'] >= start_date) &
            (self._benchmark_returns['date'] <= end_date)
        ]

        if portfolio_pos.empty or benchmark_w.empty:
            return None

        # 计算组合总收益
        portfolio_total_return = self._calc_portfolio_return(portfolio_pos, portfolio_ret)

        # 计算基准总收益
        benchmark_total_return = self._calc_benchmark_return(benchmark_w, benchmark_r)

        # 按行业分组计算
        industry_results = self._calc_industry_attribution(
            portfolio_pos, portfolio_ret, benchmark_w, benchmark_r, benchmark_total_return
        )

        # 汇总效应
        total_allocation = sum(i['allocation_effect'] for i in industry_results.values())
        total_selection = sum(i['selection_effect'] for i in industry_results.values())
        total_interaction = sum(i['interaction_effect'] for i in industry_results.values())

        # 交易成本效应
        trading_cost_effect = 0
        if self._trading_costs is not None:
            cost_data = self._trading_costs[
                (self._trading_costs['date'] >= start_date) &
                (self._trading_costs['date'] <= end_date)
            ]
            if not cost_data.empty:
                trading_cost_effect = -cost_data['cost'].sum() / 100  # 转换为百分比

        # 总超额收益
        total_excess = portfolio_total_return - benchmark_total_return

        # 计算分解后的残差（应该接近0）
        decomposed = total_allocation + total_selection + total_interaction + trading_cost_effect
        residual = total_excess - decomposed

        # 找出最大贡献者和最大拖累者
        contributions = []
        for industry, data in industry_results.items():
            contributions.append({
                'industry': industry,
                'contribution': data['total_contribution'],
                'portfolio_weight': data['portfolio_weight'],
                'portfolio_return': data['portfolio_return'],
            })

        contributions.sort(key=lambda x: x['contribution'], reverse=True)
        top_contributors = contributions[:5]
        top_detractors = contributions[-5:] if len(contributions) >= 5 else contributions

        return AttributionResult(
            period_start=start_date,
            period_end=end_date,
            portfolio_return=round(portfolio_total_return, 4),
            benchmark_return=round(benchmark_total_return, 4),
            total_excess=round(total_excess, 4),
            allocation_effect=round(total_allocation, 4),
            selection_effect=round(total_selection, 4),
            interaction_effect=round(total_interaction, 4),
            trading_cost_effect=round(trading_cost_effect, 4),
            industry_attribution=industry_results,
            top_contributors=top_contributors,
            top_detractors=top_detractors,
        )

    def _calc_portfolio_return(
        self,
        positions: pd.DataFrame,
        returns: pd.DataFrame,
    ) -> float:
        """计算组合收益率"""
        if positions.empty or returns.empty:
            return 0

        # 合并权重和收益
        merged = positions.merge(returns[['code', 'date', 'return']], on=['code', 'date'], how='left')
        merged['return'] = merged['return'].fillna(0)

        # 加权收益
        return (merged['weight'] * merged['return']).sum()

    def _calc_benchmark_return(
        self,
        weights: pd.DataFrame,
        returns: pd.DataFrame,
    ) -> float:
        """计算基准收益率"""
        if weights.empty or returns.empty:
            return 0

        merged = weights.merge(returns[['industry', 'date', 'return']], on=['industry', 'date'], how='left')
        merged['return'] = merged['return'].fillna(0)

        return (merged['weight'] * merged['return']).sum()

    def _calc_industry_attribution(
        self,
        portfolio_pos: pd.DataFrame,
        portfolio_ret: pd.DataFrame,
        benchmark_w: pd.DataFrame,
        benchmark_r: pd.DataFrame,
        total_benchmark_return: float,
    ) -> dict:
        """计算各行业归因"""
        results = {}

        # 获取所有行业
        industries = set(portfolio_pos['industry'].unique()) | set(benchmark_w['industry'].unique())

        for industry in industries:
            # 组合权重
            p_weight = portfolio_pos[portfolio_pos['industry'] == industry]['weight'].sum()

            # 基准权重
            b_weight_row = benchmark_w[benchmark_w['industry'] == industry]
            b_weight = b_weight_row['weight'].sum() if not b_weight_row.empty else 0

            # 组合收益
            p_codes = portfolio_pos[portfolio_pos['industry'] == industry]['code'].unique()
            p_ret_data = portfolio_ret[portfolio_ret['code'].isin(p_codes)]
            p_return = p_ret_data['return'].mean() if not p_ret_data.empty else 0

            # 基准收益
            b_ret_row = benchmark_r[benchmark_r['industry'] == industry]
            b_return = b_ret_row['return'].mean() if not b_ret_row.empty else 0

            # 计算效应
            allocation = self.calc_allocation_effect(p_weight, b_weight, b_return, total_benchmark_return)
            selection = self.calc_selection_effect(p_return, b_return, b_weight)
            interaction = self.calc_interaction_effect(p_weight, b_weight, p_return, b_return)
            total = allocation + selection + interaction

            results[industry] = {
                'portfolio_weight': round(p_weight, 4),
                'benchmark_weight': round(b_weight, 4),
                'portfolio_return': round(p_return, 4),
                'benchmark_return': round(b_return, 4),
                'allocation_effect': round(allocation, 4),
                'selection_effect': round(selection, 4),
                'interaction_effect': round(interaction, 4),
                'total_contribution': round(total, 4),
            }

        return results

    def generate_report(self, result: AttributionResult) -> str:
        """生成归因报告"""
        lines = []
        lines.append("=" * 60)
        lines.append("Brison归因分析报告")
        lines.append("=" * 60)
        lines.append(f"期间: {result.period_start} ~ {result.period_end}")
        lines.append("")
        lines.append("【收益概览】")
        lines.append(f"  组合收益: {result.portfolio_return*100:.2f}%")
        lines.append(f"  基准收益: {result.benchmark_return*100:.2f}%")
        lines.append(f"  超额收益: {result.total_excess*100:.2f}%")
        lines.append("")
        lines.append("【归因分解】")
        lines.append(f"  配置效应: {result.allocation_effect*100:+.2f}%")
        lines.append(f"  选券效应: {result.selection_effect*100:+.2f}%")
        lines.append(f"  交互效应: {result.interaction_effect*100:+.2f}%")
        lines.append(f"  交易成本: {result.trading_cost_effect*100:+.2f}%")
        lines.append("")
        lines.append("【最大贡献行业】")
        for c in result.top_contributors[:3]:
            lines.append(f"  {c['industry']}: {c['contribution']*100:+.2f}% (权重{c['portfolio_weight']*100:.1f}%)")
        lines.append("")
        lines.append("【最大拖累行业】")
        for c in result.top_detractors[-3:]:
            lines.append(f"  {c['industry']}: {c['contribution']*100:+.2f}% (权重{c['portfolio_weight']*100:.1f}%)")
        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)


class FactorAttribution:
    """因子归因分析器"""

    def __init__(self, factor_returns: pd.DataFrame):
        """
        factor_returns: 因子收益数据 (date, factor, return)
        """
        self._factor_returns = factor_returns

    def calc_factor_contribution(
        self,
        portfolio_exposures: pd.DataFrame,
        factor_returns: pd.DataFrame,
    ) -> dict:
        """计算因子贡献"""
        # portfolio_exposures: (date, factor, exposure)
        merged = portfolio_exposures.merge(
            factor_returns,
            on=['date', 'factor'],
            how='inner'
        )

        merged['contribution'] = merged['exposure'] * merged['return']

        factor_contrib = merged.groupby('factor')['contribution'].sum().to_dict()

        return factor_contrib

    def analyze_style_factors(
        self,
        portfolio_positions: pd.DataFrame,
        style_exposures: pd.DataFrame,
    ) -> dict:
        """分析风格因子暴露"""
        # 风格因子：动量、价值、质量、波动率、流动性等
        style_factors = ['momentum', 'value', 'quality', 'volatility', 'liquidity']

        results = {}
        for factor in style_factors:
            if factor in style_exposures.columns:
                exposure = style_exposures[factor].mean()
                results[factor] = round(exposure, 4)

        return results


@dataclass
class ThreeWayInteraction:
    """三维交互效应结果"""
    allocation_selection: float  # 配置×选券交互
    allocation_timing: float     # 配置×时机交互
    selection_timing: float      # 选券×时机交互
    three_way: float             # 三维交互
    total_interaction: float     # 总交互效应


class EnhancedBrisonAttribution(BrisonAttribution):
    """增强版Brison归因分析 - 支持三维交互效应分解"""

    def __init__(
        self,
        portfolio_positions: pd.DataFrame,
        portfolio_returns: pd.DataFrame,
        benchmark_weights: pd.DataFrame,
        benchmark_returns: pd.DataFrame,
        trading_costs: Optional[pd.DataFrame] = None,
        timing_returns: Optional[pd.DataFrame] = None,
    ):
        """
        扩展初始化，增加时机收益数据

        timing_returns: 时机调整收益 (code, date, timing_return)
        """
        super().__init__(
            portfolio_positions, portfolio_returns,
            benchmark_weights, benchmark_returns, trading_costs
        )
        self._timing_returns = timing_returns

    def calc_three_way_interaction(
        self,
        portfolio_weight: float,
        benchmark_weight: float,
        portfolio_return: float,
        benchmark_return: float,
        portfolio_timing: float,
        benchmark_timing: float,
    ) -> ThreeWayInteraction:
        """
        计算三维交互效应

        分解为：
        - 配置×选券: (Wp - Wb) × (Rp - Rb)
        - 配置×时机: (Wp - Wb) × (Tp - Tb)
        - 选券×时机: Wb × (Rp - Rb) × (Tp - Tb)
        - 三维交互: (Wp - Wb) × (Rp - Rb) × (Tp - Tb)
        """
        weight_diff = portfolio_weight - benchmark_weight
        return_diff = portfolio_return - benchmark_return
        timing_diff = portfolio_timing - benchmark_timing

        # 二维交互
        allocation_selection = weight_diff * return_diff
        allocation_timing = weight_diff * timing_diff
        selection_timing = benchmark_weight * return_diff * timing_diff

        # 三维交互
        three_way = weight_diff * return_diff * timing_diff

        return ThreeWayInteraction(
            allocation_selection=round(allocation_selection, 6),
            allocation_timing=round(allocation_timing, 6),
            selection_timing=round(selection_timing, 6),
            three_way=round(three_way, 6),
            total_interaction=round(allocation_selection + allocation_timing + selection_timing + three_way, 6),
        )

    def analyze_period_with_timing(
        self,
        start_date: str,
        end_date: str,
    ) -> AttributionResult:
        """带时机效应的期间分析"""
        # 先执行基础分析
        base_result = self.analyze_period(start_date, end_date)

        if base_result is None or self._timing_returns is None:
            return base_result

        # 计算时机效应
        timing_data = self._timing_returns[
            (self._timing_returns['date'] >= start_date) &
            (self._timing_returns['date'] <= end_date)
        ]

        if timing_data.empty:
            return base_result

        # 计算三维交互
        three_way_results = self._calc_three_way_effects(start_date, end_date, timing_data)

        # 更新结果
        if three_way_results:
            base_result.industry_attribution['three_way_interaction'] = three_way_results

        return base_result

    def _calc_three_way_effects(
        self,
        start_date: str,
        end_date: str,
        timing_data: pd.DataFrame,
    ) -> dict:
        """计算各行业的三维交互效应"""
        results = {}

        # 获取组合和基准数据
        portfolio_pos = self._portfolio_positions[
            (self._portfolio_positions['date'] >= start_date) &
            (self._portfolio_positions['date'] <= end_date)
        ]
        benchmark_w = self._benchmark_weights[
            (self._benchmark_weights['date'] >= start_date) &
            (self._benchmark_weights['date'] <= end_date)
        ]

        industries = set(portfolio_pos['industry'].unique()) | set(benchmark_w['industry'].unique())

        for industry in industries:
            # 权重
            p_weight = portfolio_pos[portfolio_pos['industry'] == industry]['weight'].sum()
            b_weight_row = benchmark_w[benchmark_w['industry'] == industry]
            b_weight = b_weight_row['weight'].sum() if not b_weight_row.empty else 0

            # 收益
            p_codes = portfolio_pos[portfolio_pos['industry'] == industry]['code'].unique()
            p_timing = timing_data[timing_data['code'].isin(p_codes)]['timing_return'].mean()
            b_timing = 0  # 基准时机效应通常为0

            p_return = self._portfolio_returns[
                self._portfolio_returns['code'].isin(p_codes)
            ]['return'].mean()
            b_return = self._benchmark_returns[
                self._benchmark_returns['industry'] == industry
            ]['return'].mean() if not self._benchmark_returns.empty else 0

            # 计算三维交互
            interaction = self.calc_three_way_interaction(
                p_weight, b_weight,
                p_return if not np.isnan(p_return) else 0,
                b_return if not np.isnan(b_return) else 0,
                p_timing if not np.isnan(p_timing) else 0,
                b_timing,
            )

            results[industry] = {
                'allocation_selection': interaction.allocation_selection,
                'allocation_timing': interaction.allocation_timing,
                'selection_timing': interaction.selection_timing,
                'three_way': interaction.three_way,
                'total': interaction.total_interaction,
            }

        return results

    def generate_detailed_report(
        self,
        result: AttributionResult,
        include_timing: bool = False,
    ) -> str:
        """生成详细归因报告"""
        lines = []
        lines.append("=" * 70)
        lines.append("增强版Brison归因分析报告")
        lines.append("=" * 70)
        lines.append(f"期间: {result.period_start} ~ {result.period_end}")
        lines.append("")
        lines.append("【收益概览】")
        lines.append(f"  组合收益:    {result.portfolio_return*100:>8.2f}%")
        lines.append(f"  基准收益:    {result.benchmark_return*100:>8.2f}%")
        lines.append(f"  超额收益:    {result.total_excess*100:>+8.2f}%")
        lines.append("")
        lines.append("【归因分解】")
        lines.append(f"  配置效应:    {result.allocation_effect*100:>+8.4f}%  (权重偏离贡献)")
        lines.append(f"  选券效应:    {result.selection_effect*100:>+8.4f}%  (选券能力贡献)")
        lines.append(f"  交互效应:    {result.interaction_effect*100:>+8.4f}%  (配置×选券)")
        lines.append(f"  交易成本:    {result.trading_cost_effect*100:>+8.4f}%  (交易损耗)")
        lines.append("")

        # 三维交互效应（如果有）
        if include_timing and 'three_way_interaction' in result.industry_attribution:
            lines.append("【三维交互效应】")
            three_way = result.industry_attribution['three_way_interaction']
            for industry, data in three_way.items():
                lines.append(f"  {industry}:")
                lines.append(f"    配置×选券: {data['allocation_selection']*100:+.4f}%")
                lines.append(f"    配置×时机: {data['allocation_timing']*100:+.4f}%")
                lines.append(f"    选券×时机: {data['selection_timing']*100:+.4f}%")
                lines.append(f"    三维交互:  {data['three_way']*100:+.4f}%")
            lines.append("")

        lines.append("【行业归因详情】")
        lines.append("-" * 70)
        lines.append(f"{'行业':<12} {'权重':>8} {'收益':>8} {'配置':>8} {'选券':>8} {'交互':>8}")
        lines.append("-" * 70)

        for industry, data in sorted(result.industry_attribution.items()):
            if industry == 'three_way_interaction':
                continue
            lines.append(
                f"{industry:<12} "
                f"{data['portfolio_weight']*100:>7.1f}% "
                f"{data['portfolio_return']*100:>7.2f}% "
                f"{data['allocation_effect']*100:>+7.3f}% "
                f"{data['selection_effect']*100:>+7.3f}% "
                f"{data['interaction_effect']*100:>+7.3f}%"
            )
        lines.append("")

        lines.append("【最大贡献行业TOP3】")
        for i, c in enumerate(result.top_contributors[:3], 1):
            lines.append(
                f"  {i}. {c['industry']}: {c['contribution']*100:+.3f}% "
                f"(权重{c['portfolio_weight']*100:.1f}%, 收益{c['portfolio_return']*100:.2f}%)"
            )
        lines.append("")

        lines.append("【最大拖累行业TOP3】")
        for i, c in enumerate(result.top_detractors[-3:], 1):
            lines.append(
                f"  {i}. {c['industry']}: {c['contribution']*100:+.3f}% "
                f"(权重{c['portfolio_weight']*100:.1f}%, 收益{c['portfolio_return']*100:.2f}%)"
            )
        lines.append("")

        # 归因质量检验
        decomposed = (
            result.allocation_effect +
            result.selection_effect +
            result.interaction_effect +
            result.trading_cost_effect
        )
        residual = result.total_excess - decomposed

        lines.append("【归因质量检验】")
        lines.append(f"  超额收益:    {result.total_excess*100:>+.4f}%")
        lines.append(f"  归因分解和:  {decomposed*100:>+.4f}%")
        lines.append(f"  残差:        {residual*100:>+.6f}%  (应接近0)")
        lines.append("")
        lines.append("=" * 70)

        return "\n".join(lines)
