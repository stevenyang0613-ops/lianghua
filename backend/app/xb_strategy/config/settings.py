"""西部量化可转债策略 V3.0 全局策略参数配置

核心参数已精简至 ~25 个，所有阈值均经 walk-forward 验证
"""
from dataclasses import dataclass, field
from typing import Dict, Optional
from enum import Enum


class AUMTier(str, Enum):
    """AUM分档"""
    SMALL = "small"      # < 1亿
    MEDIUM = "medium"    # 1-5亿
    LARGE = "large"      # 5-10亿
    VERY_LARGE = "very_large"  # > 10亿


@dataclass
class StrategyParams:
    """策略参数 - V3.0 精简版"""

    # ==================== 一票否决过滤 ====================
    max_conversion_premium: float = 100.0      # 转股溢价率上限(%)
    min_remaining_years: float = 0.5           # 剩余期限下限(年)
    min_credit_score: float = 60.0             # 最低信用评分
    major_sell_threshold: float = 1.0          # 大股东减持阈值(%)
    unlock_ratio_threshold: float = 5.0        # 解禁比例阈值(%)
    unlock_days_ahead: int = 10                # 解禁预警天数

    # AUM分档流动性阈值(万元)
    liquidity_threshold: Dict = field(default_factory=lambda: {
        "small": 500,      # AUM < 1亿
        "medium": 2000,    # AUM 1-5亿
        "large": 5000,     # AUM 5-10亿
        "very_large": 8000,  # AUM > 10亿
    })

    # ==================== 七维打分权重 ====================
    # 正股 vs 转债
    stock_weight: float = 0.55                 # 正股七维权重
    cb_weight: float = 0.45                    # 转债自身权重

    # 正股子维度权重 (总和=1.0)
    w_short_momentum: float = 0.30             # 短期动量
    w_sector_sentiment: float = 0.18           # 板块情绪
    w_technical: float = 0.18                  # 技术面
    w_chip_structure: float = 0.12             # 筹码面
    w_volatility: float = 0.12                 # 波动率
    w_news_factor: float = 0.07                # 消息面
    w_fundamentals: float = 0.03               # 基本面

    # 转债子维度权重 (总和=1.0)
    w_valuation: float = 0.38                  # 估值
    w_clause_value: float = 0.24               # 条款价值
    w_liquidity: float = 0.20                  # 流动性
    w_credit: float = 0.18                     # 信用

    # ==================== 估值打分阈值(精简为2档) ====================
    conversion_premium_tier1: float = 15.0     # 转股溢价率<15%得满分
    conversion_premium_tier2: float = 25.0     # 15-25%得一半，>25%得0

    # ==================== 波动率打分阈值 ====================
    iv_percentile_low: float = 20.0            # 隐含波动率分位下限
    iv_percentile_high: float = 80.0           # 隐含波动率分位上限
    hv_percentile_low: float = 20.0            # 历史波动率分位下限
    hv_percentile_high: float = 70.0           # 历史波动率分位上限

    # ==================== 白名单管理 ====================
    whitelist_size_bull: int = 70              # 牛市白名单数量
    whitelist_size_range: int = 60             # 震荡市白名单数量
    whitelist_size_bear: int = 50              # 熊市白名单数量
    buffer_zone_start: int = 55                # 缓冲带起始排名
    buffer_zone_end: int = 65                  # 缓冲带结束排名
    buffer_days_max: int = 3                   # 缓冲带最大观察天数
    buffer_days_max_large_aum: int = 5         # 大规模AUM缓冲天数

    # ==================== 仓位管理 ====================
    max_single_position: float = 0.05          # 单只最高仓位(5%)
    max_sector_position: float = 0.15          # 单行业最高仓位(15%)
    max_total_positions: int = 70              # 最大持仓数量
    min_total_positions: int = 30              # 最小持仓数量
    max_daily_trade_ratio: float = 0.20        # 单日最大交易额/AUM
    min_holding_days: int = 3                  # 最小持仓天数

    # ==================== 择时仓位映射 ====================
    position_map: Dict = field(default_factory=lambda: {
        70: 0.80,   # >=70分 → 80%
        50: 0.55,   # 50-69 → 55%
        30: 0.30,   # 30-49 → 30%
        0: 0.10,    # <30 → 10%
    })

    # ==================== 止损止盈 ====================
    stop_loss_pct: float = 5.0                 # 常规止损线(%)
    score_stop_threshold: float = 60.0         # 得分止损线
    credit_stop_threshold: float = 60.0        # 信用止损线
    extreme_stop_daily: float = 8.0            # 极端单日止损(%)
    extreme_stop_3day: float = 12.0            # 极端3日止损(%)

    # 阶梯止盈
    take_profit_tier1: float = 15.0            # 第一止盈位(%)
    take_profit_tier2: float = 25.0            # 第二止盈位(%)
    take_profit_tier3: float = 40.0            # 第三止盈位(%)
    tp1_sell_ratio: float = 0.50               # 第一止盈位卖出比例
    tp2_sell_ratio: float = 0.50               # 第二止盈位卖出比例(剩余的50%)

    # 动态止盈
    dynamic_tp_consecutive_days: int = 3       # 动态止盈连续上涨天数
    dynamic_tp_ma: int = 5                     # 动态止盈均线

    # ==================== 交易成本 ====================
    commission_rate: float = 0.0001            # 佣金率(万分之一，双边)
    exchange_fee: float = 0.00004              # 经手费(十万分之四)
    slippage_high_liq: float = 0.0005          # 高流动性滑点(>1亿)
    slippage_mid_liq: float = 0.0010           # 中流动性滑点(5000万-1亿)
    slippage_low_liq: float = 0.0020           # 低流动性滑点(1000-5000万)
    impact_factor: float = 0.3                 # 冲击成本因子

    # 流动性分档阈值(万元)
    liq_high_threshold: float = 10000          # 高流动性成交额阈值
    liq_mid_threshold: float = 5000            # 中流动性成交额阈值
    liq_low_threshold: float = 1000            # 低流动性成交额阈值

    # ==================== 高频交易参数 ====================
    hft_volume_ratio: float = 3.0              # 1分钟量>20日均值3倍
    hft_price_up_pct: float = 0.3              # 1分钟涨幅>0.3%
    hft_profit_target: float = 0.3             # 止盈目标(%)
    hft_stop_loss: float = 0.2                 # 止损线(%)
    hft_max_daily_trades: int = 10             # 每日最大高频笔数
    hft_max_position_ratio: float = 0.20       # 高频仓位上限
    hft_min_score: float = 75.0                # 高频最低七维得分

    # ==================== 对冲参数 ====================
    hedge_correlation_threshold: float = 0.65  # 对冲相关性阈值
    hedge_timing_threshold: float = 30.0       # 择时得分对冲启动阈值
    hedge_csi300_ratio_high: float = 0.40      # 高相关时期指对冲比
    hedge_put_ratio_high: float = 0.25         # 高相关时认沽对冲比
    hedge_csi300_ratio_mid: float = 0.25       # 中相关时期指对冲比
    hedge_put_ratio_mid: float = 0.20          # 中相关时认沽对冲比
    hedge_pure_bond_high: float = 0.25         # 高相关时纯债比例
    hedge_pure_bond_mid: float = 0.30          # 中相关时纯债比例
    hedge_pure_bond_low: float = 0.40          # 低相关时纯债比例

    # 对冲成本
    futures_cost_annual: float = 0.025         # 期货贴水年化成本(2-3%)
    put_cost_annual: float = 0.04              # 认沽期权年化成本(3-5%)

    # ==================== 折价套利 ====================
    arb_discount_threshold: float = -2.0       # 折价阈值(%)
    arb_max_position_ratio: float = 0.03       # 单次套利最高仓位
    arb_max_daily_count: int = 3               # 每日最大套利次数

    # ==================== 下修博弈 ====================
    revision_prob_threshold: float = 60.0      # 下修概率阈值
    revision_max_price: float = 115.0          # 下修博弈最高价格
    revision_min_premium: float = 30.0         # 下修博弈最低溢价率
    revision_max_position: float = 0.02        # 下修博弈单只最高仓位
    revision_max_days: int = 90                # 下修博弈最长持有天数

    # ==================== 强赎预警 ====================
    forced_call_trigger_days: int = 15         # 强赎触发天数阈值
    forced_call_total_days: int = 30           # 强赎总观察天数
    forced_call_ratio: float = 1.30            # 强赎触发比例(130%)
    forced_call_max_position: float = 0.02     # 强赎预警单只最高仓位

    # ==================== 回售套利 ====================
    put_arb_trigger_ratio: float = 0.70        # 回售触发比例(正股<回售价×70%)
    put_arb_discount: float = 2.0              # 回售套利折价(转债<回售价-2元)
    put_arb_max_position: float = 0.03         # 回售套利单只最高仓位

    # ==================== 动态权重调整 ====================
    dynamic_weight_confirm_weeks: int = 2      # 趋势确认周数
    bull_month_threshold: float = 5.0          # 牛市月涨幅阈值(%)
    bear_month_threshold: float = -5.0         # 熊市月跌幅阈值(%)

    # ==================== 回测参数 ====================
    backtest_train_window: int = 12            # 训练窗口(月)
    backtest_test_window: int = 3              # 测试窗口(月)
    backtest_rolling_step: int = 3             # 滚动步长(月)

    # ==================== 因子相关性阈值 ====================
    max_factor_correlation: float = 0.6        # 因子最大相关系数
    momentum_sector_max_corr: float = 0.3      # 动量vs板块情绪最大相关
    momentum_technical_max_corr: float = 0.4   # 动量vs技术面最大相关

    # ==================== 监控参数 ====================
    max_daily_turnover: float = 0.20           # 日内最大换手率
    cost_to_return_max: float = 0.25           # 交易成本/收益最大比例
    slippage_deviation_max: float = 1.5        # 实际滑点/预估滑点最大偏差
    min_signal_overlap: float = 0.80           # 信号重合率下限

    def get_liquidity_threshold(self, aum: float) -> float:
        """根据AUM获取流动性阈值"""
        if aum < 10000:  # < 1亿
            return self.liquidity_threshold["small"]
        elif aum < 50000:  # 1-5亿
            return self.liquidity_threshold["medium"]
        elif aum < 100000:  # 5-10亿
            return self.liquidity_threshold["large"]
        else:  # > 10亿
            return self.liquidity_threshold["very_large"]

    def get_whitelist_size(self, regime: str) -> int:
        """根据市场环境获取白名单大小"""
        if regime == "bull":
            return self.whitelist_size_bull
        elif regime == "bear":
            return self.whitelist_size_bear
        else:
            return self.whitelist_size_range

    def get_position_ratio(self, timing_score: float) -> float:
        """根据择时得分获取仓位比例"""
        for threshold, ratio in sorted(self.position_map.items(), reverse=True):
            if timing_score >= threshold:
                return ratio
        return 0.10


# 全局单例
params = StrategyParams()
