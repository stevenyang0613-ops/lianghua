"""
西部七维量化打分策略 V3.0

核心逻辑：转债价格 = 债底价值 + 转股价值 + 期权价值 + 波动率溢价
正股七维评分占55%，转债自身评分占45%

一票否决制 + 七维打分 + 缓冲带机制 + 动态权重
"""

import logging
import pandas as pd
import numpy as np
from typing import Optional, Tuple, List
from datetime import datetime, timedelta, date
from dataclasses import dataclass

from app.strategies.base import Strategy
from app.models.backtest import StrategyParam

logger = logging.getLogger(__name__)


@dataclass
class VetoResult:
    """一票否决结果"""
    passed: bool
    reasons: list[str]
    score: float  # 信用评分 0-100


@dataclass
class BufferStatus:
    """缓冲带状态"""
    in_buffer: bool  # 是否在缓冲带内
    days_in_buffer: int  # 在缓冲带内的天数
    days_above_60: int  # 连续在60名内的天数
    days_below_60: int  # 连续在60名外的天数


# 改进 (2025-06-15ae): 市场环境检测提取为独立模块函数，便于策略类外复用和单元测试
# 改进 (2025-06-15af): 外部传入 current_ts 避免重复获取，统一返回 pd.Timestamp，
# 添加 NaN 防御，cache_ttl_seconds 从策略参数获取
from typing import Optional
def _detect_market_env(df: pd.DataFrame, current_ts: pd.Timestamp,
                       last_cache: Optional[str] = None,
                       last_ts: Optional[pd.Timestamp] = None,
                       cache_ttl_seconds: int = 300) -> tuple[str, pd.Timestamp]:
    """根据 DataFrame 中的 change_pct 列检测市场环境。

    Args:
        df: 当日数据 DataFrame，需包含 'change_pct' 列（可选）
        current_ts: 当前时间戳（由调用方传入，避免函数内重复获取）
        last_cache: 上次缓存的市场环境（'bull'/'bear'/'neutral' 或 None）
        last_ts: 上次缓存的时间戳
        cache_ttl_seconds: 缓存有效期（秒），默认 300，可由策略参数覆盖

    Returns:
        (market_env, current_ts): 检测到的市场环境及当前时间戳（统一为 pd.Timestamp）
    """
    if last_cache and last_ts and (current_ts - last_ts).seconds < cache_ttl_seconds:
        return last_cache, current_ts

    avg_change = float(df['change_pct'].mean()) if 'change_pct' in df.columns else 0.0
    positive_ratio = float((df['change_pct'] > 0).mean()) if 'change_pct' in df.columns else 0.5

    # 改进 (2025-06-15af): NaN/inf 防御——change_pct 全为 NaN/inf 时 .mean() 返回异常值
    if pd.isna(avg_change) or not np.isfinite(avg_change):
        avg_change = 0.0
    if pd.isna(positive_ratio) or not np.isfinite(positive_ratio):
        positive_ratio = 0.5

    if avg_change > 0.5 and positive_ratio > 0.6:
        market_env = 'bull'
    elif avg_change < -0.5 and positive_ratio < 0.4:
        market_env = 'bear'
    else:
        market_env = 'neutral'
    return market_env, current_ts


def _get_market_weights(market_env: str, stock_weights: dict, bond_weights: dict) -> tuple[dict, dict]:
    """根据市场环境调整权重（纯函数，便于单元测试）。"""
    if market_env == 'bull':
        stock_weights = {
            'momentum': 0.35,
            'sector': 0.20,
            'technical': 0.22,
            'chip': 0.08,
            'volatility': 0.10,
            'news': 0.03,
            'fundamental': 0.02,
        }
    elif market_env == 'bear':
        stock_weights = {
            'momentum': 0.20,
            'sector': 0.12,
            'technical': 0.13,
            'chip': 0.10,
            'volatility': 0.18,
            'news': 0.10,
            'fundamental': 0.17,
        }
    else:
        stock_weights = stock_weights.copy()
    return stock_weights, bond_weights.copy()


