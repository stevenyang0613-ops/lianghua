"""松岗量化可转债策略 V3.0 核心数据类型定义

包含数据验证装饰器和验证函数
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional, List, Dict, Any, Callable
from enum import Enum
import functools
import warnings


# ============ 数据验证工具 ============

class ValidationError(Exception):
    """数据验证错误"""
    pass


def validate_range(value: float, min_val: float, max_val: float, name: str) -> float:
    """验证数值范围"""
    if not (min_val <= value <= max_val):
        if min_val == float('-inf'):
            warnings.warn(f"{name}={value} 超出正常范围(应<{max_val})")
        elif max_val == float('inf'):
            warnings.warn(f"{name}={value} 超出正常范围(应>{min_val})")
        else:
            warnings.warn(f"{name}={value} 超出正常范围({min_val}~{max_val})")
    return value


def validate_positive(value: float, name: str) -> float:
    """验证正数"""
    if value < 0:
        warnings.warn(f"{name}={value} 应为非负数")
    return value


def validate_date(value: date, name: str) -> date:
    """验证日期合理性"""
    if value > date.today():
        warnings.warn(f"{name}={value} 是未来日期")
    return value


def validate_code(value: str, name: str) -> str:
    """验证代码格式"""
    if not value or len(value) < 6:
        warnings.warn(f"{name}='{value}' 格式可能不正确")
    return value


def validated_dataclass(cls):
    """数据验证装饰器 - 为dataclass添加自动验证"""
    original_post_init = cls.__post_init__ if hasattr(cls, '__post_init__') else None

    def __post_init__(self):
        # 执行字段验证
        for field_name, field_type in cls.__annotations__.items():
            value = getattr(self, field_name, None)
            if value is not None:
                # 根据字段名进行特定验证
                if 'price' in field_name.lower() or 'close' in field_name.lower():
                    validate_positive(value, field_name)
                elif 'rate' in field_name.lower() or 'ratio' in field_name.lower():
                    validate_range(value, -100, 1000, field_name)
                elif 'premium' in field_name.lower():
                    validate_range(value, -100, 500, field_name)
                elif 'date' in field_name.lower():
                    if isinstance(value, date):
                        validate_date(value, field_name)
                elif 'code' in field_name.lower():
                    if isinstance(value, str):
                        validate_code(value, field_name)

        # 调用原始的__post_init__
        if original_post_init:
            original_post_init(self)

    cls.__post_init__ = __post_init__
    return cls


# ============ 枚举类型 ============

class MarketRegime(str, Enum):
    """市场环境"""
    BULL = "bull"        # 牛市：指数月涨 > 5%
    RANGE = "range"      # 震荡市：月波动 ±3%
    BEAR = "bear"        # 熊市：指数月跌 > 5%


class TradeAction(str, Enum):
    """交易动作"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class SignalType(str, Enum):
    """信号类型"""
    STOP_LOSS = "stop_loss"           # 刚性止损
    TAKE_PROFIT = "take_profit"       # 阶梯止盈
    WHITELIST_EXIT = "whitelist_exit" # 白名单退出
    CREDIT_EXIT = "credit_exit"       # 信用退出
    FORCE_EXIT = "force_exit"         # 强制卖出
    SCORE_EXIT = "score_exit"         # 得分止损
    EXTREME_EXIT = "extreme_exit"     # 极端止损
    NEW_BUY = "new_buy"               # 新买入
    ADD_POSITION = "add_position"     # 加仓


