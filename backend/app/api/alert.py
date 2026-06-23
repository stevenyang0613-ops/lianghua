from fastapi import APIRouter, Request, HTTPException
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from app.models.alert import AlertCondition, AlertTrigger, AlertType

router = APIRouter()


class AlertRuleCreate(BaseModel):
    code: str = ""
    name: str = ""
    alert_type: str
    threshold: float
    enabled: bool = True
    description: str = ""
    channels: List[str] = Field(default_factory=list)
    suppress_duration: int = 300
    tags: List[str] = Field(default_factory=list)


class AlertRuleUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    alert_type: Optional[str] = None
    threshold: Optional[float] = None
    enabled: Optional[bool] = None
    description: Optional[str] = None
    channels: Optional[List[str]] = None
    suppress_duration: Optional[int] = None
    tags: Optional[List[str]] = None


class AlertAcknowledge(BaseModel):
    acknowledged: bool = True


class AlertResolve(BaseModel):
    resolved: bool = True


def _get_alert_engine(request: Request):
    engine = getattr(request.app.state, "alert_engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="告警引擎未初始化")
    return engine


@router.get("/alerts/rules")
async def get_alert_rules(request: Request, code: Optional[str] = None, alert_type: Optional[str] = None):
    """获取告警规则列表"""
    engine = _get_alert_engine(request)
    at = AlertType(alert_type) if alert_type else None
    alerts = engine.get_alerts(code=code, alert_type=at)
    return {"rules": [a.model_dump() for a in alerts], "count": len(alerts)}


@router.post("/alerts/rules")
async def create_alert_rule(req: AlertRuleCreate, request: Request):
    """创建告警规则"""
    engine = _get_alert_engine(request)
    try:
        alert_type = AlertType(req.alert_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"不支持的告警类型: {req.alert_type}")
    alert = AlertCondition(
        code=req.code,
        name=req.name,
        alert_type=alert_type,
        threshold=req.threshold,
        enabled=req.enabled,
        description=req.description,
        channels=req.channels,
        suppress_duration=req.suppress_duration,
        tags=req.tags,
    )
    engine.add_alert(alert)
    return {"status": "ok", "rule_id": alert.id, "alert": alert.model_dump()}


@router.put("/alerts/rules/{rule_id}")
async def update_alert_rule(rule_id: str, req: AlertRuleUpdate, request: Request):
    """更新告警规则"""
    engine = _get_alert_engine(request)
    alert = engine.get_alert(rule_id)
    if not alert:
        raise HTTPException(status_code=404, detail="规则不存在")
    updates = req.model_dump(exclude_unset=True)
    if "alert_type" in updates:
        try:
            updates["alert_type"] = AlertType(updates["alert_type"])
        except ValueError:
            raise HTTPException(status_code=400, detail=f"不支持的告警类型: {updates['alert_type']}")
    engine.update_alert(rule_id, updates)
    return {"status": "ok", "rule_id": rule_id, "alert": engine.get_alert(rule_id).model_dump()}


@router.delete("/alerts/rules/{rule_id}")
async def delete_alert_rule(rule_id: str, request: Request):
    """删除告警规则"""
    engine = _get_alert_engine(request)
    if not engine.remove_alert(rule_id):
        raise HTTPException(status_code=404, detail="规则不存在")
    return {"status": "ok", "rule_id": rule_id}


@router.get("/alerts/active")
async def get_active_alerts(request: Request):
    """获取活动告警规则"""
    engine = _get_alert_engine(request)
    alerts = [a for a in engine.get_alerts() if a.enabled]
    return {"alerts": [a.model_dump() for a in alerts], "count": len(alerts)}


@router.get("/alerts/history")
async def get_alert_history(request: Request, limit: int = 100, acknowledged: Optional[bool] = None, resolved: Optional[bool] = None):
    """获取告警触发历史"""
    engine = _get_alert_engine(request)
    history = engine.get_trigger_history(limit=limit, acknowledged=acknowledged, resolved=resolved)
    return {"history": history, "count": len(history)}


@router.post("/alerts/{trigger_id}/acknowledge")
async def acknowledge_alert(trigger_id: str, request: Request):
    """确认告警"""
    engine = _get_alert_engine(request)
    if not engine.acknowledge_alert(trigger_id):
        raise HTTPException(status_code=404, detail="告警触发记录不存在")
    return {"status": "ok", "trigger_id": trigger_id}


@router.post("/alerts/{trigger_id}/resolve")
async def resolve_alert(trigger_id: str, request: Request):
    """解决告警"""
    engine = _get_alert_engine(request)
    if not engine.resolve_alert(trigger_id):
        raise HTTPException(status_code=404, detail="告警触发记录不存在")
    return {"status": "ok", "trigger_id": trigger_id}


@router.post("/alerts/rules/{rule_id}/webhook")
async def set_alert_webhook(rule_id: str, request: Request):
    """设置 webhook（预留）"""
    engine = _get_alert_engine(request)
    alert = engine.get_alert(rule_id)
    if not alert:
        raise HTTPException(status_code=404, detail="规则不存在")
    return {"status": "ok", "rule_id": rule_id, "hint": "webhook 配置已记录"}


@router.post("/alerts/test")
async def test_alert_channel(request: Request):
    """测试告警通道"""
    engine = _get_alert_engine(request)
    test_trigger = AlertTrigger(
        rule_id="test",
        code="128001",
        name="测试转债",
        alert_type=AlertType.PRICE_ABOVE,
        threshold=100,
        current_value=105,
        message="这是一条测试告警",
    )
    for callback in engine._callbacks:
        try:
            await callback(test_trigger)
        except Exception:
            pass
    return {"status": "ok", "test_trigger": test_trigger.model_dump()}


@router.post("/alerts/email")
async def send_alert_email(request: Request):
    """发送邮件告警（预留）"""
    return {"status": "ok", "hint": "邮件告警通道预留，需配置 SMTP"}


@router.post("/alerts/sms")
async def send_alert_sms(request: Request):
    """发送短信告警（预留）"""
    return {"status": "ok", "hint": "短信告警通道预留，需配置短信服务商"}


@router.get("/alerts")
async def get_alerts_legacy(request: Request):
    """兼容旧版端点"""
    engine = _get_alert_engine(request)
    alerts = engine.get_alerts()
    return {"alerts": [a.model_dump() for a in alerts]}


@router.post("/alerts")
async def create_alert_legacy(request: Request, alert: AlertCondition):
    """兼容旧版端点"""
    engine = _get_alert_engine(request)
    engine.add_alert(alert)
    return {"status": "ok", "alert": alert.model_dump()}


@router.delete("/alerts/{alert_id}")
async def delete_alert_legacy(alert_id: str, request: Request):
    """兼容旧版端点"""
    engine = _get_alert_engine(request)
    if not engine.remove_alert(alert_id):
        raise HTTPException(status_code=404, detail="规则不存在")
    return {"status": "ok"}


@router.get("/alert-types")
async def get_alert_types():
    """获取所有支持的告警类型"""
    labels = {
        AlertType.PRICE_ABOVE: "价格高于",
        AlertType.PRICE_BELOW: "价格低于",
        AlertType.PREMIUM_ABOVE: "溢价率高于",
        AlertType.PREMIUM_BELOW: "溢价率低于",
        AlertType.DUAL_LOW_BELOW: "双低值低于",
        AlertType.YTM_ABOVE: "YTM高于",
        AlertType.CHANGE_PCT_ABOVE: "涨跌幅高于",
        AlertType.CHANGE_PCT_BELOW: "涨跌幅低于",
        AlertType.TURNOVER_RATE_ABOVE: "换手率高于",
        AlertType.IS_CALLED: "已公告强赎",
        AlertType.FORCED_CALL_DAYS_BELOW: "强赎倒计时低于",
        AlertType.VOLUME_ABOVE: "成交额高于",
        AlertType.VOLUME_BELOW: "成交额低于",
        AlertType.RATING_DOWNGRADE: "评级评分低于",
    }
    return {"types": [{"value": t.value, "label": labels.get(t, t.value)} for t in AlertType]}
