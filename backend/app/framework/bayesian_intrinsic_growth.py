"""
Bayesian Intrinsic Growth Valuation: 市场定价合理性框架 V1.0

核心问题: 股价上涨是基本面驱动还是情绪FOMO？
市场是不是已经提前透支了未来？

核心思路: 用贝叶斯方法，把信息转化为未来3-5年增长概率的变化
- 先验 (Prior): 市场预期增长率
- 似然 (Likelihood): 新信息(订单/收入/预期修正等)
- 后验 (Posterior): 调整后的真实增长概率分布

最终输出:
- implied_growth_rate (市场隐含增长率)
- intrinsic_growth_rate (基本面隐含增长率)
- mispricing_score (定价偏差: -100到+100)
- 内在价值 vs 当前价格
- 上涨驱动归因 (基本面% vs 情绪%)
"""

from dataclasses import dataclass, field
from typing import Optional
import math


@dataclass
class BayesianValuation:
    """贝叶斯内在增长估值"""
    code: str
    name: str
    current_price: float
    intrinsic_value: float  # 内在价值
    upside_pct: float  # 上涨空间 %
    implied_growth_rate: float  # 市场隐含增长率 %
    intrinsic_growth_rate: float  # 真实增长率 %
    mispricing_score: float  # -100(低估) ~ +100(高估)
    price_decomposition: dict  # 价格分解: 基本面% / 情绪%
    intrinsic_drivers: list[str]  # 内在驱动
    probability_distribution: dict  # 不同增长率的概率
    recommendation: str  # strong_buy / buy / hold / trim / sell
    confidence_interval: tuple  # (low, high)
    catalysts: list[str] = field(default_factory=list)


