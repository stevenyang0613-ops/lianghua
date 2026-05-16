"""松岗量化可转债策略 V3.0 多策略支持模块

功能:
- 策略抽象基类
- 策略工厂
- 动态加载
- 策略组合
- 策略评估
"""
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Dict, Optional, Any, Callable, Type
from enum import Enum
import logging
import importlib
import inspect
import json
import os
from abc import ABC, abstractmethod

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class StrategyType(str, Enum):
    """策略类型"""
    CONVERTIBLE_BOND = "convertible_bond"   # 可转债策略
    STOCK = "stock"                         # 股票策略
    MIXED = "mixed"                         # 混合策略
    ARBITRAGE = "arbitrage"                 # 套利策略
    MARKET_NEUTRAL = "market_neutral"       # 市场中性


class StrategyStatus(str, Enum):
    """策略状态"""
    DRAFT = "draft"         # 草稿
    TESTING = "testing"     # 测试中
    ACTIVE = "active"       # 运行中
    PAUSED = "paused"       # 暂停
    ARCHIVED = "archived"   # 归档


class AllocationMethod(str, Enum):
    """配置方法"""
    EQUAL = "equal"             # 等权重
    RISK_PARITY = "risk_parity" # 风险平价
    CUSTOM = "custom"           # 自定义


# ============ 数据模型 ============

@dataclass
class StrategyConfig:
    """策略配置"""
    strategy_id: str
    name: str
    strategy_type: StrategyType
    description: str = ""
    version: str = "1.0.0"
    author: str = ""
    tags: List[str] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)

    # 约束
    max_position: int = 30
    max_single_weight: float = 0.05
    min_liquidity: float = 1000.0

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "strategy_type": self.strategy_type.value,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "tags": self.tags,
            "params": self.params,
        }


@dataclass
class StrategyResult:
    """策略结果"""
    strategy_id: str
    date: date
    signals: List[Dict] = field(default_factory=list)
    scores: Dict[str, float] = field(default_factory=dict)
    whitelist: List[str] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)
    execution_time: float = 0.0

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "date": self.date.isoformat(),
            "signals": self.signals,
            "scores": {k: round(v, 2) for k, v in self.scores.items()},
            "whitelist": self.whitelist,
            "metrics": {k: round(v, 4) for k, v in self.metrics.items()},
            "execution_time": round(self.execution_time, 3),
        }


# ============ 策略抽象基类 ============

