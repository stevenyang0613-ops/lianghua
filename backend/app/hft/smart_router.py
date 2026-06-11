"""智能订单路由"""
import time
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from collections import defaultdict


class Venue(Enum):
    """交易所"""
    SSE = "sse"      # 上交所
    SZSE = "szse"    # 深交所
    SHFE = "shfe"    # 上期所
    DCE = "dce"      # 大商所
    CZCE = "czce"    # 郑商所
    CFFEX = "cffex"  # 中金所


@dataclass
class MarketDepth:
    """市场深度"""
    venue: Venue
    symbol: str
    timestamp: datetime
    
    bids: List[Tuple[float, float]]  # [(price, quantity), ...]
    asks: List[Tuple[float, float]]
    
    bid_volumes: float = 0.0
    ask_volumes: float = 0.0
    
    spread: float = 0.0
    mid_price: float = 0.0
    
    def __post_init__(self):
        if self.bids and self.asks:
            self.spread = self.asks[0][0] - self.bids[0][0]
            self.mid_price = (self.bids[0][0] + self.asks[0][0]) / 2
            self.bid_volumes = sum(v for _, v in self.bids[:5])
            self.ask_volumes = sum(v for _, v in self.asks[:5])


@dataclass
class VenueStats:
    """交易所统计"""
    venue: Venue
    avg_latency_us: float
    fill_rate: float
    avg_spread: float
    volume_share: float
    reliability: float


@dataclass
class RoutingDecision:
    """路由决策"""
    order_id: str
    symbol: str
    venues: List[Tuple[Venue, float]]  # [(交易所, 分配比例), ...]
    expected_price: float
    expected_slippage: float
    expected_latency_us: float
    confidence: float
    reasoning: str


