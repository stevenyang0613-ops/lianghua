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


class AlertCondition(BaseModel):
    """告警条件"""
    code: str
    name: str = ""
    alert_type: AlertType
    threshold: float
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.now)


class AlertTrigger(BaseModel):
    """触发的告警"""
    code: str
    name: str
    alert_type: AlertType
    threshold: float
    current_value: float
    triggered_at: datetime = Field(default_factory=datetime.now)
    acknowledged: bool = False


class AlertConfig(BaseModel):
    """告警配置"""
    id: str
    condition: AlertCondition
    last_triggered: Optional[datetime] = None
    trigger_count: int = 0