@validated_dataclass
@dataclass
class StockData:
    """正股日频数据"""
    code: str
    date: date
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    amount: float = 0.0              # 成交额(万元)
    turnover_rate: float = 0.0       # 换手率(%)
    change_pct: float = 0.0          # 涨跌幅(%)
    limit_up: bool = False           # 是否涨停
    limit_down: bool = False         # 是否跌停
    main_net_inflow: float = 0.0     # 主力净流入(万元)
    volume_ratio: float = 1.0        # 量比
    market_cap: float = 0.0          # 总市值(亿)
    pe: float = 0.0                  # 市盈率
    pb: float = 0.0                  # 市净率
    sector_code: str = ""            # 所属行业代码
    sector_name: str = ""            # 所属行业名称
    sector_change_pct: float = 0.0   # 板块涨跌幅(%)
    sector_limit_up_count: int = 0   # 板块涨停家数
    sector_total_count: int = 0      # 板块成分股数
    # 正股基本面
    revenue_yoy: float = 0.0         # 营收同比增速(%)
    net_profit_yoy: float = 0.0      # 净利润同比增速(%)
    debt_ratio: float = 0.0          # 资产负债率(%)
    operating_cf: float = 0.0        # 经营活动现金流(亿)
    total_interest_debt: float = 0.0 # 有息负债(亿)
    current_ratio: float = 0.0       # 流动比率
    guarantee_ratio: float = 0.0     # 对外担保比例(%)
    pledge_ratio: float = 0.0        # 大股东质押率(%)
    # 筹码面
    profit_ratio: float = 0.0        # 获利盘比例(%)
    concentration: float = 0.0       # 筹码集中度
    shareholder_change_pct: float = 0.0  # 股东户数变化率(%)
    # 波动率
    hist_vol_20d: float = 0.0        # 20日历史波动率
    hist_vol_percentile: float = 0.0 # 历史波动率分位数
    # 均线
    ma5: float = 0.0
    ma10: float = 0.0
    ma20: float = 0.0
    ma60: float = 0.0
    # MACD
    macd: float = 0.0
    macd_signal: float = 0.0
    macd_hist: float = 0.0
    # 突破
    breakthrough_level: int = 0      # 突破级别(0-3)
    # ST状态
    is_st: bool = False
    is_delisting_warning: bool = False  # 退市风险警示


@validated_dataclass
@dataclass
class ConvertibleBondData:
    """可转债日频数据"""
    code: str                        # 转债代码
    name: str                        # 转债名称
    stock_code: str                  # 正股代码
    stock_name: str                  # 正股名称
    date: date
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0               # 转债收盘价
    volume: float = 0.0
    amount: float = 0.0              # 成交额(万元)
    turnover_rate: float = 0.0       # 换手率(%)
    change_pct: float = 0.0          # 涨跌幅(%)
    # 核心指标
    conversion_price: float = 0.0    # 转股价
    stock_price: float = 0.0         # 正股价格
    conversion_value: float = 0.0    # 转股价值
    conversion_premium: float = 0.0  # 转股溢价率(%)
    pure_bond_value: float = 0.0     # 纯债价值
    pure_bond_premium: float = 0.0   # 纯债溢价率(%)
    ytm: float = 0.0                 # 到期收益率(%)
    # 条款信息
    remaining_years: float = 0.0     # 剩余期限(年)
    coupon_rate: float = 0.0         # 票面利率(%)
    redemption_price: float = 0.0    # 赎回价
    redemption_trigger: bool = False # 是否触发强赎条件
    forced_call_days: int = 0        # 强赎倒计时天数
    put_price: float = 0.0           # 回售价
    put_date: Optional[date] = None  # 回售起始日
    # 信用相关
    issuer_rating: str = ""          # 主体评级(AAA/AA+/AA/AA-/A+...)
    bond_rating: str = ""            # 债项评级
    # 流动性
    daily_amount_20d: float = 0.0    # 20日均成交额(万元)
    # 机构持仓
    inst_holding_ratio: float = 0.0  # 机构持仓占比(%)
    major_holder_ratio: float = 0.0  # 大股东转债持仓比例(%)
    # 隐含波动率
    implied_vol: float = 0.0         # 隐含波动率
    implied_vol_percentile: float = 0.0  # 隐含波动率历史分位数
    vol_skew: float = 0.0            # 波动率偏度
    # 价格/纯债比
    price_to_bond_ratio: float = 0.0 # 转债价格/纯债价值
    # 公司事件
    has_major_sell: bool = False     # 近7日有大股东减持>1%
    unlock_date: Optional[date] = None   # 解禁日
    unlock_ratio: float = 0.0        # 解禁比例(%)
    has_limit_up_1y: bool = True     # 近1年有涨停记录
    is_called: bool = False          # 已发布强赎公告
    call_date: Optional[date] = None # 强赎公告日