class BaseStrategy(ABC):
    """策略抽象基类"""

    def __init__(self, config: StrategyConfig):
        self.config = config
        self._status = StrategyStatus.DRAFT
        self._last_run: Optional[datetime] = None
        self._run_count: int = 0

    @abstractmethod
    def initialize(self):
        """初始化策略"""
        pass

    @abstractmethod
    def on_data(self, data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        """处理数据"""
        pass

    @abstractmethod
    def generate_signals(self, context: Dict) -> List[Dict]:
        """生成信号"""
        pass

    def run(self, data: Dict[str, pd.DataFrame]) -> StrategyResult:
        """运行策略"""
        start_time = datetime.now()

        try:
            # 处理数据
            context = self.on_data(data)

            # 生成信号
            signals = self.generate_signals(context)

            # 更新状态
            self._last_run = datetime.now()
            self._run_count += 1

            execution_time = (datetime.now() - start_time).total_seconds()

            return StrategyResult(
                strategy_id=self.config.strategy_id,
                date=date.today(),
                signals=signals,
                scores=context.get("scores", {}),
                whitelist=context.get("whitelist", []),
                metrics=context.get("metrics", {}),
                execution_time=execution_time,
            )

        except Exception as e:
            logger.error(f"[Strategy:{self.config.name}] 运行失败: {e}")
            raise

    def get_status(self) -> StrategyStatus:
        """获取状态"""
        return self._status

    def set_status(self, status: StrategyStatus):
        """设置状态"""
        self._status = status
        logger.info(f"[Strategy:{self.config.name}] 状态变更: {status.value}")

    def get_info(self) -> Dict:
        """获取策略信息"""
        return {
            **self.config.to_dict(),
            "status": self._status.value,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "run_count": self._run_count,
        }


# ============ 可转债策略实现 ============

class ConvertibleBondStrategy(BaseStrategy):
    """可转债策略实现"""

    def __init__(self, config: StrategyConfig = None):
        config = config or StrategyConfig(
            strategy_id="sg_cb_default",
            name="松岗可转债策略",
            strategy_type=StrategyType.CONVERTIBLE_BOND,
        )
        super().__init__(config)

        # 策略组件
        self._scorer = None
        self._filter = None
        self._whitelist_manager = None
        self._signal_generator = None

    def initialize(self):
        """初始化"""
        from app.sg_strategy.core.scoring import ScoringEngine
        from app.sg_strategy.core.filters import VetoFilter
        from app.sg_strategy.core.whitelist import WhitelistManager
        from app.sg_strategy.core.signals import SignalGenerator

        self._scorer = ScoringEngine()
        self._filter = VetoFilter()
        self._whitelist_manager = WhitelistManager(
            whitelist_size=self.config.params.get("whitelist_size", 60),
        )
        self._signal_generator = SignalGenerator()

        logger.info(f"[Strategy] 初始化完成: {self.config.name}")

    def on_data(self, data: Dict[str, pd.DataFrame]) -> Dict:
        """处理数据"""
        cb_data = data.get("cb_data", pd.DataFrame())
        stock_data = data.get("stock_data", pd.DataFrame())

        if cb_data.empty:
            return {}

        # 打分
        scores = self._scorer.score_all(cb_data, stock_data)

        # 过滤
        filtered_codes = self._filter.filter(cb_data)

        # 更新白名单
        self._whitelist_manager.update(scores, filtered_codes)

        return {
            "scores": scores,
            "whitelist": self._whitelist_manager.get_whitelist(),
            "filtered_codes": filtered_codes,
        }

    def generate_signals(self, context: Dict) -> List[Dict]:
        """生成信号"""
        signals = self._signal_generator.generate(
            context.get("whitelist", []),
            context.get("scores", {}),
        )
        return signals


# ============ 策略工厂 ============

class StrategyFactory:
    """策略工厂"""

    _strategies: Dict[str, Type[BaseStrategy]] = {}
    _instances: Dict[str, BaseStrategy] = {}

    @classmethod
    def register(cls, strategy_id: str, strategy_class: Type[BaseStrategy]):
        """注册策略"""
        cls._strategies[strategy_id] = strategy_class
        logger.info(f"[StrategyFactory] 注册策略: {strategy_id}")

    @classmethod
    def create(cls, config: StrategyConfig) -> BaseStrategy:
        """创建策略实例"""
        strategy_id = config.strategy_id

        # 检查是否已有实例
        if strategy_id in cls._instances:
            return cls._instances[strategy_id]

        # 获取策略类
        strategy_class = cls._strategies.get(strategy_id)

        if strategy_class is None:
            # 尝试动态加载
            strategy_class = cls._load_strategy(strategy_id)

        if strategy_class is None:
            # 使用默认可转债策略
            strategy_class = ConvertibleBondStrategy

        # 创建实例
        instance = strategy_class(config)
        cls._instances[strategy_id] = instance

        logger.info(f"[StrategyFactory] 创建策略实例: {strategy_id}")
        return instance

    @classmethod
    def _load_strategy(cls, strategy_id: str) -> Optional[Type[BaseStrategy]]:
        """动态加载策略"""
        try:
            # 尝试从策略目录加载
            module_path = f"app.sg_strategy.strategies.{strategy_id}"
            module = importlib.import_module(module_path)

            # 查找策略类
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, BaseStrategy) and obj != BaseStrategy:
                    cls._strategies[strategy_id] = obj
                    return obj

        except ImportError:
            logger.debug(f"[StrategyFactory] 策略模块不存在: {strategy_id}")

        return None

    @classmethod
    def get_instance(cls, strategy_id: str) -> Optional[BaseStrategy]:
        """获取策略实例"""
        return cls._instances.get(strategy_id)

    @classmethod
    def list_strategies(cls) -> List[Dict]:
        """列出所有策略"""
        return [
            {
                "strategy_id": strategy_id,
                "class_name": cls.__name__,
            }
            for strategy_id, cls in cls._strategies.items()
        ]

    @classmethod
    def list_instances(cls) -> List[Dict]:
        """列出所有实例"""
        return [
            instance.get_info()
            for instance in cls._instances.values()
        ]


# ============ 策略组合 ============

