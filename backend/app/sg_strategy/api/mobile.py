"""松岗量化可转债策略 V3.0 移动端API模块

功能:
- 移动端API接口
- 推送服务
- 快速操作接口
- 简化数据格式
- 离线支持
"""
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Dict, Optional, Any
from enum import Enum
import logging
import json
from fastapi import Depends, Query, BackgroundTasks

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mobile", tags=["移动端"])


# ============ 枚举类型 ============

class PushType(str, Enum):
    """推送类型"""
    SIGNAL = "signal"
    TRADE = "trade"
    ALERT = "alert"
    REPORT = "report"
    MARKET = "market"


class QuickAction(str, Enum):
    """快速操作"""
    VIEW_PORTFOLIO = "view_portfolio"
    VIEW_SIGNALS = "view_signals"
    CONFIRM_TRADE = "confirm_trade"
    CANCEL_SIGNAL = "cancel_signal"
    VIEW_REPORT = "view_report"


# ============ 数据模型 ============

class MobileSummary(BaseModel):
    """移动端汇总"""
    nav: float
    daily_return: float
    drawdown: float
    position_count: int
    pending_signals: int
    last_update: datetime


class MobilePosition(BaseModel):
    """移动端持仓"""
    code: str
    name: str
    quantity: int
    profit_pct: float
    weight: float


class MobileSignal(BaseModel):
    """移动端信号"""
    signal_id: str
    code: str
    name: str
    action: str
    quantity: int
    price: float
    reason: str
    expire_time: datetime


class PushNotification(BaseModel):
    """推送通知"""
    push_id: str
    push_type: PushType
    title: str
    message: str
    data: Dict[str, Any] = {}
    timestamp: datetime
    is_read: bool = False


class QuickActionRequest(BaseModel):
    """快速操作请求"""
    action: QuickAction
    target_id: Optional[str] = None
    params: Dict[str, Any] = {}


class QuickActionResponse(BaseModel):
    """快速操作响应"""
    success: bool
    message: str
    data: Dict[str, Any] = {}


# ============ 推送服务 ============

class PushService:
    """推送服务"""

    def __init__(self):
        self._devices: Dict[str, Dict] = {}
        self._notifications: List[PushNotification] = []

    def register_device(
        self,
        device_id: str,
        device_token: str,
        platform: str,  # ios, android
        user_id: str = None,
    ):
        """注册设备"""
        self._devices[device_id] = {
            "device_token": device_token,
            "platform": platform,
            "user_id": user_id,
            "registered_at": datetime.now(),
        }
        logger.info(f"[Push] 注册设备: {device_id}")

    def unregister_device(self, device_id: str):
        """注销设备"""
        if device_id in self._devices:
            del self._devices[device_id]

    def send_push(
        self,
        device_id: str,
        push_type: PushType,
        title: str,
        message: str,
        data: Dict = None,
    ) -> bool:
        """发送推送"""
        if device_id not in self._devices:
            return False

        device = self._devices[device_id]

        # 记录通知
        notification = PushNotification(
            push_id=f"push_{datetime.now().strftime('%Y%m%d%H%M%S')}_{device_id[:8]}",
            push_type=push_type,
            title=title,
            message=message,
            data=data or {},
            timestamp=datetime.now(),
        )
        self._notifications.append(notification)

        # 实际推送逻辑
        platform = device["platform"]
        token = device["device_token"]

        try:
            if platform == "ios":
                self._send_apns(token, title, message, data)
            else:
                self._send_fcm(token, title, message, data)

            logger.info(f"[Push] 发送成功: {device_id}, {push_type}")
            return True

        except Exception as e:
            logger.error(f"[Push] 发送失败: {e}")
            return False

    def _send_apns(self, token: str, title: str, message: str, data: Dict):
        """发送APNS推送"""
        # 实际使用时需要配置APNS证书
        logger.debug(f"[Push] APNS -> {token}: {title}")

    def _send_fcm(self, token: str, title: str, message: str, data: Dict):
        """发送FCM推送"""
        # 实际使用时需要配置Firebase
        logger.debug(f"[Push] FCM -> {token}: {title}")

    def broadcast(
        self,
        push_type: PushType,
        title: str,
        message: str,
        data: Dict = None,
    ):
        """广播推送"""
        for device_id in self._devices:
            self.send_push(device_id, push_type, title, message, data)

    def get_notifications(
        self,
        device_id: str,
        unread_only: bool = False,
        limit: int = 50,
    ) -> List[PushNotification]:
        """获取通知列表"""
        notifications = self._notifications

        if unread_only:
            notifications = [n for n in notifications if not n.is_read]

        return notifications[-limit:]

    def mark_read(self, push_id: str):
        """标记已读"""
        for n in self._notifications:
            if n.push_id == push_id:
                n.is_read = True

    def push_signal(self, signal: Dict):
        """推送信号"""
        code = signal.get("code", "")
        action = signal.get("action", "")

        title = f"交易信号: {action.upper()} {code}"
        message = f"建议{action} {signal.get('quantity', 0)}张 @ {signal.get('price', 0):.2f}"

        self.broadcast(PushType.SIGNAL, title, message, signal)

    def push_trade(self, trade: Dict):
        """推送成交"""
        title = f"成交通知: {trade.get('action', '')} {trade.get('code', '')}"
        message = f"成交{trade.get('quantity', 0)}张 @ {trade.get('price', 0):.2f}"

        self.broadcast(PushType.TRADE, title, message, trade)

    def push_alert(self, alert: Dict):
        """推送告警"""
        level = alert.get("level", "warning")
        title = f"[{level.upper()}] {alert.get('type', '告警')}"
        message = alert.get("message", "")

        self.broadcast(PushType.ALERT, title, message, alert)