@dataclass
class SevenDimScore:
    """七维打分结果"""
    cb_code: str
    date: date
    # 正股七维 (55分)
    short_momentum: float = 0.0      # 短期动量(16.5)
    sector_sentiment: float = 0.0    # 板块情绪(9.9)
    technical: float = 0.0           # 技术面(9.9)
    chip_structure: float = 0.0      # 筹码面(6.6)
    volatility: float = 0.0          # 波动率(6.6)
    news_factor: float = 0.0         # 消息面(3.85)
    fundamentals: float = 0.0        # 基本面(1.65)
    stock_total: float = 0.0         # 正股小计
    # 转债自身 (45分)
    valuation: float = 0.0           # 估值指标(17.1)
    clause_value: float = 0.0        # 条款价值(10.8)
    liquidity: float = 0.0           # 流动性(9.0)
    credit: float = 0.0              # 信用评分(8.1)
    cb_total: float = 0.0            # 转债小计
    # 综合
    total_score: float = 0.0         # 总分(100)
    # 排名
    rank: int = 0
    in_whitelist: bool = False
    in_buffer_zone: bool = False
    buffer_days: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cb_code": self.cb_code,
            "date": self.date.isoformat() if isinstance(self.date, date) else self.date,
            "short_momentum": round(self.short_momentum, 2),
            "sector_sentiment": round(self.sector_sentiment, 2),
            "technical": round(self.technical, 2),
            "chip_structure": round(self.chip_structure, 2),
            "volatility": round(self.volatility, 2),
            "news_factor": round(self.news_factor, 2),
            "fundamentals": round(self.fundamentals, 2),
            "stock_total": round(self.stock_total, 2),
            "valuation": round(self.valuation, 2),
            "clause_value": round(self.clause_value, 2),
            "liquidity": round(self.liquidity, 2),
            "credit": round(self.credit, 2),
            "cb_total": round(self.cb_total, 2),
            "total_score": round(self.total_score, 2),
            "rank": self.rank,
            "in_whitelist": self.in_whitelist,
            "in_buffer_zone": self.in_buffer_zone,
            "buffer_days": self.buffer_days,
        }


@dataclass
class TimingSignal:
    """择时信号"""
    date: date
    valuation_score: float = 0.0     # 估值(40%)
    sentiment_score: float = 0.0     # 情绪(25%)
    liquidity_score: float = 0.0     # 流动性(20%)
    macro_score: float = 0.0         # 宏观(15%)
    total_score: float = 0.0         # 综合择时得分
    position_ratio: float = 0.0      # 建议仓位比例(0-0.8)
    regime: MarketRegime = MarketRegime.RANGE
    hedge_required: bool = False     # 是否需要启动对冲

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date.isoformat() if isinstance(self.date, date) else self.date,
            "valuation_score": round(self.valuation_score, 2),
            "sentiment_score": round(self.sentiment_score, 2),
            "liquidity_score": round(self.liquidity_score, 2),
            "macro_score": round(self.macro_score, 2),
            "total_score": round(self.total_score, 2),
            "position_ratio": round(self.position_ratio, 2),
            "regime": self.regime.value,
            "hedge_required": self.hedge_required,
        }


@dataclass
class CreditScore:
    """信用评分"""
    cb_code: str
    date: date
    implied_default_prob: float = 0.0  # 价格隐含违约概率得分(25)
    issuer_rating: float = 0.0         # 主体评级(10)
    debt_ratio: float = 0.0            # 资产负债率(15)
    current_ratio: float = 0.0         # 流动比率(15)
    cf_to_debt: float = 0.0            # 现金流/有息负债(15)
    guarantee_ratio: float = 0.0       # 对外担保(8)
    pledge_ratio: float = 0.0          # 大股东质押(7)
    industry_outlook: float = 0.0      # 行业景气度(5)
    total_score: float = 0.0           # 总分(100)
    is_pass: bool = True               # 是否通过(>=60)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cb_code": self.cb_code,
            "date": self.date.isoformat() if isinstance(self.date, date) else self.date,
            "implied_default_prob": round(self.implied_default_prob, 2),
            "issuer_rating": round(self.issuer_rating, 2),
            "debt_ratio": round(self.debt_ratio, 2),
            "current_ratio": round(self.current_ratio, 2),
            "cf_to_debt": round(self.cf_to_debt, 2),
            "guarantee_ratio": round(self.guarantee_ratio, 2),
            "pledge_ratio": round(self.pledge_ratio, 2),
            "industry_outlook": round(self.industry_outlook, 2),
            "total_score": round(self.total_score, 2),
            "is_pass": self.is_pass,
        }