class BayesianIntrinsicGrowthValuation:
    """贝叶斯内在增长估值分析器"""

    # 贝叶斯先验参数
    DEFAULT_DISCOUNT_RATE = 0.10  # 折现率10%
    FORECAST_YEARS = 5  # 5年预测期
    TERMINAL_GROWTH = 0.03  # 永续增长率

    def __init__(self):
        pass

    def analyze(self, stock: dict) -> BayesianValuation:
        """
        主入口

        stock 字段:
        - code, name
        - current_price, market_cap
        - eps_ttm (TTM EPS)
        - eps_growth_ltm (过去12个月增长率)
        - revenue_growth_ltm
        - forward_eps (未来12个月一致预期)
        - analyst_target_price
        - new_info (dict): 近期新信息
            {"order_book": +30, "guidance": +20, "new_customer": +15, ...}
        - sentiment_score (-1 to +1)
        """
        current_price = stock.get('current_price', 0)
        eps = stock.get('eps_ttm', 0)
        eps_growth = stock.get('eps_growth_ltm', 15)
        forward_eps = stock.get('forward_eps', eps * 1.15)
        analyst_target = stock.get('analyst_target_price', current_price * 1.1)
        new_info = stock.get('new_info', {})
        sentiment = stock.get('sentiment_score', 0)

        # === 1. 计算市场隐含增长率 (逆向DCF) ===
        # 当前价格隐含的增长率 (反推)
        implied_growth = self._calculate_implied_growth(
            current_price, eps, self.DEFAULT_DISCOUNT_RATE
        )

        # === 2. 计算真实增长率 (基于历史+新信息贝叶斯更新) ===
        intrinsic_growth = self._calculate_intrinsic_growth(
            eps_growth, new_info
        )

        # === 3. 计算内在价值 ===
        intrinsic_value = self._calculate_intrinsic_value(
            forward_eps, intrinsic_growth
        )

        # === 4. 定价偏差评分 ===
        mispricing_score = self._calc_mispricing_score(
            intrinsic_value, current_price, intrinsic_growth, implied_growth
        )

        # === 5. 价格分解: 基本面 vs 情绪 ===
        price_decomp = self._decompose_price(
            current_price, intrinsic_value, sentiment
        )

        # === 6. 增长概率分布 ===
        prob_dist = self._build_probability_distribution(
            intrinsic_growth, new_info, sentiment
        )

        # === 7. 内在驱动 ===
        intrinsic_drivers = self._identify_intrinsic_drivers(
            eps_growth, new_info, intrinsic_growth
        )

        # === 8. 催化剂 ===
        catalysts = self._identify_catalysts(new_info, intrinsic_growth)

        # === 9. 置信区间 ===
        confidence_interval = self._calc_confidence_interval(
            intrinsic_value, intrinsic_growth, prob_dist
        )

        # === 10. 上涨空间 ===
        upside_pct = (intrinsic_value / current_price - 1) * 100 if current_price > 0 else 0

        # === 11. 投资建议 ===
        recommendation = self._make_recommendation(
            mispricing_score, upside_pct, intrinsic_growth, implied_growth
        )

        return BayesianValuation(
            code=stock.get('code', ''),
            name=stock.get('name', ''),
            current_price=current_price,
            intrinsic_value=round(intrinsic_value, 2),
            upside_pct=round(upside_pct, 2),
            implied_growth_rate=round(implied_growth, 2),
            intrinsic_growth_rate=round(intrinsic_growth, 2),
            mispricing_score=round(mispricing_score, 1),
            price_decomposition={k: round(v, 1) for k, v in price_decomp.items()},
            intrinsic_drivers=intrinsic_drivers,
            probability_distribution=prob_dist,
            recommendation=recommendation,
            confidence_interval=confidence_interval,
            catalysts=catalysts
        )

    def _calculate_implied_growth(self, price, eps, discount_rate):
        """计算市场隐含增长率（逆向DCF）"""
        if eps <= 0 or price <= 0:
            return 15.0  # 默认值

        # PE = price / eps
        pe = price / eps

        # Gordon增长模型反向: g = r - (EPS/Price) = r - 1/PE
        # 修正: 考虑成长股通常PE > 1/r
        # 简化: 隐含g ≈ (1/PE)^(-0.5) * 10 (经验公式)
        # 或者: 用PE倒推市场预期
        # PE=20 → 隐含g ≈ 12%
        # PE=40 → 隐含g ≈ 18%
        # PE=80 → 隐含g ≈ 25%

        # 用更精确的反推
        # PE_high_growth ≈ 1/(r-g) → g ≈ r - 1/PE
        implied_g = max(0, min(40, (discount_rate - 1/pe) * 100))

        # 但市场对成长股通常更乐观，加入情绪调整
        # 这里假设分析师一致预期已部分定价
        return max(2, implied_g)

    def _calculate_intrinsic_growth(self, base_growth, new_info):
        """贝叶斯更新: 基于历史增长率+新信息 → 真实增长率"""
        # 先验: 历史增长率
        prior = base_growth / 100  # 转为小数

        # 新信息似然: 把新信息转化为增长率调整
        # 各种信息的"贝叶斯因子"
        info_impact = 0
        info_count = 0

        info_weights = {
            "order_book_growth": 0.05,        # 订单增长+5%
            "revenue_beat": 0.03,              # 营收超预期+3%
            "eps_beat": 0.04,                  # EPS超预期+4%
            "guidance_raised": 0.05,           # 指引上调+5%
            "guidance_lowered": -0.05,
            "new_customer": 0.02,
            "market_share_gain": 0.03,
            "product_launch": 0.04,
            "capacity_expansion": 0.02,
            "regulatory_approval": 0.05,
            "loss_of_customer": -0.04,
            "price_pressure": -0.03,
            "competition": -0.03,
            "macro_headwind": -0.02,
            "macro_tailwind": 0.02,
        }

        for key, value in new_info.items():
            if key in info_weights:
                info_impact += info_weights[key] * value
                info_count += 1

        # 贝叶斯更新 (简化版)
        # 新增长率 = 历史增长率 + 信息调整 (权重: 0.6历史 + 0.4新信息)
        # 信息调整通过info_impact汇总

        if info_count > 0:
            # 信息强度 (基于信息数量和累计影响)
            info_strength = min(0.5, info_count * 0.1)
            updated = prior + info_impact * info_strength
        else:
            updated = prior

        # 限制合理范围
        return max(-0.20, min(0.50, updated)) * 100  # 转回%

    def _calculate_intrinsic_value(self, forward_eps, growth_rate):
        """计算内在价值 (DCF折现)"""
        if forward_eps <= 0:
            return 0

        g = growth_rate / 100
        r = self.DEFAULT_DISCOUNT_RATE
        terminal_g = self.TERMINAL_GROWTH

        # 5年现金流折现 + 终值
        intrinsic = 0
        future_eps = forward_eps

        for year in range(1, self.FORECAST_YEARS + 1):
            future_eps *= (1 + g)
            discount = (1 + r) ** year
            intrinsic += future_eps / discount

        # 终值
        terminal_value = future_eps * (1 + terminal_g) / (r - terminal_g)
        intrinsic += terminal_value / ((1 + r) ** self.FORECAST_YEARS)

        return intrinsic

    def _calc_mispricing_score(self, intrinsic_value, current_price, intrinsic_growth, implied_growth):
        """定价偏差评分
        负值=低估(内在>价格), 正值=高估(价格>内在)
        """
        if current_price <= 0:
            return 0

        # 价值偏差: (current - intrinsic) / intrinsic
        # 当前价格相对内在价值高 = 正值(贵)
        # 当前价格相对内在价值低 = 负值(便宜)
        if intrinsic_value > 0:
            value_mispricing = (current_price / intrinsic_value - 1) * 100
        else:
            value_mispricing = 50 if current_price > 0 else 0

        # 增长预期偏差: 市场隐含超过真实 = 正值(贵)
        growth_diff = implied_growth - intrinsic_growth
        growth_mispricing = growth_diff * 3

        # 综合
        mispricing = value_mispricing * 0.6 + growth_mispricing * 0.4
        return max(-100, min(100, mispricing))

    def _decompose_price(self, current_price, intrinsic_value, sentiment):
        """价格分解: 基本面贡献 vs 情绪贡献"""
        if current_price <= 0:
            return {"fundamental": 50, "sentiment": 50}

        fundamental_value = intrinsic_value
        sentiment_value = current_price - intrinsic_value

        fundamental_pct = (fundamental_value / current_price) * 100 if current_price > 0 else 50
        sentiment_pct = max(0, (sentiment_value / current_price) * 100)

        # 归一化
        total = fundamental_pct + sentiment_pct
        if total > 0:
            fundamental_pct = fundamental_pct / total * 100
            sentiment_pct = sentiment_pct / total * 100

        return {
            "fundamental": fundamental_pct,
            "sentiment": sentiment_pct
        }

    def _build_probability_distribution(self, intrinsic_growth, new_info, sentiment):
        """构建增长率概率分布"""
        g = intrinsic_growth / 100
        # 基于贝叶斯更新构建离散分布
        scenarios = [
            ("strong_bear", g - 0.20, 0.05),
            ("bear", g - 0.10, 0.15),
            ("base_bear", g - 0.05, 0.20),
            ("base", g, 0.30),
            ("base_bull", g + 0.05, 0.15),
            ("bull", g + 0.10, 0.10),
            ("strong_bull", g + 0.20, 0.05),
        ]

        # 根据情绪调整权重
        adjusted = []
        for scenario, growth, weight in scenarios:
            if sentiment > 0:
                # 情绪乐观: 偏多
                if growth > g:
                    weight *= (1 + sentiment * 0.3)
                else:
                    weight *= (1 - sentiment * 0.2)
            elif sentiment < 0:
                # 情绪悲观: 偏空
                if growth < g:
                    weight *= (1 - sentiment * 0.3)
                else:
                    weight *= (1 + sentiment * 0.2)
            adjusted.append((scenario, round(growth * 100, 1), round(weight, 3)))

        # 归一化
        total_w = sum(w for _, _, w in adjusted)
        if total_w > 0:
            adjusted = [(s, g, w/total_w) for s, g, w in adjusted]

        return dict((s, {"growth": g, "probability": p}) for s, g, p in adjusted)

    def _identify_intrinsic_drivers(self, base_growth, new_info, intrinsic_growth):
        """识别内在驱动"""
        drivers = []
        if base_growth > 0:
            drivers.append(f"历史EPS增长{base_growth:.1f}%提供基础")

        if new_info.get("order_book_growth", 0) > 0.2:
            drivers.append("订单簿强劲增长，需求可见度高")
        if new_info.get("revenue_beat", 0) > 0.1:
            drivers.append("近期营收超预期")
        if new_info.get("guidance_raised", 0) > 0:
            drivers.append("管理层指引上调")
        if new_info.get("new_customer", 0) > 0:
            drivers.append("新客户开拓")
        if new_info.get("market_share_gain", 0) > 0:
            drivers.append("市场份额提升")
        if new_info.get("product_launch", 0) > 0:
            drivers.append("新产品发布催化")

        if intrinsic_growth > 30:
            drivers.append("整体处于高速增长通道")
        elif intrinsic_growth > 15:
            drivers.append("处于稳健增长通道")
        elif intrinsic_growth < 0:
            drivers.append("增长承压，需要警惕")

        return drivers

    def _identify_catalysts(self, new_info, intrinsic_growth):
        """未来催化剂"""
        catalysts = []
        if new_info.get("regulatory_approval", 0) > 0:
            catalysts.append("监管批准事件")
        if new_info.get("product_launch", 0) > 0:
            catalysts.append("新产品发布")
        if intrinsic_growth > 25:
            catalysts.append("下季度业绩报告")
            catalysts.append("全年指引更新")

        catalysts.append("行业景气度变化")
        catalysts.append("竞争格局演变")
        return catalysts

    def _calc_confidence_interval(self, intrinsic_value, intrinsic_growth, prob_dist):
        """计算置信区间"""
        if intrinsic_value <= 0:
            return (0, 0)

        # 基于bear/bull场景
        bear_growth = prob_dist.get("bear", {}).get("growth", intrinsic_growth - 10) / 100
        bull_growth = prob_dist.get("bull", {}).get("growth", intrinsic_growth + 10) / 100

        bear_value = self._calculate_intrinsic_value(
            self._estimate_forward_eps(intrinsic_value, intrinsic_growth / 100),
            bear_growth * 100
        )
        bull_value = self._calculate_intrinsic_value(
            self._estimate_forward_eps(intrinsic_value, intrinsic_growth / 100),
            bull_growth * 100
        )

        return (round(min(bear_value, intrinsic_value) * 0.85, 2),
                round(max(bull_value, intrinsic_value) * 1.15, 2))

    def _estimate_forward_eps(self, intrinsic_value, growth):
        """从内在价值反推forward EPS"""
        r = self.DEFAULT_DISCOUNT_RATE
        # 简化: intrinsic_value ≈ forward_eps * (1+g)/(r-g) for perpetuity
        if r > growth:
            return intrinsic_value * (r - growth) / (1 + growth)
        return intrinsic_value * 0.10

    def _make_recommendation(self, mispricing, upside, intrinsic_g, implied_g):
        """投资建议
        mispricing: 负值=低估(便宜), 正值=高估(贵)
        """
        if mispricing <= -30:
            return "strong_buy"  # 显著低估
        elif mispricing <= -10:
            return "buy"  # 适度低估
        elif mispricing <= 20:
            return "hold"  # 估值合理
        elif mispricing <= 40:
            return "trim"  # 偏贵
        else:
            return "sell"  # 严重高估
