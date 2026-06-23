"""自动止损机制"""
import numpy as np
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import logging
logger = logging.getLogger(__name__)


class StopLossType(Enum):
    """止损类型"""
    FIXED = "fixed"               # 固定止损
    TRAILING = "trailing"         # 移动止损
    ATR_BASED = "atr_based"      # ATR止损
    VOLATILITY = "volatility"     # 波动率止损
    TIME_BASED = "time_based"    # 时间止损
    SUPPORT = "support"           # 支撑位止损


@dataclass
class StopLossRule:
    """止损规则"""
    rule_id: str
    stop_loss_type: StopLossType
    trigger_threshold: float      # 触发阈值
    action: str                   # 'sell_all', 'sell_partial', 'alert'
    partial_ratio: float = 1.0    # 部分卖出比例
    cooldown_hours: int = 24      # 冷却时间
    enabled: bool = True


@dataclass
class StopLossOrder:
    """止损订单"""
    order_id: str
    bond_code: str
    stop_price: float
    current_price: float
    quantity: float
    rule: StopLossRule
    created_at: datetime
    triggered: bool = False
    triggered_at: Optional[datetime] = None


@dataclass
class Position:
    """持仓"""
    bond_code: str
    quantity: float
    avg_cost: float
    current_price: float
    highest_price: float  # 持仓期间最高价
    lowest_price: float   # 持仓期间最低价
    entry_time: datetime
    atr: float = 0
    support_level: float = 0