@dataclass
class DownwardRevisionScore:
    """下修概率评分"""
    cb_code: str
    date: date
    financial_pressure: float = 0.0   # 财务压力(30)
    put_time_pressure: float = 0.0    # 回售时间压力(25)
    major_holder_interest: float = 0.0  # 大股东利益(25)
    revision_history: float = 0.0     # 下修历史(20)
    total_score: float = 0.0          # 总分(100)
    probability_level: str = "low"    # high/medium/low

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cb_code": self.cb_code,
            "date": self.date.isoformat() if isinstance(self.date, date) else self.date,
            "financial_pressure": round(self.financial_pressure, 2),
            "put_time_pressure": round(self.put_time_pressure, 2),
            "major_holder_interest": round(self.major_holder_interest, 2),
            "revision_history": round(self.revision_history, 2),
            "total_score": round(self.total_score, 2),
            "probability_level": self.probability_level,
        }


@validated_dataclass
@dataclass
class TradeSignal:
    """交易信号"""
    signal_id: str
    cb_code: str
    cb_name: str
    action: TradeAction
    signal_type: SignalType
    price: float
    quantity: int = 0
    reason: str = ""
    confidence: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    executed: bool = False
    urgency: int = 0  # 0=正常 1=紧急(30分钟) 2=立即

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "cb_code": self.cb_code,
            "cb_name": self.cb_name,
            "action": self.action.value,
            "signal_type": self.signal_type.value,
            "price": round(self.price, 3),
            "quantity": self.quantity,
            "reason": self.reason,
            "confidence": round(self.confidence, 3),
            "timestamp": self.timestamp.isoformat(),
            "executed": self.executed,
            "urgency": self.urgency,
        }


@validated_dataclass
@dataclass
class Position:
    """单只持仓"""
    cb_code: str
    cb_name: str
    quantity: int = 0              # 持有张数
    avg_cost: float = 0.0          # 平均成本价
    current_price: float = 0.0     # 当前价
    market_value: float = 0.0      # 市值
    cost_basis: float = 0.0        # 成本
    unrealized_pnl: float = 0.0    # 浮动盈亏(元)
    unrealized_pnl_pct: float = 0.0  # 浮动盈亏(%)
    seven_dim_score: float = 0.0   # 最新七维得分
    whitelist_rank: int = 0        # 白名单排名
    in_buffer_zone: bool = False   # 是否在缓冲带
    buffer_days_out: int = 0       # 连续在60名外天数
    credit_score: float = 0.0      # 信用评分
    days_held: int = 0             # 持仓天数
    consecutive_up_days: int = 0   # 连续上涨天数
    max_profit_pct: float = 0.0    # 持仓以来最高盈利(%)
    stop_loss_price: float = 0.0   # 当前止损价
    sector: str = ""               # 所属行业
    buy_date: Optional[date] = None  # 买入日期
    buy_price: float = 0.0         # 买入价格
    # 止盈记录
    tp1_triggered: bool = False    # 第一止盈位已触发
    tp2_triggered: bool = False    # 第二止盈位已触发

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cb_code": self.cb_code,
            "cb_name": self.cb_name,
            "quantity": self.quantity,
            "avg_cost": round(self.avg_cost, 3),
            "current_price": round(self.current_price, 3),
            "market_value": round(self.market_value, 2),
            "cost_basis": round(self.cost_basis, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "unrealized_pnl_pct": round(self.unrealized_pnl_pct, 2),
            "seven_dim_score": round(self.seven_dim_score, 2),
            "whitelist_rank": self.whitelist_rank,
            "in_buffer_zone": self.in_buffer_zone,
            "buffer_days_out": self.buffer_days_out,
            "credit_score": round(self.credit_score, 2),
            "days_held": self.days_held,
            "consecutive_up_days": self.consecutive_up_days,
            "max_profit_pct": round(self.max_profit_pct, 2),
            "stop_loss_price": round(self.stop_loss_price, 3),
            "sector": self.sector,
            "buy_date": self.buy_date.isoformat() if self.buy_date else None,
            "buy_price": round(self.buy_price, 3),
            "tp1_triggered": self.tp1_triggered,
            "tp2_triggered": self.tp2_triggered,
        }