# ============ 移动端服务 ============

class MobileService:
    """移动端服务"""

    def __init__(self):
        self.push_service = PushService()

    def get_summary(self) -> MobileSummary:
        """获取汇总"""
        import random

        return MobileSummary(
            nav=round(1 + random.uniform(-0.1, 0.3), 4),
            daily_return=round(random.uniform(-0.02, 0.02), 4),
            drawdown=round(random.uniform(0, 0.05), 4),
            position_count=random.randint(10, 20),
            pending_signals=random.randint(0, 5),
            last_update=datetime.now(),
        )

    def get_positions(self, limit: int = 20) -> List[MobilePosition]:
        """获取持仓列表"""
        import random

        positions = []
        for i in range(limit):
            positions.append(MobilePosition(
                code=f"11000{i+1}",
                name=f"转债{chr(65+i)}",
                quantity=random.randint(500, 2000) * 100,
                profit_pct=round(random.uniform(-0.05, 0.15), 4),
                weight=round(random.uniform(0.01, 0.08), 4),
            ))

        return sorted(positions, key=lambda x: x.weight, reverse=True)

    def get_signals(self) -> List[MobileSignal]:
        """获取待处理信号"""
        import random

        signals = []
        actions = ["buy", "sell"]

        for i in range(random.randint(1, 5)):
            signals.append(MobileSignal(
                signal_id=f"sig_{datetime.now().strftime('%Y%m%d')}{i:03d}",
                code=f"11000{random.randint(1, 20)}",
                name=f"转债{chr(65+random.randint(0, 19))}",
                action=random.choice(actions),
                quantity=random.randint(1, 10) * 100,
                price=round(random.uniform(95, 115), 2),
                reason="量化信号触发",
                expire_time=datetime.now(),
            ))

        return signals

    def execute_quick_action(
        self,
        action: QuickAction,
        target_id: str = None,
        params: Dict = None,
    ) -> QuickActionResponse:
        """执行快速操作"""
        params = params or {}

        if action == QuickAction.VIEW_PORTFOLIO:
            return QuickActionResponse(
                success=True,
                message="获取组合信息成功",
                data={"summary": self.get_summary().dict()},
            )

        elif action == QuickAction.VIEW_SIGNALS:
            return QuickActionResponse(
                success=True,
                message="获取信号成功",
                data={"signals": [s.dict() for s in self.get_signals()]},
            )

        elif action == QuickAction.CONFIRM_TRADE:
            return QuickActionResponse(
                success=True,
                message=f"交易已确认: {target_id}",
                data={"signal_id": target_id, "status": "confirmed"},
            )

        elif action == QuickAction.CANCEL_SIGNAL:
            return QuickActionResponse(
                success=True,
                message=f"信号已取消: {target_id}",
                data={"signal_id": target_id, "status": "cancelled"},
            )

        else:
            return QuickActionResponse(
                success=False,
                message=f"未知操作: {action}",
            )