class StopLossManager:
    """止损管理器"""
    
    def __init__(self):
        self.positions: Dict[str, Position] = {}
        self.rules: List[StopLossRule] = []
        self.stop_orders: Dict[str, StopLossOrder] = {}
        self.trigger_history: List[Dict] = []
        
        # 回调函数
        self.on_trigger_callbacks: List[Callable] = []
        
        # 初始化默认规则
        self._init_default_rules()
    
    def _init_default_rules(self):
        """初始化默认止损规则"""
        default_rules = [
            StopLossRule(
                rule_id="fixed_5pct",
                stop_loss_type=StopLossType.FIXED,
                trigger_threshold=-0.05,  # 亏损5%
                action="sell_all"
            ),
            StopLossRule(
                rule_id="trailing_3pct",
                stop_loss_type=StopLossType.TRAILING,
                trigger_threshold=-0.03,  # 从最高点回撤3%
                action="sell_all"
            ),
            StopLossRule(
                rule_id="atr_2x",
                stop_loss_type=StopLossType.ATR_BASED,
                trigger_threshold=-2.0,    # 2倍ATR
                action="sell_all"
            ),
            StopLossRule(
                rule_id="volatility_adjusted",
                stop_loss_type=StopLossType.VOLATILITY,
                trigger_threshold=-2.5,    # 2.5倍波动率
                action="sell_all"
            ),
            StopLossRule(
                rule_id="time_5d",
                stop_loss_type=StopLossType.TIME_BASED,
                trigger_threshold=5,       # 5天
                action="alert"
            ),
        ]
        
        self.rules = default_rules
    
    def add_position(
        self, 
        bond_code: str, 
        quantity: float, 
        avg_cost: float,
        atr: float = 0,
        support_level: float = 0
    ):
        """添加持仓"""
        position = Position(
            bond_code=bond_code,
            quantity=quantity,
            avg_cost=avg_cost,
            current_price=avg_cost,
            highest_price=avg_cost,
            lowest_price=avg_cost,
            entry_time=datetime.now(),
            atr=atr,
            support_level=support_level
        )
        
        self.positions[bond_code] = position
        
        # 为该持仓创建止损订单
        self._create_stop_orders(position)
    
    def update_position(
        self, 
        bond_code: str, 
        current_price: float,
        atr: float = None
    ) -> List[StopLossOrder]:
        """更新持仓价格"""
        if bond_code not in self.positions:
            return []
        
        position = self.positions[bond_code]
        position.current_price = current_price
        position.highest_price = max(position.highest_price, current_price)
        position.lowest_price = min(position.lowest_price, current_price)
        
        if atr is not None:
            position.atr = atr
        
        # 检查止损触发
        triggered_orders = self._check_stop_triggers(position)
        
        return triggered_orders
    
    def remove_position(self, bond_code: str):
        """移除持仓"""
        if bond_code in self.positions:
            del self.positions[bond_code]
        
        # 移除相关止损订单
        order_ids = [oid for oid, order in self.stop_orders.items() 
                    if order.bond_code == bond_code]
        for oid in order_ids:
            del self.stop_orders[oid]
    
    def _create_stop_orders(self, position: Position):
        """创建止损订单"""
        for rule in self.rules:
            if not rule.enabled:
                continue
            
            stop_price = self._calculate_stop_price(position, rule)
            
            order = StopLossOrder(
                order_id=f"{position.bond_code}_{rule.rule_id}",
                bond_code=position.bond_code,
                stop_price=stop_price,
                current_price=position.current_price,
                quantity=position.quantity * rule.partial_ratio,
                rule=rule,
                created_at=datetime.now()
            )
            
            self.stop_orders[order.order_id] = order
    
    def _calculate_stop_price(self, position: Position, rule: StopLossRule) -> float:
        """计算止损价格"""
        if rule.stop_loss_type == StopLossType.FIXED:
            return position.avg_cost * (1 + rule.trigger_threshold)
        
        elif rule.stop_loss_type == StopLossType.TRAILING:
            return position.highest_price * (1 + rule.trigger_threshold)
        
        elif rule.stop_loss_type == StopLossType.ATR_BASED:
            if position.atr > 0:
                return position.avg_cost - abs(rule.trigger_threshold) * position.atr
            return position.avg_cost * 0.95
        
        elif rule.stop_loss_type == StopLossType.VOLATILITY:
            # 使用波动率计算
            return position.avg_cost * (1 + rule.trigger_threshold * 0.02)
        
        elif rule.stop_loss_type == StopLossType.SUPPORT:
            if position.support_level > 0:
                return position.support_level * 0.98  # 支撑位下方2%
            return position.lowest_price * 0.98
        
        return position.avg_cost * 0.95
    
    def _check_stop_triggers(self, position: Position) -> List[StopLossOrder]:
        """检查止损触发"""
        triggered = []
        
        for order_id, order in self.stop_orders.items():
            if order.bond_code != position.bond_code or order.triggered:
                continue
            
            # 更新止损价（对于移动止损）
            if order.rule.stop_loss_type == StopLossType.TRAILING:
                new_stop = position.highest_price * (1 + order.rule.trigger_threshold)
                order.stop_price = max(order.stop_price, new_stop)
            
            # 检查是否触发
            should_trigger = False
            
            if order.rule.stop_loss_type == StopLossType.TIME_BASED:
                # 时间止损
                days_held = (datetime.now() - position.entry_time).days
                if days_held >= order.rule.trigger_threshold:
                    should_trigger = True
            else:
                # 价格止损
                if position.current_price <= order.stop_price:
                    should_trigger = True
            
            if should_trigger:
                order.triggered = True
                order.triggered_at = datetime.now()
                triggered.append(order)
                
                # 记录历史
                self.trigger_history.append({
                    'order_id': order.order_id,
                    'bond_code': order.bond_code,
                    'trigger_price': position.current_price,
                    'stop_price': order.stop_price,
                    'rule_type': order.rule.stop_loss_type.value,
                    'triggered_at': order.triggered_at.isoformat()
                })
                
                # 触发回调
                for callback in self.on_trigger_callbacks:
                    try:
                        callback(order)
                    except Exception as e:
                        logger.debug(f"Suppressed: {e}")
                        pass
        
        return triggered
    
    def add_trigger_callback(self, callback: Callable):
        """添加触发回调"""
        self.on_trigger_callbacks.append(callback)
    
    def add_rule(self, rule: StopLossRule):
        """添加止损规则"""
        self.rules.append(rule)
    
    def remove_rule(self, rule_id: str):
        """移除止损规则"""
        self.rules = [r for r in self.rules if r.rule_id != rule_id]
    
    def get_stop_orders(self, bond_code: str = None) -> List[StopLossOrder]:
        """获取止损订单"""
        orders = list(self.stop_orders.values())
        
        if bond_code:
            orders = [o for o in orders if o.bond_code == bond_code]
        
        return orders
    
    def get_trigger_history(self, days: int = 30) -> List[Dict]:
        """获取触发历史"""
        cutoff = datetime.now() - timedelta(days=days)
        return [h for h in self.trigger_history 
                if datetime.fromisoformat(h['triggered_at']) > cutoff]
    
    def calculate_risk_per_trade(
        self, 
        entry_price: float,
        position_size: float,
        stop_loss_pct: float = 0.05
    ) -> Dict:
        """计算单笔交易风险"""
        stop_price = entry_price * (1 - stop_loss_pct)
        max_loss = (entry_price - stop_price) * position_size
        loss_per_share = entry_price - stop_price
        
        return {
            'entry_price': entry_price,
            'stop_price': stop_price,
            'stop_loss_pct': stop_loss_pct,
            'position_size': position_size,
            'max_loss': max_loss,
            'loss_per_share': loss_per_share
        }
    
    def suggest_position_size(
        self,
        portfolio_value: float,
        entry_price: float,
        stop_loss_pct: float = 0.05,
        max_risk_pct: float = 0.02
    ) -> Dict:
        """建议仓位大小"""
        max_risk_amount = portfolio_value * max_risk_pct
        stop_price = entry_price * (1 - stop_loss_pct)
        loss_per_share = entry_price - stop_price
        
        suggested_shares = max_risk_amount / loss_per_share if loss_per_share > 0 else 0
        suggested_value = suggested_shares * entry_price
        
        return {
            'suggested_shares': suggested_shares,
            'suggested_value': suggested_value,
            'max_risk_amount': max_risk_amount,
            'position_pct': suggested_value / portfolio_value
        }
