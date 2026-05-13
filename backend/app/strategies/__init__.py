from app.strategies.base import Strategy
from app.strategies.dual_low import DualLowStrategy


STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "dual_low": DualLowStrategy,
}


def get_strategy(name: str) -> type[Strategy]:
    if name not in STRATEGY_REGISTRY:
        raise ValueError(f"Unknown strategy: {name}. Available: {list(STRATEGY_REGISTRY.keys())}")
    return STRATEGY_REGISTRY[name]


def list_strategies() -> list[dict]:
    return [
        {"id": k, "name": cls.name, "description": cls.description, "params": [p.model_dump() for p in cls.params]}
        for k, cls in STRATEGY_REGISTRY.items()
    ]