def get_mobile_service() -> MobileService:
    """获取移动端服务"""
    return MobileService()


# ============ API路由 ============

@router.get("/summary", response_model=MobileSummary, summary="获取汇总")
async def get_mobile_summary(
    service: MobileService = Depends(lambda: get_mobile_service()),
):
    """获取移动端汇总数据"""
    return service.get_summary()


@router.get("/positions", response_model=List[MobilePosition], summary="获取持仓")
async def get_mobile_positions(
    limit: int = Query(20, ge=1, le=50),
    service: MobileService = Depends(lambda: get_mobile_service()),
):
    """获取持仓列表"""
    return service.get_positions(limit)


@router.get("/signals", response_model=List[MobileSignal], summary="获取信号")
async def get_mobile_signals(
    service: MobileService = Depends(lambda: get_mobile_service()),
):
    """获取待处理信号"""
    return service.get_signals()


@router.post("/action", response_model=QuickActionResponse, summary="快速操作")
async def execute_action(
    request: QuickActionRequest,
    service: MobileService = Depends(lambda: get_mobile_service()),
):
    """执行快速操作"""
    return service.execute_quick_action(
        request.action,
        request.target_id,
        request.params,
    )


@router.post("/device/register", summary="注册设备")
async def register_device(
    device_id: str,
    device_token: str,
    platform: str,
    user_id: str = None,
    service: MobileService = Depends(lambda: get_mobile_service()),
):
    """注册设备用于推送"""
    service.push_service.register_device(device_id, device_token, platform, user_id)
    return {"success": True, "message": "设备注册成功"}


@router.post("/device/unregister", summary="注销设备")
async def unregister_device(
    device_id: str,
    service: MobileService = Depends(lambda: get_mobile_service()),
):
    """注销设备"""
    service.push_service.unregister_device(device_id)
    return {"success": True, "message": "设备已注销"}


@router.get("/notifications", response_model=List[PushNotification], summary="获取通知")
async def get_notifications(
    device_id: str,
    unread_only: bool = Query(False),
    limit: int = Query(50),
    service: MobileService = Depends(lambda: get_mobile_service()),
):
    """获取推送通知列表"""
    return service.push_service.get_notifications(device_id, unread_only, limit)


@router.post("/notifications/{push_id}/read", summary="标记已读")
async def mark_notification_read(
    push_id: str,
    service: MobileService = Depends(lambda: get_mobile_service()),
):
    """标记通知已读"""
    service.push_service.mark_read(push_id)
    return {"success": True}


@router.post("/push/signal", summary="推送信号")
async def push_signal(
    signal: Dict,
    background_tasks: BackgroundTasks,
    service: MobileService = Depends(lambda: get_mobile_service()),
):
    """推送交易信号"""
    background_tasks.add_task(service.push_service.push_signal, signal)
    return {"success": True, "message": "推送已发送"}


@router.post("/push/trade", summary="推送成交")
async def push_trade(
    trade: Dict,
    background_tasks: BackgroundTasks,
    service: MobileService = Depends(lambda: get_mobile_service()),
):
    """推送成交通知"""
    background_tasks.add_task(service.push_service.push_trade, trade)
    return {"success": True, "message": "推送已发送"}


@router.post("/push/alert", summary="推送告警")
async def push_alert(
    alert: Dict,
    background_tasks: BackgroundTasks,
    service: MobileService = Depends(lambda: get_mobile_service()),
):
    """推送告警通知"""
    background_tasks.add_task(service.push_service.push_alert, alert)
    return {"success": True, "message": "推送已发送"}


@router.get("/widget/home", summary="首页小组件数据")
async def get_home_widget(
    service: MobileService = Depends(lambda: get_mobile_service()),
):
    """获取首页小组件数据"""
    summary = service.get_summary()
    return {
        "nav": summary.nav,
        "daily_return": f"{'+' if summary.daily_return >= 0 else ''}{summary.daily_return*100:.2f}%",
        "position_count": summary.position_count,
        "pending_count": summary.pending_signals,
        "status": "正常" if summary.drawdown < 0.05 else "注意",
    }