class StrategyCombination:
    """策略组合"""

    def __init__(
        self,
        name: str,
        allocation_method: AllocationMethod = AllocationMethod.EQUAL,
    ):
        self.name = name
        self.allocation_method = allocation_method
        self._strategies: Dict[str, BaseStrategy] = {}
        self._weights: Dict[str, float] = {}

    def add_strategy(
        self,
        strategy: BaseStrategy,
        weight: float = None,
    ):
        """添加策略"""
        strategy_id = strategy.config.strategy_id
        self._strategies[strategy_id] = strategy

        # 设置权重
        if weight is not None:
            self._weights[strategy_id] = weight
        else:
            self._weights[strategy_id] = 1.0 / len(self._strategies)

    def remove_strategy(self, strategy_id: str):
        """移除策略"""
        if strategy_id in self._strategies:
            del self._strategies[strategy_id]
            del self._weights[strategy_id]

    def rebalance(self):
        """重新平衡权重"""
        if self.allocation_method == AllocationMethod.EQUAL:
            n = len(self._strategies)
            self._weights = {sid: 1.0/n for sid in self._strategies}

        elif self.allocation_method == AllocationMethod.RISK_PARITY:
            # 简化实现：等权重
            self.rebalance_equal()

    def run(self, data: Dict[str, pd.DataFrame]) -> Dict[str, StrategyResult]:
        """运行所有策略"""
        results = {}

        for strategy_id, strategy in self._strategies.items():
            try:
                result = strategy.run(data)
                results[strategy_id] = result
            except Exception as e:
                logger.error(f"[Combination] 策略运行失败: {strategy_id}, {e}")

        return results

    def combine_signals(
        self,
        results: Dict[str, StrategyResult],
    ) -> List[Dict]:
        """组合信号"""
        # 收集所有信号
        all_signals = []

        for strategy_id, result in results.items():
            weight = self._weights.get(strategy_id, 1.0)

            for signal in result.signals:
                signal["strategy_id"] = strategy_id
                signal["weight"] = weight
                all_signals.append(signal)

        # 按代码聚合
        signals_by_code: Dict[str, List[Dict]] = {}
        for signal in all_signals:
            code = signal.get("code")
            if code not in signals_by_code:
                signals_by_code[code] = []
            signals_by_code[code].append(signal)

        # 合并信号
        combined_signals = []
        for code, code_signals in signals_by_code.items():
            # 加权投票
            buy_weight = sum(s["weight"] for s in code_signals if s["action"] == "buy")
            sell_weight = sum(s["weight"] for s in code_signals if s["action"] == "sell")

            if buy_weight > sell_weight and buy_weight > 0.3:
                action = "buy"
            elif sell_weight > buy_weight and sell_weight > 0.3:
                action = "sell"
            else:
                continue

            combined_signals.append({
                "code": code,
                "action": action,
                "confidence": max(buy_weight, sell_weight),
                "source_strategies": [s["strategy_id"] for s in code_signals],
            })

        return combined_signals

    def get_allocation(self) -> Dict[str, float]:
        """获取配置"""
        return self._weights.copy()


# ============ 策略评估器 ============

class StrategyEvaluator:
    """策略评估器"""

    def __init__(self):
        self._results_history: Dict[str, List[StrategyResult]] = {}

    def record_result(self, result: StrategyResult):
        """记录结果"""
        strategy_id = result.strategy_id

        if strategy_id not in self._results_history:
            self._results_history[strategy_id] = []

        self._results_history[strategy_id].append(result)

    def evaluate(
        self,
        strategy_id: str,
        backtest_results: Dict = None,
    ) -> Dict[str, Any]:
        """评估策略"""
        results = self._results_history.get(strategy_id, [])

        if not results:
            return {}

        # 统计
        total_signals = sum(len(r.signals) for r in results)
        avg_execution_time = np.mean([r.execution_time for r in results])

        return {
            "strategy_id": strategy_id,
            "total_runs": len(results),
            "total_signals": total_signals,
            "avg_signals_per_run": total_signals / len(results),
            "avg_execution_time": avg_execution_time,
            "last_run": results[-1].date.isoformat() if results else None,
        }

    def compare_strategies(
        self,
        strategy_ids: List[str],
    ) -> Dict[str, Dict]:
        """比较策略"""
        comparison = {}

        for strategy_id in strategy_ids:
            comparison[strategy_id] = self.evaluate(strategy_id)

        return comparison


# ============ 便捷函数 ============

def create_strategy(
    strategy_id: str,
    name: str = None,
    strategy_type: StrategyType = StrategyType.CONVERTIBLE_BOND,
    params: Dict = None,
) -> BaseStrategy:
    """创建策略"""
    config = StrategyConfig(
        strategy_id=strategy_id,
        name=name or strategy_id,
        strategy_type=strategy_type,
        params=params or {},
    )
    return StrategyFactory.create(config)


def get_strategy(strategy_id: str) -> Optional[BaseStrategy]:
    """获取策略实例"""
    return StrategyFactory.get_instance(strategy_id)


def register_strategy(strategy_id: str, strategy_class: Type[BaseStrategy]):
    """注册策略"""
    StrategyFactory.register(strategy_id, strategy_class)


def list_strategies() -> List[Dict]:
    """列出所有策略"""
    return StrategyFactory.list_strategies()


# 注册默认策略
StrategyFactory.register("sg_cb_default", ConvertibleBondStrategy)
StrategyFactory.register("convertible_bond", ConvertibleBondStrategy)
