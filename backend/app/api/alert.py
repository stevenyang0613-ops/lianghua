from fastapi import APIRouter, Request, HTTPException
from typing import List

from app.models.alert import AlertCondition, AlertTrigger, AlertType

router = APIRouter()


def _get_alert_engine(request: Request):
    return request.app.state.alert_engine


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