@dataclass
class Portfolio:
    """组合状态"""
    date: date
    aum: float = 0.0               # 总资产(万元)
    cash: float = 0.0              # 现金(万元)
    positions: Dict[str, Position] = field(default_factory=dict)
    total_cost_basis: float = 0.0  # 总成本
    total_market_value: float = 0.0  # 总市值
    total_unrealized_pnl: float = 0.0  # 总浮动盈亏
    position_count: int = 0        # 持仓数量
    max_position_ratio: float = 0.05  # 单只最高仓位
    max_sector_ratio: float = 0.15   # 单行业最高仓位
    sector_positions: Dict[str, float] = field(default_factory=dict)  # 行业仓位

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date.isoformat() if isinstance(self.date, date) else self.date,
            "aum": round(self.aum, 2),
            "cash": round(self.cash, 2),
            "position_count": self.position_count,
            "total_market_value": round(self.total_market_value, 2),
            "total_unrealized_pnl": round(self.total_unrealized_pnl, 2),
            "positions": {k: v.to_dict() for k, v in self.positions.items()},
            "sector_positions": self.sector_positions,
        }


@dataclass
class TransactionCost:
    """交易成本"""
    commission: float = 0.0        # 佣金
    exchange_fee: float = 0.0      # 经手费
    slippage: float = 0.0          # 滑点
    impact: float = 0.0            # 冲击成本
    total: float = 0.0             # 总成本

    def to_dict(self) -> Dict[str, Any]:
        return {
            "commission": round(self.commission, 4),
            "exchange_fee": round(self.exchange_fee, 4),
            "slippage": round(self.slippage, 4),
            "impact": round(self.impact, 4),
            "total": round(self.total, 4),
        }


@dataclass
class HedgeStatus:
    """对冲状态"""
    active: bool = False
    correlation: float = 0.0       # 60日滚动相关性
    csi300_hedge_ratio: float = 0.0  # 股指期货对冲比例
    put_hedge_ratio: float = 0.0   # 认沽期权对冲比例
    pure_bond_ratio: float = 0.0   # 纯债性转债比例
    monthly_cost: float = 0.0      # 月度对冲成本

    def to_dict(self) -> Dict[str, Any]:
        return {
            "active": self.active,
            "correlation": round(self.correlation, 3),
            "csi300_hedge_ratio": round(self.csi300_hedge_ratio, 2),
            "put_hedge_ratio": round(self.put_hedge_ratio, 2),
            "pure_bond_ratio": round(self.pure_bond_ratio, 2),
            "monthly_cost": round(self.monthly_cost, 4),
        }


@dataclass
class DailyReport:
    """每日报告"""
    date: date
    portfolio: Portfolio
    timing: TimingSignal
    signals: List[TradeSignal]
    costs: Dict[str, TransactionCost]
    whitelist: List[str]
    hedge: HedgeStatus
    performance: Dict[str, float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date.isoformat() if isinstance(self.date, date) else self.date,
            "portfolio": self.portfolio.to_dict(),
            "timing": self.timing.to_dict(),
            "signals": [s.to_dict() for s in self.signals],
            "costs": {k: v.to_dict() for k, v in self.costs.items()},
            "whitelist": self.whitelist,
            "hedge": self.hedge.to_dict(),
            "performance": self.performance,
        }
