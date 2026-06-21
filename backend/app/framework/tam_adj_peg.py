"""
TAM-Adj-PEG: 成长股估值框架 V1.0

核心问题: 增长还能持续多久？市场空间够不够大？
公司有没有定价权？增长能不能转化成利润？竞争会不会打掉利润率？

传统 PEG = PE / 增长率 (只看PE和增速)
TAM-Adj-PEG 在传统PEG基础上，调整以下维度：
1. TAM空间 (Total Addressable Market) - 市场是否够大
2. 渗透率 (Penetration Rate) - 增长剩余空间
3. 定价权 (Pricing Power) - 毛利率稳定性
4. 利润率转化 (Margin Expansion) - 增长是否转化为利润
5. 护城河 (Moat Strength) - 竞争优势持续性

适用: AI、半导体、机器人、SaaS、医疗科技等高成长公司
"""

from dataclasses import dataclass, field
import math


@dataclass
class GrowthValuation:
    """成长股估值结果"""
    code: str
    name: str
    traditional_peg: float  # 传统PEG
    tam_adj_peg: float  # TAM调整后PEG
    valuation_verdict: str  # cheap / fair / expensive / bubble
    tam_score: float  # 0-100 TAM空间分
    runway_years: float  # 增长跑道年数
    pricing_power_score: float  # 0-100
    margin_quality_score: float  # 0-100
    moat_score: float  # 0-100
    growth_quality: str  # high / medium / low
    recommendation: str
    key_risks: list[str] = field(default_factory=list)


