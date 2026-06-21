from app.strategies.base import Strategy
from app.strategies.dual_low import DualLowStrategy
from app.strategies.low_premium import LowPremiumStrategy
from app.strategies.momentum import MomentumStrategy
from app.strategies.xuanji_v8 import XuanjiV8Strategy
from app.strategies.multi_factor import MultiFactorStrategy
from app.strategies.xibu_seven_dimension import XibuSevenDimensionStrategy
from app.strategies.xuanji_twelve_factor import XuanjiTwelveFactorStrategy
from app.strategies.sector_rotation import SectorRotationStrategy
from app.strategies.fusion_strategy import FusionStrategy

import logging

logger = logging.getLogger(__name__)


STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "dual_low": DualLowStrategy,
    "low_premium": LowPremiumStrategy,
    "momentum": MomentumStrategy,
    "xuanji_v8": XuanjiV8Strategy,
    "multi_factor": MultiFactorStrategy,
    "xibu_seven": XibuSevenDimensionStrategy,
    "xuanji_twelve": XuanjiTwelveFactorStrategy,
    "sector_rotation": SectorRotationStrategy,
    "fusion": FusionStrategy,
}

# ── 启动时校验：防止重复 key 导致策略加载混淆 ──
_imported = [k for k, v in STRATEGY_REGISTRY.items() if not isinstance(v, type)]
if _imported:
    raise TypeError(f"STRATEGY_REGISTRY has non-type values: {_imported}")
_dupes = [k for k in STRATEGY_REGISTRY if list(STRATEGY_REGISTRY.keys()).count(k) > 1]
if _dupes:
    raise ValueError(f"STRATEGY_REGISTRY has duplicate keys: {_dupes}")


def register_strategy(key: str, cls: type[Strategy], overwrite: bool = False) -> None:
    """运行时注册策略（支持热加载）。
    
    Args:
        key: 策略唯一标识符
        cls: 策略类
        overwrite: 是否允许覆盖已存在的 key
    
    Raises:
        ValueError: key 已存在且 overwrite=False
        TypeError: cls 不是 Strategy 的子类
    """
    if not isinstance(cls, type) or not issubclass(cls, Strategy):
        raise TypeError(f"{cls} must be a subclass of Strategy, got {type(cls)}")
    
    if key in STRATEGY_REGISTRY and not overwrite:
        raise ValueError(
            f"Strategy key '{key}' already registered (class={STRATEGY_REGISTRY[key].__name__}). "
            f"Use overwrite=True to replace."
        )
    
    STRATEGY_REGISTRY[key] = cls
    logger.info(f"[Strategy] Registered '{key}' -> {cls.__name__}")


def unregister_strategy(key: str) -> None:
    """运行时注销策略。"""
    if key not in STRATEGY_REGISTRY:
        raise KeyError(f"Strategy '{key}' not found in registry")
    cls = STRATEGY_REGISTRY.pop(key)
    logger.info(f"[Strategy] Unregistered '{key}' ({cls.__name__})")


def get_strategy(name: str) -> type[Strategy]:
    if name not in STRATEGY_REGISTRY:
        raise ValueError(f"Unknown strategy: {name}. Available: {list(STRATEGY_REGISTRY.keys())}")
    return STRATEGY_REGISTRY[name]


def list_strategies() -> list[dict]:
    return [
        {"id": k, "name": cls.name, "description": cls.description, "params": [p.model_dump() for p in cls.params]}
        for k, cls in STRATEGY_REGISTRY.items()
    ]
