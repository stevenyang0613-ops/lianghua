from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


class ConvertibleBond(BaseModel):
    """可转债基础信息"""
    code: str = Field(..., description="转债代码")
    name: str = Field(..., description="转债简称")
    stock_code: str = Field("", description="正股代码")
    stock_name: str = Field("", description="正股名称")
    conversion_price: float = Field(0.0, description="转股价")
    maturity_date: Optional[date] = Field(None, description="到期日")
    rating: str = Field("", description="评级")
    outstanding_scale: float = Field(0.0, description="剩余规模(亿元)")


# 评级 → 数值分映射（0-100 量表，供 data_enrich 和策略共用）
RATING_SCORE_MAP: dict[str, float] = {
    "AAA": 95, "AA+": 90, "AA": 85, "AA-": 80,
    "A+": 75, "A": 70, "A-": 65,
    "BBB+": 60, "BBB": 55, "BBB-": 50,
    "BB+": 45, "BB": 40, "BB-": 35,
}
RATING_SCORE_DEFAULT: float = 75.0


class ConvertibleQuote(BaseModel):
    """可转债实时行情"""
    code: str = Field(..., description="转债代码")
    name: str = Field("", description="转债简称")
    stock_code: str = Field("", description="正股代码")
    stock_name: str = Field("", description="正股名称")
    price: float = Field(0.0, description="最新价")
    change_pct: float = Field(0.0, description="涨跌幅(%)")
    stock_price: float = Field(0.0, description="正股价")
    stock_change_pct: float = Field(0.0, description="正股涨跌幅(%)")
    conversion_price: float = Field(0.0, description="转股价")
    conversion_value: float = Field(0.0, description="转股价值")
    premium_ratio: float = Field(0.0, description="转股溢价率(%)")
    dual_low: float = Field(0.0, description="双低值")
    ytm: float = Field(0.0, description="到期收益率(%)")
    volume: float = Field(0.0, description="成交额(亿元)")
    remaining_years: float = Field(0.0, description="剩余年限")
    forced_call_days: int = Field(0, description="强赎倒计时天数,0=未触发")
    is_called: bool = Field(False, description="是否已公告强赎/将强赎")
    call_status: str = Field("", description="强赎状态原文(集思录:已公告强赎/公告要强赎/已满足强赎条件/公告不强赎)")
    last_trade_date: Optional[date] = Field(None, description="最后交易日(强赎公告后停止交易日)")
    maturity_date: Optional[date] = Field(None, description="到期日(用于临近退市过滤)")
    redemption_price: float = Field(0.0, description="强赎价格(元/张)")
    industry: Optional[str] = Field(None, description="正股所属行业")
    rating: Optional[str] = Field(None, description="转债信用评级")
    roe: Optional[float] = Field(None, description="净资产收益率(%)")
    gpm: Optional[float] = Field(None, description="毛利率(%)")
    cagr: Optional[float] = Field(None, description="复合增长率(%)")
    debt_ratio: Optional[float] = Field(None, description="资产负债率(%)")
    current_ratio: Optional[float] = Field(None, description="流动比率")
    pe: Optional[float] = Field(None, description="市盈率")
    pb: Optional[float] = Field(None, description="市净率")
    iv: Optional[float] = Field(None, description="隐含波动率(%)")
    iv_source: Optional[str] = Field(None, description="IV来源: actual, hv_proxy, estimated")
    hv: Optional[float] = Field(None, description="历史波动率(%)")
    rating_score: Optional[float] = Field(None, description="评级评分(0-100)")
    pure_bond_premium_ratio: Optional[float] = Field(None, description="纯债溢价率(%)")
    buyback_amount: Optional[float] = Field(None, description="回购金额(亿元)")
    mgmt_buy_price: Optional[float] = Field(None, description="管理层增持价")
    turnover_rate: Optional[float] = Field(None, description="正股换手率(%)")
    net_capital_flow: Optional[float] = Field(None, description="主力资金净流入(万元)")
    net_capital_flow_pct: Optional[float] = Field(None, description="主力资金净流入占比(%)")
    net_super_flow: Optional[float] = Field(None, description="超大单净流入(万元)")
    net_big_flow: Optional[float] = Field(None, description="大单净流入(万元)")
    outstanding_scale: Optional[float] = Field(None, description="剩余规模(亿元)")
    pledge_ratio: Optional[float] = Field(None, description="大股东质押比例(%)")
    momentum_5d: Optional[float] = Field(None, description="5日动量(%)")
    momentum_10d: Optional[float] = Field(None, description="10日动量(%)")
    momentum_20d: Optional[float] = Field(None, description="20日动量(%)")
    momentum_60d: Optional[float] = Field(None, description="60日动量(%)")
    bond_value: Optional[float] = Field(None, description="纯债价值(元)")
    event_score: Optional[float] = Field(None, description="事件因子评分(0-1)")
    event_detail: Optional[str] = Field(None, description="最近事件摘要")
    concepts: Optional[list[str]] = Field(None, description="正股所属概念板块")
    north_net: Optional[float] = Field(None, description="北向资金持股(万股)")
    margin_balance: Optional[float] = Field(None, description="融资余额(亿元)")
    lhb_count: Optional[int] = Field(None, description="近5日龙虎榜次数")
    block_trade_amount: Optional[float] = Field(None, description="近5日大宗交易额(万元)")
    holder_num_change: Optional[float] = Field(None, description="股东户数变化率(%)")
    eps_forecast: Optional[float] = Field(None, description="一致预期EPS")
    eps: Optional[float] = Field(None, description="每股收益")
    bps: Optional[float] = Field(None, description="每股净资产")
    revenue_yoy: Optional[float] = Field(None, description="营业总收入同比增长(%)")
    profit_yoy: Optional[float] = Field(None, description="净利润同比增长(%)")
    restricted_release_amount: Optional[float] = Field(None, description="近期解禁金额(亿元)")
    timestamp: datetime = Field(default_factory=datetime.now)

    def to_strategy_dict(self) -> dict:
        """导出策略所需的字段子集，避免每次 getattr 开销。"""
        return {
            "code": self.code,
            "name": self.name,
            "price": self.price,
            "premium_ratio": self.premium_ratio,
            "volume": self.volume,
            "dual_low": self.dual_low,
            "ytm": self.ytm,
            "remaining_years": self.remaining_years,
            "change_pct": self.change_pct,
            "stock_price": self.stock_price,
            "conversion_value": self.conversion_value,
            "hv": self.hv,
            "iv": self.iv,
            "rating_score": (
                self.rating_score
                if self.rating_score is not None
                else RATING_SCORE_MAP.get(str(self.rating).strip().upper(), RATING_SCORE_DEFAULT)
                if self.rating
                else RATING_SCORE_DEFAULT
            ),
            "pure_bond_premium_ratio": (
                self.pure_bond_premium_ratio
                if self.pure_bond_premium_ratio is not None
                else round((self.price - self.bond_value) / self.bond_value * 100, 2)
                if (self.bond_value and self.bond_value > 0 and self.price)
                else None
            ),
            "bond_value": self.bond_value,
            "industry": self.industry,
            "pe": self.pe,
            "pb": self.pb,
            "roe": self.roe,
            "gpm": self.gpm,
            "call_status": self.call_status,
            "is_called": self.is_called,
            "forced_call_days": self.forced_call_days,
        }
