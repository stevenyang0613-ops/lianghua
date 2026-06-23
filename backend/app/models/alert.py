from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from enum import Enum


class AlertType(str, Enum):
    PRICE_ABOVE = "price_above"
    PRICE_BELOW = "price_below"
    PREMIUM_ABOVE = "premium_above"
    PREMIUM_BELOW = "premium_below"
    DUAL_LOW_BELOW = "dual_low_below"
    YTM_ABOVE = "ytm_above"
    CHANGE_PCT_ABOVE = "change_pct_above"
    CHANGE_PCT_BELOW = "change_pct_below"
    TURNOVER_RATE_ABOVE = "turnover_rate_above"
    IS_CALLED = "is_called"
    FORCED_CALL_DAYS_BELOW = "forced_call_days_below"
    RATING_DOWNGRADE = "rating_downgrade"
    VOLUME_ABOVE = "volume_above"
    VOLUME_BELOW = "volume_below"


class AlertCondition(BaseModel):
    """告警条件"""
    id: str = Field(default_factory=lambda: datetime.now().strftime("%Y%m%d%H%M%S") + str(hash(datetime.now()))[:6])
    code: str = ""
    name: str = ""
    alert_type: AlertType
    threshold: float
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    description: str = ""
    channels: list[str] = Field(default_factory=list)  # inApp, email, sms, webhook
    suppress_duration: int = 300  # 抑制时间(秒)
    tags: list[str] = Field(default_factory=list)


class AlertTrigger(BaseModel):
    """触发的告警"""
    id: str = Field(default_factory=lambda: datetime.now().strftime("%Y%m%d%H%M%S") + str(hash(datetime.now()))[:6])
    rule_id: str = ""
    code: str
    name: str
    alert_type: AlertType
    threshold: float
    current_value: float
    triggered_at: datetime = Field(default_factory=datetime.now)
    acknowledged: bool = False
    acknowledged_at: Optional[datetime] = None
    resolved: bool = False
    resolved_at: Optional[datetime] = None
    message: str = ""


class AlertConfig(BaseModel):
    """告警配置"""
    id: str
    condition: AlertCondition
    last_triggered: Optional[datetime] = None
    trigger_count: int = 0