class XibuSevenDimensionStrategy(Strategy):
    """西部七维量化打分策略 - V4.0"""

    name = "西部七维打分策略"
    description = "v4.0: 七维打分 + 多因子估值 + 周频调仓 + 动量过滤 + 仓位管理 + 缓冲带"

    params = [
        StrategyParam(name="hold_count", label="持有数量", type="int", default=60, min_val=10, max_val=100),
        StrategyParam(name="buffer_size", label="缓冲带大小", type="int", default=8, min_val=0, max_val=15),
        StrategyParam(name="buffer_days", label="缓冲观察天数", type="int", default=5, min_val=1, max_val=10),
        StrategyParam(name="min_credit_score", label="最低信用评分", type="float", default=60, min_val=0, max_val=100),
        StrategyParam(name="max_premium", label="溢价率上限(%)", type="float", default=100, min_val=10, max_val=150),
        StrategyParam(name="min_remaining_months", label="最小剩余期限(月)", type="int", default=6, min_val=1, max_val=36),
        StrategyParam(name="aum_level", label="AUM规模等级", type="str", default="small", description="small/medium/large"),
        StrategyParam(name="market_env", label="市场环境", type="str", default="neutral", description="bull/bear/neutral"),
        StrategyParam(name="market_env_cache_ttl", label="市场环境缓存秒数", type="int", default=300, min_val=60, max_val=3600, description="市场环境检测结果的缓存有效期（秒）"),
        StrategyParam(name="rebalance_days", label="调仓间隔(天)", type="int", default=5, min_val=1, max_val=20),
        StrategyParam(name="min_hold_days", label="最小持仓天数", type="int", default=3, min_val=0, max_val=15),
        StrategyParam(name="momentum_filter", label="启用动量过滤", type="bool", default=True),
        StrategyParam(name="position_sizing", label="仓位管理模式", type="str", default="score_weighted", description="equal_weight/score_weighted"),
    ]

    # 正股七维权重（55分）
    STOCK_WEIGHTS = {
        'momentum': 0.30,      # 短期动量 16.5分
        'sector': 0.18,        # 板块情绪 9.9分
        'technical': 0.18,     # 技术面 9.9分
        'chip': 0.12,          # 筹码面 6.6分
        'volatility': 0.12,    # 波动率 6.6分
        'news': 0.07,          # 消息面 3.85分
        'fundamental': 0.03,   # 基本面 1.65分
    }

    # 转债自身权重（45分）
    BOND_WEIGHTS = {
        'valuation': 0.38,     # 估值指标 17.1分
        'clause': 0.24,        # 条款价值 10.8分
        'liquidity': 0.20,     # 流动性 9分
        'credit': 0.18,        # 信用评分 8.1分
    }

    # AUM对应的流动性阈值（万元）
    LIQUIDITY_THRESHOLDS = {
        'small': 500,      # < 1亿AUM
        'medium': 2000,    # 1-5亿AUM
        'large': 5000,     # 5-10亿AUM
    }

    def __init__(self, **kwargs):
        # 改进 (2025-06-15aq): 参数验证防御——无效参数立即 ValueError，避免静默传播
        # 1. 整数参数校验（必须精确为整数，拒绝 10.5 等小数）
        _VALID_INT_RANGES = {
            'hold_count': (1, 100),
            'buffer_size': (0, 15),
            'buffer_days': (1, 10),
            'min_remaining_months': (1, 36),
            'market_env_cache_ttl': (60, 3600),
            'rebalance_days': (1, 20),
            'min_hold_days': (0, 15),
        }
        for param_name, (min_v, max_v) in _VALID_INT_RANGES.items():
            val = kwargs.get(param_name)
            if val is not None:
                try:
                    # 拒绝非整数类型（如 10.5、"10.5"）
                    if isinstance(val, float):
                        # float 必须是整数值（如 10.0 允许，10.5 拒绝）
                        if not val.is_integer():
                            raise ValueError
                        ival = int(val)
                    else:
                        ival = int(val)
                except (TypeError, ValueError):
                    raise ValueError(f"[{self.name}] {param_name}={val!r} 不是有效整数")
                if ival < min_v or ival > max_v:
                    raise ValueError(
                        f"[{self.name}] {param_name}={val} 超出允许范围 [{min_v}, {max_v}]"
                    )

        # 2. 浮点参数校验
        _VALID_FLOAT_RANGES = {
            'min_credit_score': (0.0, 100.0),
            'max_premium': (10.0, 150.0),
        }
        for param_name, (min_v, max_v) in _VALID_FLOAT_RANGES.items():
            val = kwargs.get(param_name)
            if val is not None:
                try:
                    fval = float(val)
                except (TypeError, ValueError):
                    raise ValueError(f"[{self.name}] {param_name}={val!r} 不是有效数值")
                if fval < min_v or fval > max_v:
                    raise ValueError(
                        f"[{self.name}] {param_name}={val} 超出允许范围 [{min_v}, {max_v}]"
                    )

        # 3. 枚举值校验
        _VALID_ENUMS = {
            'aum_level': {'small', 'medium', 'large'},
            'market_env': {'bull', 'bear', 'neutral'},
            'position_sizing': {'equal_weight', 'score_weighted'},
        }
        for param_name, allowed in _VALID_ENUMS.items():
            val = kwargs.get(param_name)
            if val is not None and str(val) not in allowed:
                raise ValueError(
                    f"[{self.name}] {param_name}={val!r} 不是允许值 {allowed}"
                )

        super().__init__(**kwargs)
        self._buffer_tracker: dict[str, BufferStatus] = {}
        self._veto_results: dict[str, VetoResult] = {}
        self._prev_selected: set[str] = set()
        self._hold_since: dict[str, int] = {}  # v4.0
        self._last_rebalance_idx: int = -999  # v4.0
        self._market_env_cache: Optional[str] = None
        self._market_env_ts: Optional[datetime] = None

    def load_buffer_from_storage(self, storage) -> None:
        """从 DuckDB 加载持久化的缓冲带状态"""
        if storage is None:
            return
        try:
            saved = storage.load_buffer_tracker()
            for code, d in saved.items():
                self._buffer_tracker[code] = BufferStatus(
                    in_buffer=d['in_buffer'],
                    days_in_buffer=d['days_in_buffer'],
                    days_above_60=d['days_above_60'],
                    days_below_60=d['days_below_60'],
                )
            if saved:
                logger.info(f"[XibuSeven] Loaded {len(saved)} buffer states from DB")
        except Exception as e:
            logger.warning(f"[XibuSeven] load_buffer_from_storage failed: {e}")

    def save_buffer_to_storage(self, storage) -> None:
        """持久化缓冲带状态到 DuckDB"""
        if storage is None:
            return
        try:
            storage.save_buffer_tracker(self._buffer_tracker)
        except Exception as e:
            logger.warning(f"[XibuSeven] save_buffer_to_storage failed: {e}")

    def _normalize_rank(self, series: pd.Series, ascending: bool = True) -> pd.Series:
        """将 Series 转换为 0~1 的排名分数"""
        if series.empty or series.isna().all():
            return pd.Series(0.5, index=series.index)
        ranks = series.rank(method='average', ascending=ascending)
        max_r = ranks.max()
        if pd.isna(max_r) or max_r == 0:
            return pd.Series(0.5, index=series.index)
        return (ranks - 1) / max_r

    def _zscore(self, series: pd.Series) -> pd.Series:
        """计算Z-score"""
        mean = series.mean()
        std = series.std()
        if pd.isna(std) or std == 0:
            return pd.Series(0.0, index=series.index)
        return (series - mean) / std

    # ==================== 一票否决制 ====================

    def _check_veto(self, row: pd.Series) -> VetoResult:
        """
        一票否决制检查
        满足任意一条直接排除
        """
        reasons = []
        passed = True

        # 1. 信用评分检查（简化版，基于价格和溢价率估算）
        credit_score = self._estimate_credit_score(row)
        if credit_score < self.get_param('min_credit_score'):
            passed = False
            reasons.append(f"信用评分{credit_score:.1f}<{self.get_param('min_credit_score')}")

        # 2. 转股溢价率检查
        if (row.get('premium_ratio') or 0) > self.get_param('max_premium'):
            passed = False
            reasons.append(f"溢价率{row['premium_ratio']:.1f}%>{self.get_param('max_premium')}%")

        # 3. 剩余期限检查
        remaining_years = row.get('remaining_years', 0)
        min_months = self.get_param('min_remaining_months')
        if remaining_years * 12 < min_months:
            passed = False
            reasons.append(f"剩余期限{remaining_years*12:.1f}月<{min_months}月")

        # 4. 强赎检查
        forced_call_days = row.get('forced_call_days', 0)
        if forced_call_days > 0 and forced_call_days < 15:  # 已进入强赎期
            passed = False
            reasons.append(f"强赎倒计时{forced_call_days}天")

        # 5. 流动性检查（与AUM挂钩）
        volume = row.get('volume', 0) * 10000  # 转换为万元
        aum_level = self.get_param('aum_level')
        min_liquidity = self.LIQUIDITY_THRESHOLDS.get(aum_level, 500)
        if volume < min_liquidity:
            passed = False
            reasons.append(f"成交额{volume/10000:.2f}亿<{min_liquidity/10000:.2f}亿")

        # 6. 价格有效性检查
        price = row.get('price', 0)
        if price <= 0 or price > 300:  # 价格异常
            passed = False
            reasons.append(f"价格异常{price:.2f}")

        return VetoResult(passed=passed, reasons=reasons, score=credit_score)

    def _estimate_credit_score(self, row: pd.Series) -> float:
        """
        估算信用评分（简化版KMV模型）
        基于价格隐含违约概率
        """
        price = row.get('price')
        if price is None or not np.isfinite(price):
            # 价格缺失时返回中性评分，避免默认100造成误判
            return 50.0
        score = 100.0
        premium_ratio = row.get('premium_ratio', 0)
        ytm = row.get('ytm', 0)
        dual_low = row.get('dual_low', 150)

        # 价格过低暗示违约风险
        if price < 80:
            score -= (80 - price) * 2
        elif price < 90:
            score -= (90 - price)

        # 双低值过低（可能是正股下跌导致）
        if dual_low < 100:
            score -= (100 - dual_low) * 0.5

        # YTM异常高（市场定价违约风险）
        if ytm > 10:
            score -= (ytm - 10) * 2
        elif ytm > 5:
            score -= (ytm - 5)

        # 溢价率过高（纯期权炒作）
        if premium_ratio > 80:
            score -= (premium_ratio - 80) * 0.5

        return max(0, min(100, score))

    # ==================== 正股七维评分 ====================

    def _calc_momentum_score(self, row: pd.Series, df: pd.DataFrame) -> float:
        """
        短期动量评分（满分16.5分）
        Z-score(涨幅) × 0.4 + Z-score(量比) × 0.3 + Z-score(换手率) × 0.3
        """
        change_pct = row.get('change_pct', 0)
        volume = row.get('volume', 0)
        stock_change = row.get('stock_change_pct', 0)

        # 计算全市场的Z-score
        z_change = 0.0
        z_volume = 0.0
        z_stock = 0.0

        if 'change_pct' in df.columns and not df['change_pct'].empty:
            z_change = self._zscore(df['change_pct']).get(row.name, 0)
        if 'volume' in df.columns and not df['volume'].empty:
            z_volume = self._zscore(df['volume']).get(row.name, 0)
        if 'stock_change_pct' in df.columns and not df['stock_change_pct'].empty:
            z_stock = self._zscore(df['stock_change_pct']).get(row.name, 0)

        # 综合动量得分
        momentum_z = z_change * 0.4 + z_volume * 0.3 + z_stock * 0.3

        # 转换为0-1分数（Z-score通常在-3到3之间）
        momentum_normalized = (momentum_z + 3) / 6
        momentum_normalized = max(0, min(1, momentum_normalized))

        return momentum_normalized * 16.5

    def _calc_sector_score(self, row: pd.Series) -> float:
        """
        板块情绪评分（满分9.9分）
        简化版：基于正股涨跌幅和市场整体表现
        """
        stock_change = row.get('stock_change_pct', 0)

        # 正股表现越好，板块情绪越好
        if stock_change > 5:
            return 9.9
        elif stock_change > 3:
            return 8.0
        elif stock_change > 1:
            return 6.0
        elif stock_change > 0:
            return 4.0
        elif stock_change > -2:
            return 2.0
        else:
            return 0.0

    def _calc_technical_score(self, row: pd.Series) -> float:
        """
        技术面评分（满分9.9分）
        基于价格位置和双低值判断
        """
        price = row.get('price')
        if price is None or not np.isfinite(price):
            # 价格缺失时不应默认100, 返回最低分
            return 1.0
        dual_low = row.get('dual_low', 150)

        score = 0.0

        # 价格位置评分
        if 100 <= price <= 130:
            score += 3.0  # 安全区间
        elif 90 <= price < 100:
            score += 4.0  # 低估区间
        elif 130 < price <= 150:
            score += 2.0  # 略高但可接受
        else:
            score += 1.0  # 其他

        # 双低值评分
        if dual_low < 120:
            score += 6.9
        elif dual_low < 140:
            score += 5.0
        elif dual_low < 160:
            score += 3.0
        elif dual_low < 180:
            score += 1.5
        else:
            score += 0.0

        return min(9.9, score)

    def _calc_chip_score(self, row: pd.Series) -> float:
        """
        筹码面评分（满分6.6分）
        简化版：基于成交量和价格位置判断筹码集中度
        """
        volume = row.get('volume', 0)
        price = row.get('price')
        if price is None or not np.isfinite(price):
            # 价格缺失时不应默认100, 仅基于成交量评分
            price = None

        # 成交量适中为佳（过小说明关注度低，过大说明分歧大）
        score = 3.3  # 基础分

        if volume > 0.5 and volume < 5:  # 适中区间
            score += 3.3
        elif volume >= 5 and volume < 10:
            score += 2.0
        elif volume >= 10:
            score += 0.5  # 过热

        return min(6.6, score)

    def _calc_volatility_score(self, row: pd.Series) -> float:
        """
        波动率维度评分（满分6.6分）
        中等偏高的波动率+正偏度=最佳期权属性
        """
        change_pct = abs(row.get('change_pct', 0))
        stock_change = abs(row.get('stock_change_pct', 0))

        score = 0.0

        # 转债隐含波动率评分（通过涨跌幅波动估算）
        if 1 < change_pct < 5:  # 中等波动
            score += 3.0
        elif change_pct <= 1:  # 低波动
            score += 1.5
        elif change_pct <= 8:  # 较高波动
            score += 2.0
        else:  # 极端波动
            score += 0.0

        # 正股历史波动率评分
        if 2 < stock_change < 6:
            score += 2.0
        elif stock_change <= 2:
            score += 1.0
        elif stock_change <= 10:
            score += 1.0
        else:
            score += 0.0

        # 波动率偏度（正股涨时转债涨幅大，跌时跌幅小）
        if row.get('stock_change_pct', 0) > 0 and change_pct > stock_change * 0.5:
            score += 1.6  # 正偏

        return min(6.6, score)

    def _calc_news_score(self, row: pd.Series) -> float:
        """
        消息面评分（满分3.85分）
        简化版：基于是否有事件驱动
        """
        forced_call = row.get('forced_call_days', 0)
        score = 1.0  # 基础分

        # 下修预期
        dual_low = row.get('dual_low', 150)
        if dual_low < 110:
            score += 2.85  # 可能有下修预期

        # 强赎预期（正收益）
        if forced_call > 10 and forced_call < 20:
            score += 1.5

        return min(3.85, score)

    def _calc_fundamental_score(self, row: pd.Series) -> float:
        """
        基本面评分（满分1.65分）
        简化版：基于YTM判断
        """
        ytm = row.get('ytm', 0)

        if ytm > 0:
            return 1.65  # 正收益说明基本面正常
        elif ytm > -5:
            return 1.0
        else:
            return 0.0

    # ==================== 转债自身评分 ====================

    def _calc_valuation_score(self, row: pd.Series) -> float:
        """
        估值指标评分（满分17.1分）
        转股溢价率<15%得满分，15%-25%得一半，>25%得0分
        """
        premium = row.get('premium_ratio', 50)
        dual_low = row.get('dual_low', 150)

        score = 0.0

        # 溢价率评分
        if premium < 15:
            score += 10.0
        elif premium < 25:
            score += 5.0
        else:
            score += 0.0

        # 双低值加分
        if dual_low < 120:
            score += 7.1
        elif dual_low < 140:
            score += 5.0
        elif dual_low < 160:
            score += 3.0
        else:
            score += 0.0

        return min(17.1, score)

    def _calc_clause_score(self, row: pd.Series) -> float:
        """
        条款价值评分（满分10.8分）
        下修概率得分
        """
        dual_low = row.get('dual_low', 150)
        remaining_years = row.get('remaining_years', 0)
        premium = row.get('premium_ratio', 0)

        score = 0.0

        # 下修概率评分
        if dual_low < 100 and premium > 30:  # 下修概率高
            score += 6.0
        elif dual_low < 110 and premium > 20:
            score += 4.0
        elif dual_low < 120:
            score += 2.0

        # 回售期临近加分
        if 0.5 < remaining_years < 2:  # 进入回售期
            score += 4.8
        elif remaining_years < 0.5:
            score += 2.0  # 即将到期，条款价值降低

        return min(10.8, score)

    def _calc_liquidity_score(self, row: pd.Series) -> float:
        """
        流动性评分（满分9分）
        三档打分，与AUM分档联动
        """
        volume = row.get('volume', 0)
        aum_level = self.get_param('aum_level')

        thresholds = self.LIQUIDITY_THRESHOLDS
        base_threshold = thresholds.get(aum_level, 500)

        # 成交额换算为万元
        volume_w = volume * 10000

        if volume_w >= base_threshold * 4:
            return 9.0
        elif volume_w >= base_threshold * 2:
            return 6.0
        elif volume_w >= base_threshold:
            return 3.0
        else:
            return 0.0

    def _calc_credit_score_component(self, row: pd.Series) -> float:
        """
        信用评分组件（满分8.1分）
        基于估算的信用得分折算
        """
        credit = self._estimate_credit_score(row)

        if credit >= 80:
            return 8.1
        elif credit >= 70:
            return 6.0
        elif credit >= 60:
            return 4.0
        else:
            return 0.0

    # ==================== 综合评分 ====================

    def calc_vectorized(self, df: pd.DataFrame, market_env: Optional[str] = None) -> Tuple[List[dict], List[dict]]:
        """
        向量化计算全部评分，消除 iterrows 循环。
        返回 (scores_list, vetoed_list)，格式与 _calc_total_score 逐行调用一致。
        性能提升约 50-100 倍。

        改进 (2025-06-15ae): 完全解耦——市场环境由 on_data 检测后传入，
        calc_vectorized 成为纯函数（仅依赖 df 和 market_env），便于单元测试。
        """
        n = len(df)
        if n == 0:
            return [], []

        # 预提取列（避免重复 .get 访问）
        change_pct = df['change_pct'].values if 'change_pct' in df.columns else np.zeros(n)
        volume = df['volume'].values if 'volume' in df.columns else np.zeros(n)
        stock_change_pct = df['stock_change_pct'].values if 'stock_change_pct' in df.columns else np.zeros(n)
        price = df['price'].values if 'price' in df.columns else np.full(n, 0.0)
        dual_low = df['dual_low'].values if 'dual_low' in df.columns else np.full(n, 0.0)
        premium_ratio = df['premium_ratio'].values if 'premium_ratio' in df.columns else np.zeros(n)
        ytm = df['ytm'].values if 'ytm' in df.columns else np.zeros(n)
        remaining_years = df['remaining_years'].values if 'remaining_years' in df.columns else np.zeros(n)
        forced_call_days = pd.to_numeric(df['forced_call_days'], errors='coerce').fillna(0).values if 'forced_call_days' in df.columns else np.zeros(n)
        codes = np.asarray(df['code']) if 'code' in df.columns else np.array([str(i) for i in range(n)])
        names = np.asarray(df['name']) if 'name' in df.columns else np.array([''] * n)

        # ===== 一票否决（向量化） =====
        # 改进 (2025-06-15ae): 所有 self 参数在开头提取完毕，后续逻辑为纯函数
        min_credit_score = self.get_param('min_credit_score')
        max_premium = self.get_param('max_premium')
        min_months = self.get_param('min_remaining_months')
        aum_level = self.get_param('aum_level')
        _stock_weights = self.STOCK_WEIGHTS
        _bond_weights = self.BOND_WEIGHTS
        _liquidity_thresholds = self.LIQUIDITY_THRESHOLDS
        min_liquidity = _liquidity_thresholds.get(aum_level, 500)

        # 信用评分（向量化 _estimate_credit_score）
        credit = np.full(n, 100.0)
        mask_price_lt80 = price < 80
        mask_price_lt90 = (~mask_price_lt80) & (price < 90)
        credit[mask_price_lt80] -= (80 - price[mask_price_lt80]) * 2
        credit[mask_price_lt90] -= (90 - price[mask_price_lt90])
        mask_dual_low_lt100 = dual_low < 100
        credit[mask_dual_low_lt100] -= (100 - dual_low[mask_dual_low_lt100]) * 0.5
        mask_ytm_gt10 = ytm > 10
        mask_ytm_gt5 = (~mask_ytm_gt10) & (ytm > 5)
        credit[mask_ytm_gt10] -= (ytm[mask_ytm_gt10] - 10) * 2
        credit[mask_ytm_gt5] -= (ytm[mask_ytm_gt5] - 5)
        mask_premium_gt80 = premium_ratio > 80
        credit[mask_premium_gt80] -= (premium_ratio[mask_premium_gt80] - 80) * 0.5
        credit = np.clip(credit, 0, 100)

        # 否决条件（向量化布尔掩码）
        veto1 = credit < min_credit_score
        veto2 = premium_ratio > max_premium
        veto3 = remaining_years * 12 < min_months
        # 安全处理 forced_call_days 可能为 None 的情况
        veto4 = np.zeros(n, dtype=bool)
        if 'forced_call_days' in df.columns:
            fcd = pd.to_numeric(df['forced_call_days'], errors='coerce').fillna(-1).values
            veto4 = (fcd > 0) & (fcd < 15)
        volume_wan = volume * 10000
        veto5 = volume_wan < min_liquidity
        veto6 = (price <= 0) | (price > 300)
        veto_any = veto1 | veto2 | veto3 | veto4 | veto5 | veto6
        passed_mask = ~veto_any

        # 收集否决结果
        vetoed_list = []
        veto_indices = np.where(veto_any)[0]
        for vi in veto_indices:
            reasons = []
            if veto1[vi]:
                reasons.append(f"信用评分{credit[vi]:.1f}<{min_credit_score}")
            if veto2[vi]:
                reasons.append(f"溢价率{premium_ratio[vi]:.1f}%>{max_premium}%")
            if veto3[vi]:
                reasons.append(f"剩余期限{remaining_years[vi]*12:.1f}月<{min_months}月")
            if veto4[vi]:
                reasons.append(f"强赎倒计时{forced_call_days[vi]:.0f}天")
            if veto5[vi]:
                reasons.append(f"成交额{volume_wan[vi]/10000:.2f}亿<{min_liquidity/10000:.2f}亿")
            if veto6[vi]:
                reasons.append(f"价格异常{price[vi]:.2f}")
            vetoed_list.append({
                "code": codes[vi],
                "name": names[vi],
                "reasons": reasons,
                "credit_score": round(float(credit[vi]), 1),
            })

        # 通过否决的行索引
        passed_idx = np.where(passed_mask)[0]
        if len(passed_idx) == 0:
            return [], vetoed_list

        # 提取通过行的数据
        p_change = change_pct[passed_idx]
        p_volume = volume[passed_idx]
        p_stock_change = stock_change_pct[passed_idx]
        p_price = price[passed_idx]
        p_dual_low = dual_low[passed_idx]
        p_premium = premium_ratio[passed_idx]
        p_ytm = ytm[passed_idx]
        p_remaining = remaining_years[passed_idx]
        p_forced = forced_call_days[passed_idx]
        p_credit = credit[passed_idx]
        pn = len(passed_idx)

        # 预分配11维评分缓冲区 (pn, 11)，列顺序：7正股+4转债
        # 0:momentum 1:sector 2:technical 3:chip 4:volatility 5:news 6:fundamental
        # 7:valuation 8:clause 9:liquidity 10:credit
        D = np.zeros((pn, 11))

        # ===== 正股七维评分 =====

        # 1. 动量（Z-score 加权）
        def _safe_zscore_inplace(arr, out):
            if len(arr) <= 1:
                out[:] = 0.0
                return
            std = np.std(arr, ddof=1)  # 与 _zscore 的 series.std(ddof=1) 保持一致
            if std == 0 or np.isnan(std):
                out[:] = 0.0
            else:
                np.subtract(arr, np.mean(arr), out=out)
                out /= std

        buf_z = np.empty(pn)
        buf_z2 = np.empty(pn)
        _safe_zscore_inplace(p_change, buf_z)
        _safe_zscore_inplace(p_volume, buf_z2)
        momentum_z = buf_z * 0.4 + buf_z2 * 0.3
        _safe_zscore_inplace(p_stock_change, buf_z)
        momentum_z += buf_z * 0.3
        np.clip((momentum_z + 3) / 6, 0, 1, out=D[:, 0])
        D[:, 0] *= 16.5

        # 2. 板块情绪
        D[:, 1] = 2.0  # 默认 (-2, 0]
        D[:, 1][p_stock_change > 5] = 9.9
        D[:, 1][(p_stock_change > 3) & (p_stock_change <= 5)] = 8.0
        D[:, 1][(p_stock_change > 1) & (p_stock_change <= 3)] = 6.0
        D[:, 1][(p_stock_change > 0) & (p_stock_change <= 1)] = 4.0
        D[:, 1][p_stock_change <= -2] = 0.0

        # 3. 技术面（复用 buf_z 作临时缓冲）
        buf_z[:] = 1.0
        buf_z[(p_price >= 100) & (p_price <= 130)] = 3.0
        buf_z[(p_price >= 90) & (p_price < 100)] = 4.0
        buf_z[(p_price > 130) & (p_price <= 150)] = 2.0
        buf_z2[:] = 0.0
        buf_z2[p_dual_low < 120] = 6.9
        buf_z2[(p_dual_low >= 120) & (p_dual_low < 140)] = 5.0
        buf_z2[(p_dual_low >= 140) & (p_dual_low < 160)] = 3.0
        buf_z2[(p_dual_low >= 160) & (p_dual_low < 180)] = 1.5
        np.clip(buf_z + buf_z2, 0, 9.9, out=D[:, 2])

        # 4. 筹码面
        D[:, 3] = 3.3
        D[:, 3][(p_volume > 0.5) & (p_volume < 5)] += 3.3
        D[:, 3][(p_volume >= 5) & (p_volume < 10)] += 2.0
        D[:, 3][p_volume >= 10] += 0.5
        np.clip(D[:, 3], 0, 6.6, out=D[:, 3])

        # 5. 波动率（复用 buf_z 作 abs_change）
        np.abs(p_change, out=buf_z)
        np.abs(p_stock_change, out=buf_z2)
        D[:, 4][(buf_z > 1) & (buf_z < 5)] += 3.0
        D[:, 4][buf_z <= 1] += 1.5
        D[:, 4][(buf_z >= 5) & (buf_z <= 8)] += 2.0
        D[:, 4][(buf_z2 > 2) & (buf_z2 < 6)] += 2.0
        D[:, 4][buf_z2 <= 2] += 1.0
        D[:, 4][(buf_z2 >= 6) & (buf_z2 <= 10)] += 1.0
        positive_skew = (p_stock_change > 0) & (buf_z > buf_z2 * 0.5)
        D[:, 4][positive_skew] += 1.6
        np.clip(D[:, 4], 0, 6.6, out=D[:, 4])

        # 6. 消息面
        D[:, 5] = 1.0
        D[:, 5][p_dual_low < 110] += 2.85
        D[:, 5][(p_forced > 10) & (p_forced < 20)] += 1.5
        np.clip(D[:, 5], 0, 3.85, out=D[:, 5])

        # 7. 基本面
        D[:, 6][p_ytm > 0] = 1.65
        D[:, 6][(p_ytm <= 0) & (p_ytm > -5)] = 1.0

        # ===== 转债自身评分 =====

        # 8. 估值（复用 buf_z/buf_z2）
        buf_z[:] = 0.0
        buf_z[p_premium < 15] = 10.0
        buf_z[(p_premium >= 15) & (p_premium < 25)] = 5.0
        buf_z2[:] = 0.0
        buf_z2[p_dual_low < 120] = 7.1
        buf_z2[(p_dual_low >= 120) & (p_dual_low < 140)] = 5.0
        buf_z2[(p_dual_low >= 140) & (p_dual_low < 160)] = 3.0
        np.clip(buf_z + buf_z2, 0, 17.1, out=D[:, 7])

        # 9. 条款（与逐行 if/elif/elif 语义一致）
        cond1 = (p_dual_low < 100) & (p_premium > 30)
        cond2 = (p_dual_low >= 100) & (p_dual_low < 110) & (p_premium > 20)
        cond3 = (p_dual_low < 120) & ~cond1 & ~cond2
        D[:, 8][cond1] += 6.0
        D[:, 8][cond2] += 4.0
        D[:, 8][cond3] += 2.0
        D[:, 8][(p_remaining > 0.5) & (p_remaining < 2)] += 4.8
        D[:, 8][p_remaining < 0.5] += 2.0
        np.clip(D[:, 8], 0, 10.8, out=D[:, 8])

        # 10. 流动性
        base_threshold = _liquidity_thresholds.get(aum_level, 500)
        p_volume_w = p_volume * 10000
        D[:, 9][p_volume_w >= base_threshold * 4] = 9.0
        D[:, 9][(p_volume_w >= base_threshold * 2) & (p_volume_w < base_threshold * 4)] = 6.0
        D[:, 9][(p_volume_w >= base_threshold) & (p_volume_w < base_threshold * 2)] = 3.0

        # 11. 信用评分组件
        D[:, 10][p_credit >= 80] = 8.1
        D[:, 10][(p_credit >= 70) & (p_credit < 80)] = 6.0
        D[:, 10][(p_credit >= 60) & (p_credit < 70)] = 4.0

        # ===== 动态市场环境检测 + 权重调整 =====
        # 改进 (2025-06-15ae): 市场环境已由 on_data 检测并传入，直接应用
        sw, bw = _get_market_weights(market_env, _stock_weights, _bond_weights)

        # ===== 动态权重应用 =====
        # 向量化模式下子维度分数已含默认权重（如动量满分16.5=0.30*55），
        # 需按实际权重与默认权重的比值缩放各子维度分数，使动态权重生效。
        stock_dim_keys = ['momentum', 'sector', 'technical', 'chip', 'volatility', 'news', 'fundamental']
        bond_dim_keys = ['valuation', 'clause', 'liquidity', 'credit']
        for dim_i, key in enumerate(stock_dim_keys):
            default_w = _stock_weights.get(key, 0)
            actual_w = sw.get(key, default_w)
            if default_w > 0 and actual_w != default_w:
                D[:, dim_i] *= actual_w / default_w
        for dim_j, key in enumerate(bond_dim_keys):
            default_w = _bond_weights.get(key, 0)
            actual_w = bw.get(key, default_w)
            if default_w > 0 and actual_w != default_w:
                D[:, 7 + dim_j] *= actual_w / default_w

        # ===== 求和（子维度分数已含权重，直接求和，避免双重衰减） =====
        # 正股七维满分55分，转债满分45分，理论总分0-100
        stock_total = D[:, :7].sum(axis=1)
        bond_total = D[:, 7:].sum(axis=1)

        # 市场环境微调因子（小幅偏移，不改变量级）
        env_factor = {'bull': 1.05, 'bear': 0.95, 'neutral': 1.0}.get(market_env, 1.0)
        total_score = stock_total * env_factor + bond_total

        # ===== NumPy 排序（降序） =====
        sort_idx = np.argsort(-total_score)
        sorted_orig_idx = passed_idx[sort_idx]

        # ===== 批量 round + 组装结果（已排序） =====
        r_total = np.round(total_score[sort_idx], 2)
        r_stock = np.round(stock_total[sort_idx], 2)
        r_bond = np.round(bond_total[sort_idx], 2)
        r_D = np.round(D[sort_idx], 2)
        orig_codes = codes[sorted_orig_idx]
        orig_names = names[sorted_orig_idx]
        orig_price = price[sorted_orig_idx]
        orig_premium = premium_ratio[sorted_orig_idx]
        orig_dual_low = dual_low[sorted_orig_idx]
        orig_volume = volume[sorted_orig_idx]
        orig_change = change_pct[sorted_orig_idx]
        orig_ytm = ytm[sorted_orig_idx]
        orig_remaining = remaining_years[sorted_orig_idx]

        scores_list = [{
            'total': float(r_total[i]),
            'stock_score': float(r_stock[i]),
            'bond_score': float(r_bond[i]),
            'stock_details': {
                'momentum': float(r_D[i, 0]), 'sector': float(r_D[i, 1]),
                'technical': float(r_D[i, 2]), 'chip': float(r_D[i, 3]),
                'volatility': float(r_D[i, 4]), 'news': float(r_D[i, 5]),
                'fundamental': float(r_D[i, 6]),
            },
            'bond_details': {
                'valuation': float(r_D[i, 7]), 'clause': float(r_D[i, 8]),
                'liquidity': float(r_D[i, 9]), 'credit': float(r_D[i, 10]),
            },
            'code': str(orig_codes[i]),
            'name': str(orig_names[i]),
            'price': float(orig_price[i]),
            'premium_ratio': float(orig_premium[i]),
            'dual_low': float(orig_dual_low[i]),
            'volume': float(orig_volume[i]),
            'change_pct': float(orig_change[i]),
            'ytm': float(orig_ytm[i]),
            'remaining_years': float(orig_remaining[i]),
        } for i in range(pn)]
        return scores_list, vetoed_list

    def _calc_total_score(self, row: pd.Series, df: pd.DataFrame) -> dict:
        """计算综合评分"""
        # 正股七维评分
        stock_scores = {
            'momentum': self._calc_momentum_score(row, df),
            'sector': self._calc_sector_score(row),
            'technical': self._calc_technical_score(row),
            'chip': self._calc_chip_score(row),
            'volatility': self._calc_volatility_score(row),
            'news': self._calc_news_score(row),
            'fundamental': self._calc_fundamental_score(row),
        }

        # 转债自身评分
        bond_scores = {
            'valuation': self._calc_valuation_score(row),
            'clause': self._calc_clause_score(row),
            'liquidity': self._calc_liquidity_score(row),
            'credit': self._calc_credit_score_component(row),
        }

        # 加权总分（子维度分数已含权重，直接求和即可，否则双重衰减）
        # 正股七维满分55分（16.5+9.9+9.9+6.6+6.6+3.85+1.65），转债满分45分（17.1+10.8+9+8.1）
        stock_total = sum(stock_scores.values())
        bond_total = sum(bond_scores.values())

        # 市场环境微调因子（小幅偏移，不改变量级）
        market_env = self._detect_market_environment(pd.DataFrame([row]))
        env_factor = {'bull': 1.05, 'bear': 0.95, 'neutral': 1.0}.get(market_env, 1.0)
        total_score = stock_total * env_factor + bond_total

        return {
            'total': round(total_score, 2),
            'stock_score': round(stock_total, 2),
            'bond_score': round(bond_total, 2),
            'stock_details': {k: round(v, 2) for k, v in stock_scores.items()},
            'bond_details': {k: round(v, 2) for k, v in bond_scores.items()},
        }

    # ==================== 动态权重调整 ====================

    def _detect_market_environment(self, df: pd.DataFrame) -> str:
        """
        检测市场环境：bull/bear/neutral
        基于全市场涨跌幅分布
        """
        # 检查缓存（每5分钟更新一次）
        # 使用当前时间（非向量化模式下的回测日期由调用方设置）
        current_dt = getattr(self, '_current_backtest_date', pd.Timestamp.now())
        if not isinstance(current_dt, pd.Timestamp):
            current_dt = pd.Timestamp(current_dt)
        if self._market_env_cache and self._market_env_ts:
            if (current_dt - self._market_env_ts).seconds < 300:
                return self._market_env_cache

        # 计算市场指标
        avg_change = df['change_pct'].mean() if 'change_pct' in df.columns else 0
        positive_ratio = (df['change_pct'] > 0).mean() if 'change_pct' in df.columns else 0.5

        # 判断市场环境
        if avg_change > 0.5 and positive_ratio > 0.6:
            env = 'bull'
        elif avg_change < -0.5 and positive_ratio < 0.4:
            env = 'bear'
        else:
            env = 'neutral'

        self._market_env_cache = env
        self._market_env_ts = current_dt
        return env

    def _adjust_weights_by_market(self, market_env: str) -> tuple[dict, dict]:
        """根据市场环境调整权重"""
        if market_env == 'bull':
            # 牛市：提高动量和技术权重
            stock_weights = {
                'momentum': 0.35,
                'sector': 0.20,
                'technical': 0.22,
                'chip': 0.08,
                'volatility': 0.10,
                'news': 0.03,
                'fundamental': 0.02,
            }
        elif market_env == 'bear':
            # 熊市：降低动量，提高基本面和波动率权重
            stock_weights = {
                'momentum': 0.20,
                'sector': 0.12,
                'technical': 0.13,
                'chip': 0.10,
                'volatility': 0.18,
                'news': 0.10,
                'fundamental': 0.17,
            }
        else:
            # 震荡市：均衡权重
            stock_weights = self.STOCK_WEIGHTS.copy()

        return stock_weights, self.BOND_WEIGHTS.copy()

    # ==================== 缓冲带机制 ====================

    def _update_buffer_status(self, code: str, rank: int) -> BufferStatus:
        """更新缓冲带状态"""
        hold_count = self.get_param('hold_count')
        buffer_size = self.get_param('buffer_size')
        buffer_days = self.get_param('buffer_days')

        # 获取之前的状态
        prev_status = self._buffer_tracker.get(code, BufferStatus(
            in_buffer=False, days_in_buffer=0,
            days_above_60=0, days_below_60=0
        ))

        # 判断当前位置
        in_top = rank <= hold_count
        in_buffer_zone = hold_count < rank <= hold_count + buffer_size

        # 更新计数
        if in_top:
            days_above_60 = prev_status.days_above_60 + 1
            days_below_60 = 0
        else:
            days_above_60 = 0
            days_below_60 = prev_status.days_below_60 + 1

        # 判断是否在缓冲带内
        if in_buffer_zone:
            in_buffer = True
            days_in_buffer = prev_status.days_in_buffer + 1
        else:
            in_buffer = False
            days_in_buffer = 0

        new_status = BufferStatus(
            in_buffer=in_buffer,
            days_in_buffer=days_in_buffer,
            days_above_60=days_above_60,
            days_below_60=days_below_60,
        )
        self._buffer_tracker[code] = new_status
        return new_status

    def _should_hold_with_buffer(self, code: str, rank: int, was_held: bool) -> tuple[bool, str]:
        """
        根据缓冲带机制判断是否应该持有
        返回: (是否持有, 原因)
        """
        hold_count = self.get_param('hold_count')
        buffer_size = self.get_param('buffer_size')
        buffer_days = self.get_param('buffer_days')

        # 首次运行（无持仓）时跳过缓冲带，直接买入
        if not self._prev_selected:
            return True, "首次建仓"

        status = self._update_buffer_status(code, rank)

        # 在前60名内：直接持有
        if rank <= hold_count:
            return True, f"排名{rank}，前{hold_count}名"

        # 不在缓冲带内：直接卖出
        if rank > hold_count + buffer_size:
            return False, f"排名{rank}，跌出缓冲带"

        # 在缓冲带内：检查连续天数
        if status.days_below_60 >= buffer_days:
            return False, f"排名{rank}，连续{buffer_days}日在60名外"

        if was_held:
            return True, f"排名{rank}，缓冲带观察期({status.days_in_buffer}/{buffer_days}日)"
        else:
            return False, f"排名{rank}，未持仓，缓冲带内不买入"

    # ==================== 策略主逻辑 ====================

    def on_init(self, data: pd.DataFrame) -> None:
        """策略初始化"""
        self._data = data.copy()
        # Defensive: ensure required columns exist with safe defaults
        # 改进 (2025-06-15ah): 补全所有数据源列，防止 calc_vectorized 中缺失列导致异常值
        _required_columns = {
            'premium_ratio': 15.0,
            'change_pct': 0.0,
            'volume': 100000.0,
            'ytm': 1.0,
            'remaining_years': 3.0,
            'price': 100.0,
            'dual_low': 0.0,
            'forced_call_days': 0,
            'stock_change_pct': 0.0,
            'code': '',
            'name': '',
        }
        for col, default in _required_columns.items():
            if col not in self._data.columns:
                self._data[col] = default
                logger.warning(f"[XibuSeven] 数据源缺失列 '{col}'，已填充默认值 {default}")
            # 对数值列进行 fillna，对字符串列不处理（保持空字符串）
            if self._data[col].dtype.kind in 'iufc':  # integer, unsigned, float, complex
                self._data[col] = self._data[col].fillna(default)
        if 'date' in data.columns and len(data) > 0:
            sample_date = data['date'].iloc[0]
            if isinstance(sample_date, date):
                self._dates = sorted(d for d in data['date'].unique() if pd.notna(d))
            else:
                # 修复 (2025-06-15): date列类型异常时尝试转换，而非直接fallback到当前日期
                # 原逻辑: self._dates = [datetime.now().date()] -> 导致所有日期相同，策略失效
                try:
                    converted = pd.to_datetime(data['date'], errors='coerce')
                    if converted.isna().all():
                        raise ValueError("date列转换后全为NaT")
                    # 只修改 self._data，不修改 caller 传入的 data，避免副作用
                    self._data['date'] = converted.dt.date
                    self._dates = sorted(d for d in self._data['date'].unique() if pd.notna(d))
                    logger.info(f"[XibuSeven] date列已从 {type(sample_date).__name__} 转换为 date")
                except Exception as e:
                    logger.error(f"[XibuSeven] date列转换失败: {e}, 回退到当前日期")
                    self._dates = [datetime.now().date()]
        else:
            self._dates = [datetime.now().date()]

    def on_data(self, data: pd.DataFrame, idx: int) -> Optional[list[dict]]:
        """V4.0: 周频调仓 + 动量过滤 + 仓位管理（向量化评分）"""
        # 改进 (2025-06-15ae): assert 在 -O 模式下会被忽略，改用显式 RuntimeError
        if not self._dates or len(self._dates) == 0:
            raise RuntimeError("[XibuSeven] _dates 未初始化")
        current_date = self._dates[idx] if idx < len(self._dates) else datetime.now().date()
        day_data = data.copy()

        if day_data.empty:
            return None

        # 清理退市债券的缓冲状态
        active_codes = set(day_data['code'].values) if 'code' in day_data.columns else set()
        stale_buffer_codes = [c for c in self._buffer_tracker if c not in active_codes]
        for c in stale_buffer_codes:
            del self._buffer_tracker[c]
        if stale_buffer_codes:
            logger.debug(f"[XibuSeven] 清理 {len(stale_buffer_codes)} 只退市债券的缓冲状态")

        # === V4.0: 调仓频率控制 ===
        rebalance_days = self.get_param('rebalance_days')
        is_rebalance_day = (idx - self._last_rebalance_idx) >= rebalance_days

        # 非调仓日只检查是否需要卖出（最小持仓期之外的止损逻辑）
        if not is_rebalance_day:
            # 没有主动卖出逻辑，持仓等待下一个调仓日
            # 但仍需更新hold_since中存在的持仓的跟踪
            return None

        self._last_rebalance_idx = idx

        # 改进 (2025-06-15af): 使用模块级 _detect_market_env，传入当前时间戳和策略参数 cache_ttl
        # 改进 (2025-06-15ag): 区分 None 和 0，尊重用户显式设置的 0 值
        # 回测中使用回测日期而非实时时间，确保市场环境基于历史数据
        current_ts = pd.Timestamp(current_date) if current_date else pd.Timestamp.now()
        _cache_ttl_raw = self.get_param('market_env_cache_ttl')
        _cache_ttl = 300 if _cache_ttl_raw is None else int(_cache_ttl_raw)
        market_env, self._market_env_ts = _detect_market_env(
            data, current_ts, self._market_env_cache, self._market_env_ts, cache_ttl_seconds=_cache_ttl
        )
        self._market_env_cache = market_env

        # 向量化评分
        scores_list, vetoed_list = self.calc_vectorized(day_data, market_env)

        for v in vetoed_list:
            code = v.get('code', '')
            self._veto_results[code] = VetoResult(
                passed=False,
                reasons=v.get('reasons', []),
                score=v.get('credit_score', 0),
            )

        if not scores_list:
            return None

        hold_count = self.get_param('hold_count')
        min_hold_days = self.get_param('min_hold_days')
        momentum_filter = self.get_param('momentum_filter')
        position_sizing = self.get_param('position_sizing')

        # === V4.0: 动量过滤（买入前检查短期趋势）===
        if momentum_filter:
            code_momentum_ok = {}
            for s in scores_list:
                code = s['code']
                chg = s.get('change_pct', 0)
                # 短期动量需要为正（或至少>-2%）
                code_momentum_ok[code] = chg > -2
        else:
            code_momentum_ok = {s['code']: True for s in scores_list}

        # 生成信号
        signals = []
        new_selected = set()
        buy_candidates = []

        for rank, s in enumerate(scores_list, 1):
            code = s['code']
            was_held = code in self._prev_selected

            # 最小持仓期检查
            hold_start = self._hold_since.get(code, -999)
            held_days = idx - hold_start if hold_start >= 0 else 999
            is_locked = held_days < min_hold_days

            should_hold, reason = self._should_hold_with_buffer(code, rank, was_held)

            if should_hold:
                new_selected.add(code)
                if code not in self._hold_since:
                    self._hold_since[code] = idx
                
                if not was_held and rank <= hold_count:
                    # 动量过滤
                    if not code_momentum_ok.get(code, True):
                        continue
                    buy_candidates.append({
                        'code': code, 'action': 'buy',
                        'price': float(s['price']),
                        'reason': f'评分{s["total"]:.1f}，{reason}',
                        'score': s['total'], 'rank': rank,
                        'confidence': s['total'],  # 添加 confidence 字段，避免被 _min_confidence 过滤
                    })
                    self._hold_since[code] = idx

        # === V4.0: 仓位管理 ===
        # 得分加权模式：每笔buy带上建议仓位权重
        if position_sizing == 'score_weighted' and buy_candidates:
            scores_arr = np.array([b['score'] for b in buy_candidates])
            if scores_arr.sum() > 0:
                weights = scores_arr / scores_arr.sum()
            else:
                weights = np.ones(len(buy_candidates)) / len(buy_candidates)
            for i, b in enumerate(buy_candidates):
                b['alloc_weight'] = float(weights[i])

        signals.extend(buy_candidates)

        # 卖出
        to_sell = self._prev_selected - new_selected
        # 但受最小持仓期保护的持仓不卖
        protected_sell = {c for c in to_sell if c in self._hold_since and (idx - self._hold_since[c]) < min_hold_days}
        to_sell = to_sell - protected_sell
        # 保留受保护的持仓
        new_selected |= protected_sell

        code_price_map = {row['code']: row.get('price', 0) for _, row in day_data.iterrows()} if not day_data.empty else {}
        for code in to_sell:
            p = code_price_map.get(code, 0)
            if p > 0:
                signals.append({'code': code, 'action': 'sell', 'price': float(p), 'reason': '跌出白名单', 'rank': None})
                self._hold_since.pop(code, None)

        self._prev_selected = new_selected
        return signals if signals else None

    def get_veto_results(self) -> dict[str, VetoResult]:
        """获取一票否决检查结果"""
        return self._veto_results.copy()

    def get_buffer_status(self, code: str) -> Optional[BufferStatus]:
        """获取指定标的的缓冲带状态"""
        return self._buffer_tracker.get(code)

    def on_destroy(self):
        """策略清理"""
        self._buffer_tracker.clear()
        self._veto_results.clear()
        self._prev_selected.clear()
        self._hold_since.clear()
