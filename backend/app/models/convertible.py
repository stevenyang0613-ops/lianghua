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


class ConvertibleQuote(BaseModel):
    """可转债实时行情"""
    code: str = Field(..., description="转债代码")
    name: str = Field("", description="转债简称")
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
    buyback_amount: Optional[float] = Field(None, description="回购金额(亿元)")
    mgmt_buy_price: Optional[float] = Field(None, description="管理层增持价")
    timestamp: datetime = Field(default_factory=datetime.now)
