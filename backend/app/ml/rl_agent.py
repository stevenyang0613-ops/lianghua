"""强化学习策略优化"""
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from collections import deque
import random

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


@dataclass
class TradingState:
    """交易状态"""
    portfolio_value: float
    cash: float
    positions: Dict[str, float]  # bond_code -> quantity
    market_data: Dict[str, np.ndarray]  # 债券市场数据
    risk_metrics: Dict[str, float]


@dataclass
class TradingAction:
    """交易动作"""
    bond_code: str
    action_type: str  # 'buy', 'sell', 'hold'
    quantity: float
    price: float


class TradingEnvironment:
    """交易环境"""
    
    def __init__(self, data: pd.DataFrame, initial_cash: float = 1000000):
        self.data = data
        self.initial_cash = initial_cash
        self.reset()
    
    def reset(self) -> TradingState:
        """重置环境"""
        self.current_step = 0
        self.cash = self.initial_cash
        self.positions = {}
        self.portfolio_value = self.initial_cash
        self.history = []
        
        return self._get_state()
    
    def _get_state(self) -> TradingState:
        """获取当前状态"""
        current_data = self.data.iloc[self.current_step]
        
        return TradingState(
            portfolio_value=self.portfolio_value,
            cash=self.cash,
            positions=self.positions.copy(),
            market_data={'bond': current_data.values},
            risk_metrics=self._calculate_risk_metrics()
        )
    
    def _calculate_risk_metrics(self) -> Dict[str, float]:
        """计算风险指标"""
        if not self.history:
            return {'volatility': 0, 'drawdown': 0, 'sharpe': 0}
        
        returns = [h['return'] for h in self.history[-20:]]
        volatility = np.std(returns) if len(returns) > 1 else 0
        
        # 最大回撤
        values = [h['portfolio_value'] for h in self.history]
        peak = max(values)
        drawdown = (peak - self.portfolio_value) / peak if peak > 0 else 0
        
        # 夏普比率
        avg_return = np.mean(returns) if returns else 0
        sharpe = avg_return / volatility if volatility > 0 else 0
        
        return {
            'volatility': volatility,
            'drawdown': drawdown,
            'sharpe': sharpe
        }
    
    def step(self, action: TradingAction) -> Tuple[TradingState, float, bool, Dict]:
        """执行动作"""
        current_data = self.data.iloc[self.current_step]
        price = current_data.get('close')
        if price is None or (isinstance(price, float) and np.isnan(price)):
            # 价格缺失时不使用硬编码100，跳过交易并推进步数
            self.current_step += 1
            done = self.current_step >= len(self.data) - 1
            return self._get_state(), 0.0, done, {'return': 0.0}
        price = float(price)
        
        # 执行交易
        if action.action_type == 'buy':
            cost = action.quantity * price
            if cost <= self.cash:
                self.cash -= cost
                self.positions[action.bond_code] = self.positions.get(action.bond_code, 0) + action.quantity
        
        elif action.action_type == 'sell':
            if action.bond_code in self.positions:
                sell_qty = min(action.quantity, self.positions[action.bond_code])
                self.cash += sell_qty * price
                self.positions[action.bond_code] -= sell_qty
                if self.positions[action.bond_code] <= 0:
                    del self.positions[action.bond_code]
        
        # 计算新的组合价值
        prev_value = self.portfolio_value
        self.portfolio_value = self.cash
        for bond, qty in self.positions.items():
            bond_price = current_data.get('close')
            if bond_price is not None and not (isinstance(bond_price, float) and np.isnan(bond_price)):
                self.portfolio_value += qty * float(bond_price)
        
        # 计算奖励
        portfolio_return = (self.portfolio_value - prev_value) / prev_value
        reward = self._calculate_reward(portfolio_return)
        
        # 记录历史
        self.history.append({
            'step': self.current_step,
            'portfolio_value': self.portfolio_value,
            'return': portfolio_return,
            'action': action
        })
        
        # 移动到下一步
        self.current_step += 1
        done = self.current_step >= len(self.data) - 1
        
        return self._get_state(), reward, done, {'return': portfolio_return}
    
    def _calculate_reward(self, portfolio_return: float) -> float:
        """计算奖励"""
        risk_metrics = self._calculate_risk_metrics()
        
        # 风险调整收益
        risk_penalty = risk_metrics['drawdown'] * 0.5
        volatility_penalty = risk_metrics['volatility'] * 0.1
        
        reward = portfolio_return - risk_penalty - volatility_penalty
        
        return reward


