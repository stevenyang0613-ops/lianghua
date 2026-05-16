"""松岗量化可转债策略 V3.0

完整的七维打分量化可转债投资策略

核心功能:
- 七维量化打分引擎 (满分100分)
- 前60名白名单动态轮换
- 四因子择时模型
- 8维度信用风控
- 三层交易成本模型
- 事件驱动子策略
- 动态对冲策略
- Walk-forward回测验证
"""

__version__ = "3.0.0"
__author__ = "松岗量化"

from app.sg_strategy.core.strategy import SGConvertibleStrategy
from app.sg_strategy.config.settings import params, StrategyParams
from app.sg_strategy.config.weights import MarketRegime, WEIGHT_SCHEMES

__all__ = [
    "SGConvertibleStrategy",
    "params",
    "StrategyParams",
    "MarketRegime",
    "WEIGHT_SCHEMES",
]
