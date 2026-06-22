from fastapi import APIRouter, Request, HTTPException
from typing import List

from app.models.alert import AlertCondition, AlertTrigger, AlertType

router = APIRouter()


def _get_alert_engine(request: Request):
    return request.app.state.alert_engine


@router.get("/alerts/rules")
async def get_alert_rules():
    """兼容端点：返回空规则列表（前端 community.ts 调用）"""
    return {"rules": [], "hint": "legacy alert rules not implemented"}


@router.post("/alerts/rules")
async def create_alert_rule():
    """兼容端点：接受规则创建（前端 community.ts 调用）"""
    return {"status": "ok", "rule_id": "stub", "hint": "legacy alert rules not implemented"}


@router.put("/alerts/rules/{rule_id}")
async def update_alert_rule(rule_id: str):
    """兼容端点：接受规则更新（前端 community.ts 调用）"""
    return {"status": "ok", "rule_id": rule_id, "hint": "legacy alert rules not implemented"}


@router.delete("/alerts/rules/{rule_id}")
async def delete_alert_rule(rule_id: str):
    """兼容端点：接受规则删除（前端 community.ts 调用）"""
    return {"status": "ok", "rule_id": rule_id, "hint": "legacy alert rules not implemented"}


@router.get("/alerts/active")
async def get_active_alerts():
    """兼容端点：返回空活动告警列表（前端 community.ts 调用）"""
    return {"alerts": [], "hint": "legacy active alerts not implemented"}


@router.get("/alerts/history")
async def get_alert_history():
    """兼容端点：返回空告警历史（前端 community.ts 调用）"""
    return {"history": [], "hint": "legacy alert history not implemented"}


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str):
    """兼容端点：确认告警（前端 community.ts 调用）"""
    return {"status": "ok", "alert_id": alert_id, "hint": "legacy alert acknowledge not implemented"}


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str):
    """兼容端点：解决告警（前端 community.ts 调用）"""
    return {"status": "ok", "alert_id": alert_id, "hint": "legacy alert resolve not implemented"}


@router.post("/alerts/rules/{rule_id}/webhook")
async def set_alert_webhook(rule_id: str):
    """兼容端点：设置 webhook（前端 community.ts 调用）"""
    return {"status": "ok", "rule_id": rule_id, "hint": "legacy webhook not implemented"}


@router.post("/alerts/test")
async def test_alert_channel():
    """兼容端点：测试告警通道（前端 community.ts 调用）"""
    return {"status": "ok", "hint": "legacy alert test not implemented"}


@router.post("/alerts/email")
async def send_alert_email():
    """兼容端点：邮件告警（前端 alertNotification.ts 调用）"""
    return {"status": "ok", "hint": "email alert not implemented"}


@router.post("/alerts/sms")
async def send_alert_sms():
    """兼容端点：短信告警（前端 alertNotification.ts 调用）"""
    return {"status": "ok", "hint": "sms alert not implemented"}


@router.get("/alerts")
async def get_alerts(request: Request):
    engine = _get_alert_engine(request)
    alerts = engine.get_alerts()
    return {"alerts": [a.model_dump() for a in alerts]}


@router.post("/alerts")
async def create_alert(request: Request, alert: AlertCondition):
    engine = _get_alert_engine(request)
    engine.add_alert(alert)
    return {"status": "ok", "alert": alert.model_dump()}


@router.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: str, request: Request):
    engine = _get_alert_engine(request)
    engine.remove_alert(alert_id)
    return {"status": "ok"}


@router.get("/alert-types")
async def get_alert_types():
    return {"types": [{"value": t.value, "label": _get_type_label(t)} for t in AlertType]}


def _get_type_label(alert_type: AlertType) -> str:
    labels = {
        AlertType.PRICE_ABOVE: "价格高于",
        AlertType.PRICE_BELOW: "价格低于",
        AlertType.PREMIUM_ABOVE: "溢价率高于",
        AlertType.PREMIUM_BELOW: "溢价率低于",
        AlertType.DUAL_LOW_BELOW: "双低值低于",
        AlertType.YTM_ABOVE: "YTM高于",
    }
    return labels.get(alert_type, alert_type.value)
