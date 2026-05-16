"""Signal confidence calculation - extracted for extensibility."""
from typing import Optional
from app.models.convertible import ConvertibleQuote

# Registry for custom confidence calculators: {strategy_id: callable}
_confidence_calculators: dict[str, callable] = {}


def register_confidence_calculator(strategy: str, calculator: callable) -> None:
    """Register a custom confidence calculator for a strategy.

    The calculator receives (bond, signal) and returns a float 0~1.
    """
    _confidence_calculators[strategy] = calculator


def calc_confidence(strategy: str, bond: Optional[ConvertibleQuote],
                    signal: dict) -> float:
    """Calculate signal confidence (0~1).

    Uses registered calculator if available, otherwise falls back to default.
    """
    if strategy in _confidence_calculators:
        return _confidence_calculators[strategy](bond, signal)
    return _default_confidence(strategy, bond, signal)


def _default_confidence(strategy: str, bond: Optional[ConvertibleQuote],
                         signal: dict) -> float:
    """Default confidence calculation logic."""
    if not bond:
        return 0.5

    score = 0.5

    if strategy == "dual_low":
        if bond.dual_low < 130:
            score += 0.3
        elif bond.dual_low < 150:
            score += 0.15
        if bond.premium_ratio < 10:
            score += 0.2
        elif bond.premium_ratio < 20:
            score += 0.1
    elif strategy == "low_premium":
        if bond.premium_ratio < 5:
            score += 0.3
        elif bond.premium_ratio < 10:
            score += 0.15
    elif strategy == "momentum":
        if bond.change_pct and bond.change_pct > 2:
            score += 0.2
            if bond.volume and bond.volume > 1e8:
                score += 0.1

    return min(score, 1.0)