class SmartOrderRouter:
    """智能订单路由器"""
    
    def __init__(self):
        # 交易所状态
        self.venue_stats: Dict[Venue, VenueStats] = {}
        self.market_data: Dict[str, Dict[Venue, MarketDepth]] = defaultdict(dict)
        
        # 路由历史
        self.routing_history: List[RoutingDecision] = []
        
        # 路由策略
        self.strategy = 'smart'  # 'smart', 'best_price', 'fastest', 'balanced'
        
        # 初始化交易所统计
        self._init_venue_stats()
    
    def _init_venue_stats(self):
        """初始化交易所统计"""
        default_stats = {
            Venue.SSE: VenueStats(Venue.SSE, 50, 0.98, 0.001, 0.6, 0.999),
            Venue.SZSE: VenueStats(Venue.SZSE, 60, 0.97, 0.001, 0.4, 0.998),
        }
        
        self.venue_stats = default_stats
    
    def update_market_data(self, venue: Venue, depth: MarketDepth):
        """更新市场数据"""
        self.market_data[depth.symbol][venue] = depth
    
    def route(
        self,
        symbol: str,
        side: str,
        quantity: float,
        urgency: str = 'normal'
    ) -> RoutingDecision:
        """路由决策"""
        available_venues = self.market_data.get(symbol, {})
        
        if not available_venues:
            # 默认路由
            return RoutingDecision(
                order_id=f"route_{int(time.time() * 1000000)}",
                symbol=symbol,
                venues=[(Venue.SSE, 1.0)],
                expected_price=0,
                expected_slippage=0,
                expected_latency_us=100,
                confidence=0.5,
                reasoning="无市场数据，使用默认路由"
            )
        
        # 根据策略选择路由
        if self.strategy == 'best_price':
            decision = self._route_best_price(symbol, side, quantity, available_venues)
        elif self.strategy == 'fastest':
            decision = self._route_fastest(symbol, side, quantity, available_venues)
        elif self.strategy == 'balanced':
            decision = self._route_balanced(symbol, side, quantity, available_venues)
        else:
            decision = self._route_smart(symbol, side, quantity, available_venues, urgency)
        
        self.routing_history.append(decision)
        
        return decision
    
    def _route_best_price(
        self,
        symbol: str,
        side: str,
        quantity: float,
        venues: Dict[Venue, MarketDepth]
    ) -> RoutingDecision:
        """最优价格路由"""
        best_venue = None
        best_price = None
        
        for venue, depth in venues.items():
            if side == 'buy':
                price = depth.asks[0][0] if depth.asks else float('inf')
            else:
                price = depth.bids[0][0] if depth.bids else 0
            
            if best_price is None or (side == 'buy' and price < best_price) or (side == 'sell' and price > best_price):
                best_price = price
                best_venue = venue
        
        return RoutingDecision(
            order_id=f"route_{int(time.time() * 1000000)}",
            symbol=symbol,
            venues=[(best_venue, 1.0)],
            expected_price=best_price,
            expected_slippage=0,
            expected_latency_us=self.venue_stats[best_venue].avg_latency_us,
            confidence=0.9,
            reasoning="选择最优价格交易所"
        )
    
    def _route_fastest(
        self,
        symbol: str,
        side: str,
        quantity: float,
        venues: Dict[Venue, MarketDepth]
    ) -> RoutingDecision:
        """最快路由"""
        fastest_venue = min(venues.keys(), key=lambda v: self.venue_stats[v].avg_latency_us)
        
        depth = venues[fastest_venue]
        price = depth.asks[0][0] if side == 'buy' and depth.asks else (depth.bids[0][0] if depth.bids else 0)
        
        return RoutingDecision(
            order_id=f"route_{int(time.time() * 1000000)}",
            symbol=symbol,
            venues=[(fastest_venue, 1.0)],
            expected_price=price,
            expected_slippage=depth.spread / 2,
            expected_latency_us=self.venue_stats[fastest_venue].avg_latency_us,
            confidence=0.85,
            reasoning="选择最低延迟交易所"
        )
    
    def _route_balanced(
        self,
        symbol: str,
        side: str,
        quantity: float,
        venues: Dict[Venue, MarketDepth]
    ) -> RoutingDecision:
        """平衡路由"""
        scores = {}
        
        for venue, depth in venues.items():
            stats = self.venue_stats[venue]
            
            # 综合评分
            latency_score = 1 - stats.avg_latency_us / 1000
            fill_score = stats.fill_rate
            reliability_score = stats.reliability
            spread_score = 1 - depth.spread / depth.mid_price if depth.mid_price > 0 else 0
            
            # 加权综合
            scores[venue] = (
                latency_score * 0.3 +
                fill_score * 0.3 +
                reliability_score * 0.2 +
                spread_score * 0.2
            )
        
        # 选择得分最高的交易所
        best_venue = max(scores.keys(), key=lambda v: scores[v])
        
        depth = venues[best_venue]
        price = depth.asks[0][0] if side == 'buy' and depth.asks else (depth.bids[0][0] if depth.bids else 0)
        
        return RoutingDecision(
            order_id=f"route_{int(time.time() * 1000000)}",
            symbol=symbol,
            venues=[(best_venue, 1.0)],
            expected_price=price,
            expected_slippage=depth.spread / 2,
            expected_latency_us=self.venue_stats[best_venue].avg_latency_us,
            confidence=scores[best_venue],
            reasoning="综合评分最优交易所"
        )
    
    def _route_smart(
        self,
        symbol: str,
        side: str,
        quantity: float,
        venues: Dict[Venue, MarketDepth],
        urgency: str
    ) -> RoutingDecision:
        """智能路由"""
        # 计算每个交易所的分配比例
        allocations = {}
        total_score = 0
        
        urgency_weights = {
            'high': {'latency': 0.5, 'price': 0.3, 'fill': 0.2},
            'normal': {'latency': 0.3, 'price': 0.4, 'fill': 0.3},
            'low': {'latency': 0.1, 'price': 0.5, 'fill': 0.4},
        }
        
        weights = urgency_weights.get(urgency, urgency_weights['normal'])
        
        for venue, depth in venues.items():
            stats = self.venue_stats[venue]
            
            # 可用流动性
            available_volume = depth.ask_volumes if side == 'buy' else depth.bid_volumes
            liquidity_score = min(available_volume / quantity, 1.0) if quantity > 0 else 0
            
            # 价格优势
            if side == 'buy':
                price_score = 1 - (depth.asks[0][0] / depth.mid_price - 1) if depth.asks else 0
            else:
                price_score = 1 - (1 - depth.bids[0][0] / depth.mid_price) if depth.bids else 0
            
            # 综合得分
            score = (
                (1 - stats.avg_latency_us / 1000) * weights['latency'] +
                price_score * weights['price'] +
                stats.fill_rate * liquidity_score * weights['fill']
            )
            
            allocations[venue] = score
            total_score += score
        
        # 标准化分配比例
        if total_score > 0:
            for venue in allocations:
                allocations[venue] /= total_score
        
        # 按比例分配
        venue_list = [(v, s) for v, s in allocations.items() if s > 0.05]  # 过滤小比例
        
        # 计算预期价格和滑点
        expected_price = 0
        expected_slippage = 0
        expected_latency = 0
        
        for venue, ratio in venue_list:
            depth = venues[venue]
            stats = self.venue_stats[venue]
            
            price = depth.asks[0][0] if side == 'buy' and depth.asks else (depth.bids[0][0] if depth.bids else 0)
            expected_price += price * ratio
            expected_slippage += depth.spread / 2 * ratio
            expected_latency += stats.avg_latency_us * ratio
        
        reasoning = f"智能分配，紧急程度: {urgency}"
        if len(venue_list) > 1:
            reasoning += f"，分散到{len(venue_list)}个交易所"
        
        return RoutingDecision(
            order_id=f"route_{int(time.time() * 1000000)}",
            symbol=symbol,
            venues=venue_list,
            expected_price=expected_price,
            expected_slippage=expected_slippage,
            expected_latency_us=expected_latency,
            confidence=0.8,
            reasoning=reasoning
        )
    
    def split_large_order(
        self,
        symbol: str,
        side: str,
        total_quantity: float,
        max_slice_size: float = None,
        time_window_seconds: float = 60
    ) -> List[Dict]:
        """大单拆分"""
        slices = []
        
        # 计算最优切片大小
        depth = list(self.market_data.get(symbol, {}).values())
        if depth:
            avg_depth = np.mean([d.bid_volumes + d.ask_volumes for d in depth]) / 2
            max_slice_size = max_slice_size or min(avg_depth * 0.1, total_quantity / 10)
        else:
            max_slice_size = max_slice_size or total_quantity / 10
        
        remaining = total_quantity
        slice_interval = time_window_seconds / (total_quantity / max_slice_size)
        
        while remaining > 0:
            slice_qty = min(remaining, max_slice_size)
            
            # 决定切片大小（随机化以避免模式识别）
            if remaining > max_slice_size * 2:
                slice_qty *= (0.8 + 0.4 * np.random.random())
            
            slices.append({
                'symbol': symbol,
                'side': side,
                'quantity': slice_qty,
                'delay_seconds': len(slices) * slice_interval
            })
            
            remaining -= slice_qty
        
        return slices
    
    def execute_twap(
        self,
        symbol: str,
        side: str,
        total_quantity: float,
        duration_minutes: int = 30
    ) -> List[Dict]:
        """TWAP执行"""
        num_slices = duration_minutes
        slice_quantity = total_quantity / num_slices
        
        slices = []
        for i in range(num_slices):
            # 添加随机性
            qty_variation = slice_quantity * (0.95 + 0.1 * np.random.random())
            
            slices.append({
                'symbol': symbol,
                'side': side,
                'quantity': qty_variation,
                'delay_seconds': i * 60,
                'type': 'limit'
            })
        
        return slices
    
    def execute_vwap(
        self,
        symbol: str,
        side: str,
        total_quantity: float,
        volume_profile: List[float] = None
    ) -> List[Dict]:
        """VWAP执行"""
        if not volume_profile:
            # 默认成交量分布
            volume_profile = [0.05, 0.08, 0.12, 0.15, 0.18, 0.15, 0.12, 0.08, 0.05, 0.02]
        
        slices = []
        for i, volume_pct in enumerate(volume_profile):
            slices.append({
                'symbol': symbol,
                'side': side,
                'quantity': total_quantity * volume_pct,
                'delay_seconds': i * 3600 / len(volume_profile),
                'type': 'limit'
            })
        
        return slices
    
    def get_routing_stats(self) -> Dict:
        """获取路由统计"""
        if not self.routing_history:
            return {}
        
        venue_counts = defaultdict(int)
        for decision in self.routing_history:
            for venue, _ in decision.venues:
                venue_counts[venue.value] += 1
        
        avg_latency = np.mean([d.expected_latency_us for d in self.routing_history])
        avg_slippage = np.mean([d.expected_slippage for d in self.routing_history])
        
        return {
            'total_decisions': len(self.routing_history),
            'venue_distribution': dict(venue_counts),
            'avg_expected_latency_us': avg_latency,
            'avg_expected_slippage': avg_slippage,
        }
    
    def set_strategy(self, strategy: str):
        """设置路由策略"""
        self.strategy = strategy
