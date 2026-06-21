"""
GF-DMA Health Index: 走势健康度框架 V1.0

核心问题: 一只股票上涨，是健康上涨还是短线过热？
回调是健康回调还是趋势破坏？

主要看:
- 20/50/100/200 日均线结构
- 股价离均线多远
- 基本面增速能不能支撑走势
- 预期有没有上修
- 有没有 FOMO 逃逸风险

输出: health_score (0-100) + trend_phase + 风险提示
"""

from dataclasses import dataclass, field
from typing import Optional
import math


@dataclass
class HealthReport:
    """走势健康度报告"""
    code: str
    name: str
    health_score: float  # 0-100
    trend_phase: str  # accumulation / markup / distribution / markdown
    ma_alignment: str  # perfect / good / warning / broken
    ma_deviation_warning: str  # overbought/none
    fundamental_support: str  # strong / neutral / weak
    expectation_revision: str  # upgraded / stable / downgraded
    fomo_risk: str  # low / medium / high / extreme
    recommendation: str  # buy / hold / trim / sell / avoid
    health_factors: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class GFDMAHealthAnalyzer:
    """GF-DMA Health Index 分析器"""

    # 均线参数
    MA_PERIODS = [20, 50, 100, 200]

    def __init__(self):
        pass

    def analyze(self, stock: dict) -> HealthReport:
        """
        主入口

        stock 字段:
        - code, name
        - prices: [p1, p2, ..., pn]  (按时间从早到晚)
        - ma_20, ma_50, ma_100, ma_200 (当前值)
        - eps_growth, revenue_growth (%)
        - pe (TTM)
        - analyst_rating_change (last 3 months: upgraded/stable/downgraded)
        - turnover_rate, volume_ratio
        """
        prices = stock.get('prices', [])
        ma_20 = stock.get('ma_20', 0)
        ma_50 = stock.get('ma_50', 0)
        ma_100 = stock.get('ma_100', 0)
        ma_200 = stock.get('ma_200', 0)
        current_price = stock.get('current_price', prices[-1] if prices else 0)
        eps_growth = stock.get('eps_growth', 0)
        revenue_growth = stock.get('revenue_growth', 0)
        pe = stock.get('pe', 30)
        analyst_change = stock.get('analyst_rating_change', 'stable')

        # === 1. 均线排列 ===
        ma_align_score, ma_align_label = self._analyze_ma_alignment(
            current_price, ma_20, ma_50, ma_100, ma_200
        )

        # === 2. 股价离均线距离 ===
        deviation_score, deviation_warning = self._analyze_deviation(
            current_price, ma_20, ma_50, ma_200
        )

        # === 3. 趋势阶段识别 ===
        trend_phase = self._identify_trend_phase(
            prices, current_price, ma_20, ma_50, ma_200
        )

        # === 4. 基本面支撑 ===
        fundamental_support, fund_score = self._analyze_fundamental_support(
            eps_growth, revenue_growth, pe, current_price, ma_20
        )

        # === 5. 预期修正 ===
        expectation_revision, expect_score = self._analyze_expectation(analyst_change)

        # === 6. FOMO 风险 ===
        fomo_risk, fomo_score = self._analyze_fomo_risk(
            prices, current_price, ma_20, deviation_warning
        )

        # === 7. 综合健康度评分 ===
        weights = {
            "ma_alignment": 0.25,
            "deviation": 0.15,
            "fundamental": 0.30,
            "expectation": 0.15,
            "fomo_risk": 0.15  # 反向
        }
        health_score = (
            ma_align_score * weights["ma_alignment"] +
            deviation_score * weights["deviation"] +
            fund_score * weights["fundamental"] +
            expect_score * weights["expectation"] +
            fomo_score * weights["fomo_risk"]
        )

        # === 8. 投资建议 ===
        recommendation = self._make_recommendation(health_score, trend_phase, deviation_warning, fomo_risk)

        # === 9. 警告 ===
        warnings = self._generate_warnings(
            ma_align_label, deviation_warning, fundamental_support,
            fomo_risk, trend_phase, prices
        )

        return HealthReport(
            code=stock.get('code', ''),
            name=stock.get('name', ''),
            health_score=round(health_score, 1),
            trend_phase=trend_phase,
            ma_alignment=ma_align_label,
            ma_deviation_warning=deviation_warning,
            fundamental_support=fundamental_support,
            expectation_revision=expectation_revision,
            fomo_risk=fomo_risk,
            recommendation=recommendation,
            health_factors={
                "ma_alignment": round(ma_align_score, 1),
                "deviation": round(deviation_score, 1),
                "fundamental": round(fund_score, 1),
                "expectation": round(expect_score, 1),
                "fomo_risk": round(fomo_score, 1),
            },
            warnings=warnings
        )

    def _analyze_ma_alignment(self, price, ma20, ma50, ma100, ma200):
        """均线排列分析"""
        if not all([ma20, ma50, ma100, ma200, price]):
            return 50, "unknown"

        # 完美多头: P > MA20 > MA50 > MA100 > MA200
        if price > ma20 > ma50 > ma100 > ma200:
            return 95, "perfect"

        # 良好多头: 接近完美排列
        diffs = [price - ma20, ma20 - ma50, ma50 - ma100, ma100 - ma200]
        diffs_pct = [d / ma200 * 100 for d in diffs]
        if all(d > 0 for d in diffs_pct):
            return 80, "good"

        # 部分多头: 短期均线上穿长期
        if ma20 > ma50 and price > ma20:
            return 65, "good"

        # 混乱/警告: 均线缠绕
        if abs(price / ma50 - 1) < 0.05:
            return 45, "warning"

        # 空头: 跌破均线
        if price < ma50 < ma200:
            return 25, "broken"

        return 35, "warning"

    def _analyze_deviation(self, price, ma20, ma50, ma200):
        """股价偏离均线分析"""
        if not ma20 or not price:
            return 50, "none"

        # 离MA20偏离度
        dev_ma20 = (price / ma20 - 1) * 100

        # 离MA50偏离度
        dev_ma50 = (price / ma50 - 1) * 100 if ma50 else dev_ma20

        # 离MA200偏离度
        dev_ma200 = (price / ma200 - 1) * 100 if ma200 else 0

        # 偏离度过高 = 短线超买
        if dev_ma20 > 30 or dev_ma200 > 80:
            return 25, "extreme_overbought"
        elif dev_ma20 > 20 or dev_ma200 > 50:
            return 50, "overbought"
        elif dev_ma20 > 10:
            return 80, "mild_premium"
        elif dev_ma20 < -20:
            return 70, "deep_discount"  # 深度折价=可能的机会
        elif dev_ma20 < -10:
            return 85, "discount"
        else:
            return 95, "none"

    def _identify_trend_phase(self, prices, current, ma20, ma50, ma200):
        """趋势阶段识别"""
        if len(prices) < 60:
            return "unknown"

        # 阶段1: 吸筹期 - 价格横盘, 均线缠绕
        recent_volatility = self._calc_volatility(prices[-60:])
        if recent_volatility < 15 and abs(current / ma50 - 1) < 0.05:
            return "accumulation"

        # 阶段2: 拉升期 - 价格突破均线, 均线多头排列
        if current > ma20 > ma50 > ma200:
            # 短期涨幅
            short_return = (current / prices[-20] - 1) * 100 if len(prices) >= 20 else 0
            if short_return > 30:
                return "markup_late"  # 拉升末期
            return "markup"

        # 阶段3: 派发期 - 价格高位震荡, 均线开始走平
        if current > ma50 and ma50 > ma200 and abs(current / ma50 - 1) < 0.10:
            return "distribution"

        # 阶段4: 下跌期 - 跌破均线
        if current < ma50 < ma200:
            return "markdown"

        # 阶段5: 修复期 - 反弹中, 但均线尚未修复
        if ma20 < ma50 and current > ma20:
            return "recovery"

        return "transition"

    def _calc_volatility(self, prices):
        """计算波动率"""
        if len(prices) < 2:
            return 0
        returns = [(prices[i] / prices[i-1] - 1) * 100 for i in range(1, len(prices))]
        if not returns:
            return 0
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        return math.sqrt(variance) * math.sqrt(252)

    def _analyze_fundamental_support(self, eps_growth, revenue_growth, pe, price, ma20):
        """基本面支撑分析"""
        # 估值合理性
        peg = pe / max(eps_growth, 1) if eps_growth > 0 else 99

        # 增速 vs 估值
        score = 0
        if eps_growth >= 30 and peg < 1.5:
            score += 50
        elif eps_growth >= 20 and peg < 2.0:
            score += 40
        elif eps_growth >= 10 and peg < 3.0:
            score += 30
        elif eps_growth > 0:
            score += 20
        else:
            score += 5

        # 营收增长支持
        if revenue_growth >= 30:
            score += 30
        elif revenue_growth >= 20:
            score += 25
        elif revenue_growth >= 10:
            score += 15
        elif revenue_growth > 0:
            score += 10

        # 趋势中基本面支撑
        if price > ma20 and eps_growth > 15:
            score += 20
        elif price > ma20:
            score += 10

        score = min(100, score)

        if score >= 75:
            return "strong", score
        elif score >= 50:
            return "neutral", score
        else:
            return "weak", score

    def _analyze_expectation(self, change):
        """预期修正分析"""
        if change == "upgraded":
            return "upgraded", 90
        elif change == "stable":
            return "stable", 60
        elif change == "slight_downgrade":
            return "stable", 45
        else:
            return "downgraded", 25

    def _analyze_fomo_risk(self, prices, current, ma20, deviation_warning):
        """FOMO (Fear of Missing Out) 逃逸风险"""
        if len(prices) < 60:
            return "unknown", 50

        # 短期涨幅
        short_ret_5 = (current / prices[-5] - 1) * 100 if len(prices) >= 5 else 0
        short_ret_20 = (current / prices[-20] - 1) * 100 if len(prices) >= 20 else 0

        # 成交量放大情况（如果提供）
        turnover = 0  # 默认

        score = 100  # 起始分(无风险)
        risk_level = "low"

        # 短期暴涨
        if short_ret_5 > 15 or short_ret_20 > 40:
            score -= 40
            risk_level = "extreme"
        elif short_ret_5 > 8 or short_ret_20 > 25:
            score -= 25
            risk_level = "high"
        elif short_ret_5 > 4 or short_ret_20 > 15:
            score -= 10
            risk_level = "medium"

        # 偏离度警告
        if deviation_warning == "extreme_overbought":
            score -= 30
            risk_level = "extreme"
        elif deviation_warning == "overbought":
            score -= 15
            if risk_level == "low":
                risk_level = "medium"

        return risk_level, max(0, score)

    def _make_recommendation(self, health, phase, deviation, fomo):
        """生成建议"""
        if health >= 80 and phase in ["markup", "accumulation"] and fomo in ["low", "medium"]:
            return "buy"
        elif health >= 65 and fomo in ["low", "medium"]:
            return "hold"
        elif fomo in ["high", "extreme"] or deviation in ["overbought", "extreme_overbought"]:
            return "trim"
        elif health < 40 or phase == "markdown":
            return "sell"
        else:
            return "avoid"

    def _generate_warnings(self, ma_align, deviation, fundamental, fomo, phase, prices):
        """生成警告"""
        warnings = []

        if ma_align == "broken":
            warnings.append("⚠️ 均线空头排列，趋势破坏")

        if deviation == "extreme_overbought":
            warnings.append("🔥 股价远离均线，短线超买严重")
        elif deviation == "overbought":
            warnings.append("⚡ 股价偏离均线较多，警惕回调")

        if fundamental == "weak":
            warnings.append("💼 基本面无法支撑当前走势")

        if fomo == "extreme":
            warnings.append("🎯 FOMO情绪极端，逃逸风险高")
        elif fomo == "high":
            warnings.append("⚠️ FOMO情绪升温，谨慎追高")

        if phase == "markup_late":
            warnings.append("📈 拉升末期，注意趋势拐点")
        elif phase == "distribution":
            warnings.append("📊 派发期特征显现")
        elif phase == "markdown":
            warnings.append("📉 下跌趋势中，勿轻易抄底")

        # 短期涨幅过大
        if len(prices) >= 20:
            short_ret = (prices[-1] / prices[-20] - 1) * 100
            if short_ret > 30:
                warnings.append(f"🚀 20日涨幅{short_ret:.0f}%，获利盘压力大")

        return warnings