class DQNAgent:
    """DQN智能体"""
    
    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        hidden_dim: int = 128,
        lr: float = 1e-3,
        gamma: float = 0.99,
        epsilon: float = 1.0,
        epsilon_min: float = 0.01,
        epsilon_decay: float = 0.995,
        buffer_size: int = 10000,
        batch_size: int = 64
    ):
        if not TORCH_AVAILABLE:
            raise ImportError("需要安装PyTorch")
        
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.batch_size = batch_size
        
        # 经验回放
        self.memory = deque(maxlen=buffer_size)
        
        # 神经网络
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.q_network = self._build_network(hidden_dim).to(self.device)
        self.target_network = self._build_network(hidden_dim).to(self.device)
        self.target_network.load_state_dict(self.q_network.state_dict())
        
        self.optimizer = optim.Adam(self.q_network.parameters(), lr=lr)
    
    def _build_network(self, hidden_dim: int) -> nn.Module:
        """构建神经网络"""
        return nn.Sequential(
            nn.Linear(self.state_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, self.action_dim)
        )
    
    def remember(self, state, action, reward, next_state, done):
        """存储经验"""
        self.memory.append((state, action, reward, next_state, done))
    
    def act(self, state: np.ndarray, training: bool = True) -> int:
        """选择动作"""
        if training and random.random() < self.epsilon:
            return random.randrange(self.action_dim)
        
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
            q_values = self.q_network(state_tensor)
            return q_values.argmax().item()
    
    def replay(self):
        """经验回放训练"""
        if len(self.memory) < self.batch_size:
            return
        
        # 采样
        batch = random.sample(self.memory, self.batch_size)
        states, actions, rewards, next_states, dones = zip(*batch)
        
        states = torch.FloatTensor(np.array(states)).to(self.device)
        actions = torch.LongTensor(actions).to(self.device)
        rewards = torch.FloatTensor(rewards).to(self.device)
        next_states = torch.FloatTensor(np.array(next_states)).to(self.device)
        dones = torch.FloatTensor(dones).to(self.device)
        
        # 计算Q值
        current_q = self.q_network(states).gather(1, actions.unsqueeze(1))
        with torch.no_grad():
            next_q = self.target_network(next_states).max(1)[0]
            target_q = rewards + (1 - dones) * self.gamma * next_q
        
        # 计算损失
        loss = nn.MSELoss()(current_q.squeeze(), target_q)
        
        # 反向传播
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        
        # 衰减epsilon
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
    
    def update_target(self):
        """更新目标网络"""
        self.target_network.load_state_dict(self.q_network.state_dict())


class PPOAgent:
    """PPO智能体"""
    
    def __init__(
        self,
        state_dim: int,
        action_dim: int,
        hidden_dim: int = 64,
        lr: float = 3e-4,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        clip_epsilon: float = 0.2,
        entropy_coef: float = 0.01
    ):
        if not TORCH_AVAILABLE:
            raise ImportError("需要安装PyTorch")
        
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.gamma = gamma
        self.gae_lambda = gae_lambda
        self.clip_epsilon = clip_epsilon
        self.entropy_coef = entropy_coef
        
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        # Actor-Critic网络
        self.actor = self._build_actor(hidden_dim).to(self.device)
        self.critic = self._build_critic(hidden_dim).to(self.device)
        
        self.actor_optimizer = optim.Adam(self.actor.parameters(), lr=lr)
        self.critic_optimizer = optim.Adam(self.critic.parameters(), lr=lr)
    
    def _build_actor(self, hidden_dim: int) -> nn.Module:
        """构建Actor网络"""
        return nn.Sequential(
            nn.Linear(self.state_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, self.action_dim),
            nn.Softmax(dim=-1)
        )
    
    def _build_critic(self, hidden_dim: int) -> nn.Module:
        """构建Critic网络"""
        return nn.Sequential(
            nn.Linear(self.state_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, 1)
        )
    
    def act(self, state: np.ndarray) -> Tuple[int, float]:
        """选择动作"""
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
            probs = self.actor(state_tensor)
            value = self.critic(state_tensor)
            
            dist = torch.distributions.Categorical(probs)
            action = dist.sample()
            log_prob = dist.log_prob(action)
            
            return action.item(), log_prob.item()
    
    def update(self, trajectories: List[Dict]):
        """更新策略"""
        # 实现PPO更新逻辑
        pass
