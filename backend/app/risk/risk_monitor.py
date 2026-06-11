"""实时风险监控仪表盘"""
import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import asyncio


@dataclass
class RiskMetrics:
    """风险指标"""
    # 组合级别
    portfolio_value: float
    portfolio_return: float
    portfolio_volatility: float
    
    # 风险价值
    var_95: float
    var_99: float
    cvar_95: float  # 条件VaR
    
    # 回撤
    max_drawdown: float
    current_drawdown: float
    drawdown_duration: int
    
    # 敞口
    gross_exposure: float
    net_exposure: float
    concentration: float
    
    # 希腊字母
    delta: float
    gamma: float
    vega: float
    theta: float
    
    # 流动性
    liquidity_score: float
    avg_bid_ask_spread: float
    
    # 压力测试
    stress_loss_1sigma: float
    stress_loss_2sigma: float
    
    # 夏普相关
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    
    # 时间戳
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class RiskAlert:
    """风险警报"""
    alert_id: str
    alert_type: str
    severity: str  # 'low', 'medium', 'high', 'critical'
    message: str
    metric_value: float
    threshold: float
    timestamp: datetime
    acknowledged: bool = False


class RiskMonitor:
    """实时风险监控"""
    
    def __init__(
        self,
        lookback_days: int = 252,
        risk_free_rate: float = 0.03,
        alert_thresholds: Dict = None
    ):
        self.lookback_days = lookback_days
        self.risk_free_rate = risk_free_rate
        
        # 默认阈值
        self.alert_thresholds = alert_thresholds or {
            'max_drawdown': 0.10,
            'var_95': 0.05,
            'concentration': 0.30,
            'liquidity_score': 0.5,
            'volatility': 0.30,
            'leverage': 2.0,
            'beta': 1.5
        }
        
        # 历史数据
        self.returns_history = deque(maxlen=lookback_days)
        self.values_history = deque(maxlen=lookback_days)
        self.positions_history = deque(maxlen=lookback_days)
        
        # 警报
        self.alerts: List[RiskAlert] = []
        self.alert_callbacks: List[callable] = []
    
    def update(self, portfolio_value: float, positions: Dict[str, float], 
               market_data: Dict[str, Dict]):
        """更新风险指标"""
        # 记录历史
        self.values_history.append({
            'value': portfolio_value,
            'timestamp': datetime.now()
        })
        
        if len(self.values_history) > 1:
            prev_value = self.values_history[-2]['value']
            daily_return = (portfolio_value - prev_value) / prev_value
            self.returns_history.append(daily_return)
        
        self.positions_history.append(positions.copy())
        
        # 计算风险指标
        metrics = self._calculate_metrics(portfolio_value, positions, market_data)
        
        # 检查阈值
        self._check_thresholds(metrics)
        
        return metrics
    
    def _calculate_metrics(
        self, 
        portfolio_value: float, 
        positions: Dict[str, float],
        market_data: Dict[str, Dict]
    ) -> RiskMetrics:
        """计算风险指标"""
        returns = np.array(list(self.returns_history))
        values = [v['value'] for v in self.values_history]
        
        # 组合收益和波动率
        if len(returns) > 1:
            portfolio_return = returns[-1]
            portfolio_volatility = np.std(returns) * np.sqrt(252)
        else:
            portfolio_return = 0
            portfolio_volatility = 0
        
        # VaR计算
        if len(returns) > 20:
            var_95 = np.percentile(returns, 5) * portfolio_value
            var_99 = np.percentile(returns, 1) * portfolio_value
            # CVaR
            cvar_95 = np.mean(returns[returns <= np.percentile(returns, 5)]) * portfolio_value
        else:
            var_95 = var_99 = cvar_95 = 0
        
        # 回撤计算
        if values:
            peak = max(values)
            current_drawdown = (peak - portfolio_value) / peak if peak > 0 else 0
            
            # 最大回撤
            cummax = np.maximum.accumulate(values)
            drawdowns = (cummax - values) / cummax
            max_drawdown = np.max(drawdowns) if len(drawdowns) > 0 else 0
            
            # 回撤持续时间
            if current_drawdown > 0:
                drawdown_duration = sum(1 for v in values[-30:] if v < peak * 0.99)
            else:
                drawdown_duration = 0
        else:
            max_drawdown = current_drawdown = drawdown_duration = 0
        
        # 敞口计算
        gross_exposure = sum(abs(v) for v in positions.values()) / portfolio_value
        net_exposure = sum(positions.values()) / portfolio_value
        
        # 集中度
        position_values = list(positions.values())
        if position_values:
            concentration = max(position_values) / sum(position_values) if sum(position_values) > 0 else 0
        else:
            concentration = 0
        
        # 希腊字母（简化计算）
        delta, gamma, vega, theta = self._calculate_greeks(positions, market_data)
        
        # 流动性评分
        liquidity_score, avg_spread = self._calculate_liquidity(positions, market_data)
        
        # 压力测试
        stress_1sigma, stress_2sigma = self._stress_test(portfolio_value, returns)
        
        # 夏普比率
        if len(returns) > 30:
            excess_return = np.mean(returns) * 252 - self.risk_free_rate
            sharpe_ratio = excess_return / portfolio_volatility if portfolio_volatility > 0 else 0
            
            # Sortino比率
            downside_returns = returns[returns < 0]
            downside_std = np.std(downside_returns) * np.sqrt(252) if len(downside_returns) > 0 else 0
            sortino_ratio = excess_return / downside_std if downside_std > 0 else 0
            
            # Calmar比率
            calmar_ratio = (np.mean(returns) * 252) / max_drawdown if max_drawdown > 0 else 0
        else:
            sharpe_ratio = sortino_ratio = calmar_ratio = 0
        
        return RiskMetrics(
            portfolio_value=portfolio_value,
            portfolio_return=portfolio_return,
            portfolio_volatility=portfolio_volatility,
            var_95=var_95,
            var_99=var_99,
            cvar_95=cvar_95,
            max_drawdown=max_drawdown,
            current_drawdown=current_drawdown,
            drawdown_duration=drawdown_duration,
            gross_exposure=gross_exposure,
            net_exposure=net_exposure,
            concentration=concentration,
            delta=delta,
            gamma=gamma,
            vega=vega,
            theta=theta,
            liquidity_score=liquidity_score,
            avg_bid_ask_spread=avg_spread,
            stress_loss_1sigma=stress_1sigma,
            stress_loss_2sigma=stress_2sigma,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            calmar_ratio=calmar_ratio
        )
    
    def _calculate_greeks(
        self, 
        positions: Dict[str, float],
        market_data: Dict[str, Dict]
    ) -> tuple:
        """计算希腊字母"""
        total_delta = 0
        total_gamma = 0
        total_vega = 0
        total_theta = 0
        
        for bond_code, quantity in positions.items():
            if bond_code in market_data:
                data = market_data[bond_code]
                total_delta += quantity * data.get('delta', 0)
                total_gamma += quantity * data.get('gamma', 0)
                total_vega += quantity * data.get('vega', 0)
                total_theta += quantity * data.get('theta', 0)
        
        return total_delta, total_gamma, total_vega, total_theta
    
    def _calculate_liquidity(
        self, 
        positions: Dict[str, float],
        market_data: Dict[str, Dict]
    ) -> tuple:
        """计算流动性"""
        if not positions:
            return 1.0, 0.0
        
        spreads = []
        for bond_code, quantity in positions.items():
            if bond_code in market_data:
                data = market_data[bond_code]
                bid = data.get('bid', data.get('close', 100))
                ask = data.get('ask', data.get('close', 100))
                mid = (bid + ask) / 2
                if mid > 0:
                    spread = (ask - bid) / mid
                    spreads.append(spread)
        
        avg_spread = np.mean(spreads) if spreads else 0
        liquidity_score = max(0, 1 - avg_spread * 100)  # 简化评分
        
        return liquidity_score, avg_spread
    
    def _stress_test(self, portfolio_value: float, returns: np.ndarray) -> tuple:
        """压力测试"""
        if len(returns) < 30:
            return 0, 0
        
        mean = np.mean(returns)
        std = np.std(returns)
        
        stress_1sigma = abs(mean - std) * portfolio_value
        stress_2sigma = abs(mean - 2 * std) * portfolio_value
        
        return stress_1sigma, stress_2sigma
    
    def _check_thresholds(self, metrics: RiskMetrics):
        """检查阈值"""
        # 最大回撤检查
        if metrics.max_drawdown > self.alert_thresholds['max_drawdown']:
            self._create_alert(
                alert_type='max_drawdown',
                severity='high',
                message=f'最大回撤 {metrics.max_drawdown:.2%} 超过阈值 {self.alert_thresholds["max_drawdown"]:.2%}',
                metric_value=metrics.max_drawdown,
                threshold=self.alert_thresholds['max_drawdown']
            )
        
        # VaR检查
        if abs(metrics.var_95 / metrics.portfolio_value) > self.alert_thresholds['var_95']:
            self._create_alert(
                alert_type='var_95',
                severity='medium',
                message=f'VaR(95%) {abs(metrics.var_95):.2f} 占比过高',
                metric_value=abs(metrics.var_95 / metrics.portfolio_value),
                threshold=self.alert_thresholds['var_95']
            )
        
        # 集中度检查
        if metrics.concentration > self.alert_thresholds['concentration']:
            self._create_alert(
                alert_type='concentration',
                severity='medium',
                message=f'持仓集中度 {metrics.concentration:.2%} 过高',
                metric_value=metrics.concentration,
                threshold=self.alert_thresholds['concentration']
            )
        
        # 流动性检查
        if metrics.liquidity_score < self.alert_thresholds['liquidity_score']:
            self._create_alert(
                alert_type='liquidity',
                severity='high',
                message=f'流动性评分 {metrics.liquidity_score:.2f} 过低',
                metric_value=metrics.liquidity_score,
                threshold=self.alert_thresholds['liquidity_score']
            )
    
    def _create_alert(
        self, 
        alert_type: str, 
        severity: str, 
        message: str,
        metric_value: float,
        threshold: float
    ):
        """创建警报"""
        alert = RiskAlert(
            alert_id=f"{alert_type}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            alert_type=alert_type,
            severity=severity,
            message=message,
            metric_value=metric_value,
            threshold=threshold,
            timestamp=datetime.now()
        )
        
        self.alerts.append(alert)
        
        # 触发回调
        for callback in self.alert_callbacks:
            try:
                callback(alert)
            except Exception:
                pass
    
    def add_alert_callback(self, callback: callable):
        """添加警报回调"""
        self.alert_callbacks.append(callback)
    
    def get_active_alerts(self, severity: str = None) -> List[RiskAlert]:
        """获取活跃警报"""
        alerts = [a for a in self.alerts if not a.acknowledged]
        
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        
        return alerts
    
    def acknowledge_alert(self, alert_id: str):
        """确认警报"""
        for alert in self.alerts:
            if alert.alert_id == alert_id:
                alert.acknowledged = True
                break
    
    def get_risk_report(self) -> Dict:
        """生成风险报告"""
        if not self.values_history:
            return {}
        
        latest_metrics = self._calculate_metrics(
            self.values_history[-1]['value'],
            self.positions_history[-1] if self.positions_history else {},
            {}
        )
        
        return {
            'summary': {
                'portfolio_value': latest_metrics.portfolio_value,
                'daily_return': latest_metrics.portfolio_return,
                'ytd_return': np.sum(list(self.returns_history)) if self.returns_history else 0,
                'volatility': latest_metrics.portfolio_volatility,
            },
            'risk': {
                'var_95': latest_metrics.var_95,
                'max_drawdown': latest_metrics.max_drawdown,
                'sharpe_ratio': latest_metrics.sharpe_ratio,
                'concentration': latest_metrics.concentration,
            },
            'alerts': len(self.get_active_alerts()),
            'timestamp': datetime.now().isoformat()
        }
