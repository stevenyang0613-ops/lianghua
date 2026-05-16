"""
松岗七维量化打分策略 V3.0

核心逻辑：转债价格 = 债底价值 + 转股价值 + 期权价值 + 波动率溢价
正股七维评分占55%，转债自身评分占45%

一票否决制 + 七维打分 + 缓冲带机制 + 动态权重
"""

import pandas as pd
import numpy as np
from typing import Optional
from datetime import datetime, timedelta
from dataclasses import dataclass

from app.strategies.base import Strategy
from app.models.backtest import StrategyParam


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


class SonggangSevenDimensionStrategy(Strategy):
    """松岗七维量化打分策略 - V3.0"""

    name = "松岗七维打分策略"
    description = "融合七维量化打分 + 多因子估值 + 动态择时 + 前60名强制轮换 + 缓冲带机制"

    params = [
        StrategyParam(name="hold_count", label="持有数量", type="int", default=60, min_val=10, max_val=100),
        StrategyParam(name="buffer_size", label="缓冲带大小", type="int", default=5, min_val=0, max_val=10),
        StrategyParam(name="buffer_days", label="缓冲观察天数", type="int", default=3, min_val=1, max_val=7),
        StrategyParam(name="min_credit_score", label="最低信用评分", type="float", default=60, min_val=0, max_val=100),
        StrategyParam(name="max_premium", label="溢价率上限(%)", type="float", default=100, min_val=10, max_val=150),
        StrategyParam(name="min_remaining_months", label="最小剩余期限(月)", type="int", default=6, min_val=1, max_val=36),
        StrategyParam(name="aum_level", label="AUM规模等级", type="str", default="small", description="small/medium/large"),
        StrategyParam(name="market_env", label="市场环境", type="str", default="neutral", description="bull/bear/neutral"),
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
        super().__init__(**kwargs)
        self._buffer_tracker: dict[str, BufferStatus] = {}
        self._veto_results: dict[str, VetoResult] = {}
        self._prev_selected: set[str] = set()
        self._market_env_cache: Optional[str] = None
        self._market_env_ts: Optional[datetime] = None

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
        if row.get('premium_ratio', 0) > self.get_param('max_premium'):
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
        score = 100.0
        price = row.get('price', 100)
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
        price = row.get('price', 100)
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
        price = row.get('price', 100)

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

        # 加权总分
        stock_total = sum(stock_scores[k] * self.STOCK_WEIGHTS[k] for k in stock_scores)
        bond_total = sum(bond_scores[k] * self.BOND_WEIGHTS[k] for k in bond_scores)

        # 正股55% + 转债45%
        total_score = stock_total + bond_total

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
        now = datetime.now()
        if self._market_env_cache and self._market_env_ts:
            if (now - self._market_env_ts).seconds < 300:
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
        self._market_env_ts = now
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
        self._dates = sorted(data['date'].unique()) if 'date' in data.columns else [datetime.now().date()]

    def on_data(self, data: pd.DataFrame, idx: int) -> Optional[list[dict]]:
        """在每个时间点生成交易信号"""
        current_date = self._dates[idx] if idx < len(self._dates) else datetime.now().date()
        # data 已是当日行情子集，无需再按日期过滤
        day_data = data.copy()

        if day_data.empty:
            return None

        # 检测市场环境
        market_env = self._detect_market_environment(day_data)

        # 第一步：一票否决过滤
        valid_indices = []
        for i, row in day_data.iterrows():
            veto = self._check_veto(row)
            self._veto_results[row['code']] = veto
            if veto.passed:
                valid_indices.append(i)

        if not valid_indices:
            return None

        valid_data = day_data.loc[valid_indices].copy()

        # 第二步：计算七维评分
        scores_list = []
        for i, row in valid_data.iterrows():
            score_dict = self._calc_total_score(row, valid_data)
            score_dict['code'] = row['code']
            score_dict['name'] = row.get('name', '')
            score_dict['price'] = row['price']
            scores_list.append(score_dict)

        if not scores_list:
            return None

        scores_df = pd.DataFrame(scores_list)

        # 第三步：按分数排序，生成白名单
        scores_df = scores_df.sort_values('total', ascending=False).reset_index(drop=True)
        hold_count = self.get_param('hold_count')

        # 第四步：生成信号
        signals = []
        new_selected = set()

        for rank, (_, row) in enumerate(scores_df.iterrows(), 1):
            code = row['code']
            was_held = code in self._prev_selected

            # 缓冲带判断
            should_hold, reason = self._should_hold_with_buffer(code, rank, was_held)

            if should_hold:
                new_selected.add(code)

                # 如果是新买入
                if not was_held and rank <= hold_count:
                    signals.append({
                        'code': code,
                        'action': 'buy',
                        'price': float(row['price']),
                        'reason': f'评分{row["total"]:.1f}，{reason}',
                        'score': row['total'],
                        'rank': rank,
                    })

        # 卖出不再持有的标的
        to_sell = self._prev_selected - new_selected
        for code in to_sell:
            if code in day_data['code'].values:
                sell_row = day_data[day_data['code'] == code].iloc[0]
                signals.append({
                    'code': code,
                    'action': 'sell',
                    'price': float(sell_row['price']),
                    'reason': '跌出白名单',
                    'rank': None,
                })

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