class TAMAdjPEGAanalyzer:
    """TAM-Adjusted PEG 估值分析器"""

    # TAM参考表 (单位: 亿元 RMB)
    TAM_REFERENCE = {
        "AI": {"TAM_2025": 5000, "CAGR": 35, "tam_growth_rate": 0.35},
        "AI数据中心液冷": {"TAM_2025": 800, "CAGR": 50, "tam_growth_rate": 0.50},
        "半导体设备": {"TAM_2025": 3000, "CAGR": 20, "tam_growth_rate": 0.20},
        "半导体材料": {"TAM_2025": 1500, "CAGR": 15, "tam_growth_rate": 0.15},
        "机器人": {"TAM_2025": 2000, "CAGR": 30, "tam_growth_rate": 0.30},
        "工业机器人": {"TAM_2025": 1200, "CAGR": 18, "tam_growth_rate": 0.18},
        "医疗SaaS": {"TAM_2025": 600, "CAGR": 25, "tam_growth_rate": 0.25},
        "创新药": {"TAM_2025": 4000, "CAGR": 12, "tam_growth_rate": 0.12},
        "新能源车": {"TAM_2025": 8000, "CAGR": 22, "tam_growth_rate": 0.22},
        "储能": {"TAM_2025": 2500, "CAGR": 40, "tam_growth_rate": 0.40},
        "光伏": {"TAM_2025": 6000, "CAGR": 15, "tam_growth_rate": 0.15},
        "其他": {"TAM_2025": 1000, "CAGR": 10, "tam_growth_rate": 0.10}
    }

    def __init__(self):
        pass

    def analyze(self, stock: dict) -> GrowthValuation:
        """
        主入口: 评估成长股估值合理性

        stock 字段:
        - code, name, industry
        - pe, growth_rate (%)
        - market_cap, revenue, market_share
        - gross_margin, operating_margin
        - moat_indicators (dict): {"brand": 0-10, "tech": 0-10, "scale": 0-10, "network": 0-10}
        """
        pe = stock.get('pe', 30)
        growth = max(5, stock.get('growth_rate', 15))  # 最低5%
        industry = stock.get('industry', '其他')

        # === 1. 传统 PEG ===
        traditional_peg = pe / growth if growth > 0 else 99

        # === 2. TAM分析 ===
        tam_info = self._get_tam_info(industry)
        tam_score = self._calc_tam_score(stock, tam_info)
        runway_years = self._calc_runway(stock, tam_info)

        # === 3. 定价权 ===
        pricing_power = self._calc_pricing_power(stock)

        # === 4. 利润率质量 ===
        margin_quality = self._calc_margin_quality(stock)

        # === 5. 护城河 ===
        moat_score = self._calc_moat_score(stock)

        # === 6. TAM调整PEG ===
        # 调整因子 = (TAM分 + 定价权 + 利润率 + 护城河) / 400
        quality_score = (tam_score + pricing_power + margin_quality + moat_score) / 4

        # 调整PEG: 质量越高，允许PEG越高
        # 例如: 质量分80时, PEG=1.5仍合理; 质量分40时, PEG=0.8就偏贵
        peg_threshold = 0.5 + (quality_score / 100) * 1.5  # 0.5 ~ 2.0

        tam_adj_peg = traditional_peg / (quality_score / 100)
        # 让adj_peg和threshold同向比较: adj_peg越低越便宜
        # 如果 quality=80, tam_adj_peg = trad_peg / 0.8 = trad_peg * 1.25 (好公司允许更贵)
        # 实际上: 我们比较 tam_adj_peg 和 peg_threshold 的关系

        # === 7. 估值判断 ===
        ratio = tam_adj_peg / peg_threshold if peg_threshold > 0 else 1.0
        if ratio < 0.7:
            verdict = "cheap"
        elif ratio < 1.0:
            verdict = "fair"
        elif ratio < 1.5:
            verdict = "expensive"
        else:
            verdict = "bubble"

        # === 8. 增长质量 ===
        if quality_score >= 75 and runway_years >= 5:
            growth_quality = "high"
        elif quality_score >= 55 and runway_years >= 3:
            growth_quality = "medium"
        else:
            growth_quality = "low"

        # === 9. 建议 ===
        recommendation = self._make_recommendation(verdict, growth_quality, ratio)

        # === 10. 关键风险 ===
        key_risks = self._identify_risks(stock, growth, verdict)

        return GrowthValuation(
            code=stock.get('code', ''),
            name=stock.get('name', ''),
            traditional_peg=round(traditional_peg, 2),
            tam_adj_peg=round(tam_adj_peg, 2),
            valuation_verdict=verdict,
            tam_score=round(tam_score, 1),
            runway_years=round(runway_years, 1),
            pricing_power_score=round(pricing_power, 1),
            margin_quality_score=round(margin_quality, 1),
            moat_score=round(moat_score, 1),
            growth_quality=growth_quality,
            recommendation=recommendation,
            key_risks=key_risks
        )

    def _get_tam_info(self, industry: str) -> dict:
        """获取行业TAM信息"""
        return self.TAM_REFERENCE.get(industry, self.TAM_REFERENCE["其他"])

    def _calc_tam_score(self, stock: dict, tam_info: dict) -> float:
        """TAM空间评分"""
        tam = tam_info.get("TAM_2025", 1000)
        market_cap = stock.get('market_cap', 100)
        # 行业TAM / 公司市值的比例
        if market_cap > 0:
            ratio = tam / market_cap
            # 比例越大越好 (公司相对市场还小)
            if ratio > 50:
                return 100
            elif ratio > 20:
                return 85
            elif ratio > 10:
                return 70
            elif ratio > 5:
                return 55
            elif ratio > 2:
                return 40
            else:
                return 25
        return 50

    def _calc_runway(self, stock: dict, tam_info: dict) -> float:
        """增长跑道年数（基于渗透率）"""
        growth = stock.get('growth_rate', 15)
        tam_growth = tam_info.get("tam_growth_rate", 0.10)
        market_share = stock.get('market_share', 0.05)  # 默认5%份额

        # 跑道 = log(目标份额/当前份额) / log(1+行业增速)
        target_share = min(0.30, market_share * 5)  # 假设可扩张到5倍
        if market_share > 0 and target_share > market_share and tam_growth > 0:
            years = math.log(target_share / market_share) / math.log(1 + tam_growth)
            return min(15, max(1, years))

        # 默认按增长率反推
        return min(10, max(2, 50 / max(growth, 1)))

    def _calc_pricing_power(self, stock: dict) -> float:
        """定价权评分"""
        gm = stock.get('gross_margin', 25)
        # 高毛利 = 强定价权
        if gm >= 60:
            return 95
        elif gm >= 45:
            return 80
        elif gm >= 30:
            return 65
        elif gm >= 20:
            return 45
        elif gm >= 10:
            return 30
        else:
            return 15

        # 检查毛利率变化趋势
        gm_trend = stock.get('gm_trend', 0)  # 变化百分点
        if gm_trend > 0:
            base = min(100, base + gm_trend * 2)
        return base

    def _calc_margin_quality(self, stock: dict) -> float:
        """利润率质量"""
        op_margin = stock.get('operating_margin', 10)
        gm = stock.get('gross_margin', 25)

        # 毛利率 - 营业利润率 = 费用率
        # 费用率低说明运营效率高
        if gm > 0:
            expense_ratio = (gm - op_margin) / gm * 100
            # 费用率<30% = 高效
            if expense_ratio < 30:
                efficiency = 90
            elif expense_ratio < 50:
                efficiency = 70
            elif expense_ratio < 70:
                efficiency = 50
            else:
                efficiency = 30
        else:
            efficiency = 40

        # 综合: 营业利润率本身也很重要
        if op_margin >= 30:
            op_score = 95
        elif op_margin >= 20:
            op_score = 80
        elif op_margin >= 10:
            op_score = 60
        elif op_margin >= 0:
            op_score = 40
        else:
            op_score = 20

        return (efficiency + op_score) / 2

    def _calc_moat_score(self, stock: dict) -> float:
        """护城河评分"""
        moat = stock.get('moat_indicators', {})
        brand = moat.get('brand', 5)
        tech = moat.get('tech', 5)
        scale = moat.get('scale', 5)
        network = moat.get('network', 5)

        # 加权: 技术40%, 规模25%, 品牌20%, 网络15%
        score = tech * 4 + scale * 2.5 + brand * 2 + network * 1.5
        return min(100, score)

    def _make_recommendation(self, verdict: str, quality: str, ratio: float) -> str:
        """生成投资建议"""
        if verdict == "cheap" and quality == "high":
            return "强烈推荐: 估值便宜+高质量增长"
        elif verdict == "cheap":
            return "关注: 估值便宜但需验证增长质量"
        elif verdict == "fair" and quality == "high":
            return "持有: 估值合理+高质量增长，长期持有"
        elif verdict == "fair":
            return "观望: 估值合理但增长质量一般"
        elif verdict == "expensive" and quality == "high":
            return "谨慎: 估值偏贵但高质量，等待回调"
        elif verdict == "expensive":
            return "回避: 估值偏贵且质量一般"
        else:
            return "强烈回避: 估值泡沫"

    def _identify_risks(self, stock: dict, growth: float, verdict: str) -> list[str]:
        """识别关键风险"""
        risks = []
        if growth > 50:
            risks.append("高增速难以持续，预期下修风险")
        if verdict == "bubble":
            risks.append("估值泡沫，回归压力大")
        if stock.get('market_share', 0.05) < 0.02:
            risks.append("市占率小，竞争压力大")
        if stock.get('gross_margin', 25) < 20:
            risks.append("毛利率低，定价权弱")
        if stock.get('operating_margin', 10) < 5:
            risks.append("盈利能力弱，可能仍在烧钱")
        return risks
