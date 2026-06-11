"""
实时择时信号WebSocket推送模块

通过WebSocket推送：
- 多维度择时得分更新
- 仓位上限变化通知
- 市场环境切换通知
- 对冲启动/停止通知
"""

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional, Callable, Awaitable
from enum import Enum
import asyncio
import json
import logging

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """信号类型"""
    TIMING_UPDATE = 'timing_update'      # 择时得分更新
    POSITION_CHANGE = 'position_change'  # 仓位变化
    MARKET_SWITCH = 'market_switch'      # 市场环境切换
    HEDGE_TRIGGER = 'hedge_trigger'      # 对冲触发
    REBALANCE_ALERT = 'rebalance_alert'  # 调仓预警


@dataclass
class TimingSignal:
    """择时信号"""
    type: str
    score: float
    position_limit: float
    market_env: str
    should_hedge: bool
    should_rebalance: bool
    details: dict
    ts: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PositionChange:
    """仓位变化信号"""
    type: str
    old_limit: float
    new_limit: float
    change_pct: float
    reason: str
    ts: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MarketSwitch:
    """市场环境切换信号"""
    type: str
    old_env: str
    new_env: str
    confirmed: bool
    weeks_count: int
    ts: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HedgeTrigger:
    """对冲触发信号"""
    type: str
    action: str  # 'start' or 'stop'
    hedge_ratio: float
    reason: str
    ts: str

    def to_dict(self) -> dict:
        return asdict(self)


class TimingSignalBroadcaster:
    """择时信号广播器"""

    def __init__(self):
        self._subscribers: set[Callable[[dict], Awaitable[None]]] = set()
        self._last_timing_signal: Optional[TimingSignal] = None
        self._last_position_limit: float = 0.8
        self._last_market_env: str = 'neutral'
        self._last_hedge_status: bool = False

    def subscribe(self, callback: Callable[[dict], Awaitable[None]]) -> None:
        """订阅信号"""
        self._subscribers.add(callback)
        logger.info(f"[TimingWS] New subscriber, total: {len(self._subscribers)}")

    def unsubscribe(self, callback: Callable[[dict], Awaitable[None]]) -> None:
        """取消订阅"""
        self._subscribers.discard(callback)
        logger.info(f"[TimingWS] Unsubscribed, total: {len(self._subscribers)}")

    async def broadcast(self, signal: dict) -> None:
        """广播信号给所有订阅者"""
        if not self._subscribers:
            return

        tasks = []
        for callback in list(self._subscribers):
            try:
                tasks.append(callback(signal))
            except Exception as e:
                logger.warning(f"[TimingWS] Broadcast error: {e}")

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def push_timing_update(
        self,
        score: float,
        position_limit: float,
        market_env: str,
        should_hedge: bool,
        details: dict,
    ) -> None:
        """推送择时得分更新"""
        now = datetime.now().isoformat()

        # 检查是否需要调仓
        should_rebalance = (
            abs(position_limit - self._last_position_limit) > 0.2 or
            market_env != self._last_market_env
        )

        signal = TimingSignal(
            type=SignalType.TIMING_UPDATE.value,
            score=round(score, 2),
            position_limit=position_limit,
            market_env=market_env,
            should_hedge=should_hedge,
            should_rebalance=should_rebalance,
            details=details,
            ts=now,
        )

        self._last_timing_signal = signal
        await self.broadcast(signal.to_dict())

        # 检查仓位变化
        if abs(position_limit - self._last_position_limit) > 0.05:
            await self.push_position_change(
                self._last_position_limit,
                position_limit,
                f"择时得分变化: {score:.1f}"
            )

        # 检查市场环境切换
        if market_env != self._last_market_env:
            await self.push_market_switch(
                self._last_market_env,
                market_env,
                confirmed=True,
                weeks_count=2
            )

        # 检查对冲状态变化
        if should_hedge != self._last_hedge_status:
            await self.push_hedge_trigger(
                'start' if should_hedge else 'stop',
                0.3 if should_hedge else 0,
                f"择时得分{score:.1f}{'<' if should_hedge else '>='}30"
            )

        self._last_position_limit = position_limit
        self._last_market_env = market_env
        self._last_hedge_status = should_hedge

    async def push_position_change(
        self,
        old_limit: float,
        new_limit: float,
        reason: str,
    ) -> None:
        """推送仓位变化信号"""
        change_pct = (new_limit - old_limit) / old_limit * 100 if old_limit > 0 else 0

        signal = PositionChange(
            type=SignalType.POSITION_CHANGE.value,
            old_limit=round(old_limit, 2),
            new_limit=round(new_limit, 2),
            change_pct=round(change_pct, 1),
            reason=reason,
            ts=datetime.now().isoformat(),
        )

        await self.broadcast(signal.to_dict())
        logger.info(f"[TimingWS] Position change: {old_limit:.2f} -> {new_limit:.2f} ({change_pct:+.1f}%)")

    async def push_market_switch(
        self,
        old_env: str,
        new_env: str,
        confirmed: bool,
        weeks_count: int,
    ) -> None:
        """推送市场环境切换信号"""
        signal = MarketSwitch(
            type=SignalType.MARKET_SWITCH.value,
            old_env=old_env,
            new_env=new_env,
            confirmed=confirmed,
            weeks_count=weeks_count,
            ts=datetime.now().isoformat(),
        )

        await self.broadcast(signal.to_dict())
        logger.info(f"[TimingWS] Market switch: {old_env} -> {new_env} (confirmed={confirmed})")

    async def push_hedge_trigger(
        self,
        action: str,
        hedge_ratio: float,
        reason: str,
    ) -> None:
        """推送对冲触发信号"""
        signal = HedgeTrigger(
            type=SignalType.HEDGE_TRIGGER.value,
            action=action,
            hedge_ratio=round(hedge_ratio, 2),
            reason=reason,
            ts=datetime.now().isoformat(),
        )

        await self.broadcast(signal.to_dict())
        logger.info(f"[TimingWS] Hedge {action}: ratio={hedge_ratio:.2f}, reason={reason}")

    async def push_rebalance_alert(
        self,
        codes_to_sell: list[str],
        codes_to_buy: list[str],
        estimated_cost: float,
    ) -> None:
        """推送调仓预警"""
        signal = {
            'type': SignalType.REBALANCE_ALERT.value,
            'codes_to_sell': codes_to_sell,
            'codes_to_buy': codes_to_buy,
            'estimated_cost': round(estimated_cost, 2),
            'ts': datetime.now().isoformat(),
        }

        await self.broadcast(signal)
        logger.info(f"[TimingWS] Rebalance alert: sell {len(codes_to_sell)}, buy {len(codes_to_buy)}")

    @property
    def last_signal(self) -> Optional[dict]:
        """获取最近的信号"""
        return self._last_timing_signal.to_dict() if self._last_timing_signal else None

    def get_status(self) -> dict:
        """获取当前状态"""
        return {
            'position_limit': self._last_position_limit,
            'market_env': self._last_market_env,
            'hedge_active': self._last_hedge_status,
            'subscribers': len(self._subscribers),
        }


# 全局单例
_broadcaster: Optional[TimingSignalBroadcaster] = None


def get_timing_broadcaster() -> TimingSignalBroadcaster:
    """获取全局择时信号广播器"""
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = TimingSignalBroadcaster()
    return _broadcaster
