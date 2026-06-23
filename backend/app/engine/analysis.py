import math
import hashlib
import json
import threading
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any, Optional
from app.models.convertible import ConvertibleQuote
import logging
logger = logging.getLogger(__name__)


class AnalysisEngine:
    """Analysis engine for convertible bond data."""

    def __init__(self, cache_ttl: int = 0, max_entries: int = 0):
        self._cache_ttl = cache_ttl
        self._max_entries = max_entries
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_method_keys: dict[str, set[str]] = {}
        self._cache_code_keys: dict[str, set[str]] = {}
        self._lock = threading.Lock()

    def _cache_key(self, method: str, bonds: list, **kwargs) -> str:
        n = len(bonds)
        first_code = bonds[0].code if n > 0 else ""
        last_code = bonds[-1].code if n > 0 else ""
        bond_sig = f"{n}:{first_code}:{last_code}"
        kw_str = json.dumps(kwargs, sort_keys=True, default=str)
        raw = f"{method}:{bond_sig}:{kw_str}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _get_cache(self, key: str) -> Any | None:
        if self._cache_ttl <= 0:
            return None
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._cache_misses += 1
                return None
            ts, value = entry
            if (datetime.now().timestamp() - ts) > self._cache_ttl:
                del self._cache[key]
                self._remove_key_from_indexes(key)
                self._cache_misses += 1
                return None
            self._cache_hits += 1
            self._cache.move_to_end(key)
            return value

    def _remove_key_from_indexes(self, key: str) -> None:
        for method_keys in self._cache_method_keys.values():
            method_keys.discard(key)
        for code_keys in self._cache_code_keys.values():
            code_keys.discard(key)

    def _set_cache(self, key: str, value: Any, method: str = "", codes: list[str] | None = None) -> None:
        if self._cache_ttl > 0:
            with self._lock:
                if self._max_entries > 0 and len(self._cache) >= self._max_entries and key not in self._cache:
                    oldest_key, _ = self._cache.popitem(last=False)
                    self._remove_key_from_indexes(oldest_key)
                self._cache[key] = (datetime.now().timestamp(), value)
                self._cache.move_to_end(key)
                if method:
                    self._cache_method_keys.setdefault(method, set()).add(key)
                if codes:
                    for code in codes:
                        self._cache_code_keys.setdefault(code, set()).add(key)

    def cache_stats(self) -> dict:
        with self._lock:
            total = self._cache_hits + self._cache_misses
            hit_rate = self._cache_hits / total if total > 0 else 0.0
            return {
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "size": len(self._cache),
                "ttl": self._cache_ttl,
                "hit_rate": round(hit_rate, 4),
            }

    def invalidate_cache(self, method: str) -> int:
        """Remove all cache entries for a given method."""
        with self._lock:
            removed = 0
            keys_for_method = self._cache_method_keys.get(method, set())
            for k in list(keys_for_method):
                if k in self._cache:
                    del self._cache[k]
                    removed += 1
                self._remove_key_from_indexes(k)
            self._cache_method_keys.pop(method, None)
            return removed

    def invalidate_all(self) -> int:
        """Clear all cache entries."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._cache_method_keys.clear()
            self._cache_code_keys.clear()
        return count

    def invalidate_by_code(self, code: str) -> int:
        """Remove all cache entries that contain the given bond code."""
        with self._lock:
            removed = 0
            keys_for_code = self._cache_code_keys.pop(code, set())
            for k in list(keys_for_code):
                if k in self._cache:
                    del self._cache[k]
                    removed += 1
            for method_keys in self._cache_method_keys.values():
                method_keys -= keys_for_code
            for other_code, other_keys in self._cache_code_keys.items():
                other_keys -= keys_for_code
        return removed

    @staticmethod
    def is_valid_bond(b: ConvertibleQuote, min_volume: float = 0) -> bool:
        """Filter out delisted/invalid/exchangeable/called bonds before analysis.

        在统一交易过滤(is_tradeable_bond)的基础上,再叠加:
        - 流动性:无成交且剩余年限短(脉冲扫描专用)
        - 最低成交额
        """
        from app.engine.filters import is_tradeable_bond
        if not is_tradeable_bond(b):
            return False
        if (b.volume is None or b.volume == 0) and b.remaining_years is not None and b.remaining_years < 0.5:
            return False
        if min_volume > 0 and (b.volume is None or b.volume < min_volume):
            return False
        return True

    @staticmethod
    def _pearson_correlation(xs: list[float], ys: list[float]) -> Optional[float]:
        """Calculate Pearson correlation coefficient between two series."""
        n = len(xs)
        if n < 3:
            return None
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        var_x = sum((x - mean_x) ** 2 for x in xs)
        var_y = sum((y - mean_y) ** 2 for y in ys)
        if var_x == 0 or var_y == 0:
            return None
        return round(cov / math.sqrt(var_x * var_y), 4)

    ENUM_ORDER: dict[str, dict[str, int]] = {
        "risk_level": {"high": 0, "medium": 1, "low": 2, "watch": 3, "none": 4},
        "severity": {"high": 0, "medium": 1, "low": 2},
        "correlation": {"强关联": 0, "中关联": 1, "弱关联": 2, "待观察": 3},
    }

    @staticmethod
    def _apply_sort(results: list[dict], sort_by: str = "", sort_order: str = "asc") -> list[dict]:
        """Apply custom sorting to results, with enum-aware ordering for known fields. Nulls always last. Supports comma-separated multi-field sort."""
        if not sort_by or not results:
            return results
        fields = [f.strip() for f in sort_by.split(",")]
        if any(f not in results[0] for f in fields if f):
            return results

        asc = sort_order == "asc"

        def sort_key(x):
            key_parts = []
            for field in fields:
                enum_map = AnalysisEngine.ENUM_ORDER.get(field)
                v = x.get(field)
                if v is None:
                    key_parts.append((1, 0))
                elif enum_map:
                    max_rank = len(enum_map)
                    rank = enum_map.get(v, max_rank + 1)
                    key_parts.append((0, rank if asc else -rank))
                else:
                    try:
                        key_parts.append((0, v if asc else -v))
                    except TypeError:
                        key_parts.append((1, 0))
            return tuple(key_parts)

        results.sort(key=sort_key)
        return results

    @staticmethod
    def compute_forced_redemption(bonds: list[ConvertibleQuote], limit: int = 0, offset: int = 0, min_volume: float = 0, sort_by: str = "", sort_order: str = "asc") -> list[dict]:
        """Compute forced redemption calendar with put-back pressure."""
        results = []
        for b in bonds:
            if not AnalysisEngine.is_valid_bond(b, min_volume=min_volume):
                continue
            if b.conversion_value is None or b.conversion_value <= 0:
                continue

            stock_above_130 = b.stock_price and b.conversion_price and (
                b.stock_price / b.conversion_price >= 1.3
            )

            forced_call_days = getattr(b, "forced_call_days", 0) or 0

            put_back_pressure = (
                b.conversion_price and b.conversion_price > 0 and b.stock_price is not None and b.stock_price < b.conversion_price
                and b.remaining_years is not None and 0 < b.remaining_years < 2
            )

            if stock_above_130:
                trigger_days = max(0, 15 - forced_call_days)
                risk_level = "high" if trigger_days <= 5 else "medium" if trigger_days <= 10 else "low"
            else:
                ratio = (b.stock_price / b.conversion_price * 100) if b.conversion_price and b.conversion_price > 0 else 0
                trigger_days = None
                risk_level = "watch" if put_back_pressure else ("none" if ratio < 120 else "watch")

            results.append({
                "code": b.code,
                "name": b.name,
                "stock_price": b.stock_price,
                "conversion_price": b.conversion_price,
                "ratio": round(b.stock_price / b.conversion_price * 100, 2) if b.conversion_price > 0 else 0,
                "conversion_value": round(b.conversion_value, 2),
                "premium_ratio": b.premium_ratio,
                "trigger_days": trigger_days,
                "forced_call_days": forced_call_days,
                "risk_level": risk_level,
                "remaining_years": b.remaining_years,
                "put_back_pressure": put_back_pressure,
            })

        if sort_by:
            AnalysisEngine._apply_sort(results, sort_by, sort_order)
        else:
            risk_order = {"high": 0, "medium": 1, "low": 2, "watch": 3, "none": 4}
            results.sort(key=lambda x: (risk_order.get(x["risk_level"], 99), x.get("trigger_days") or 999))

        if offset:
            results = results[offset:]
        if limit:
            results = results[:limit]
        return results

    @staticmethod
    def compute_dual_low_ranking(bonds: list[ConvertibleQuote], limit: int = 0, offset: int = 0, min_volume: float = 0, sort_by: str = "", sort_order: str = "asc") -> list[dict]:
        """Rank bonds by dual_low value (price + premium)."""
        results = []
        for i, b in enumerate(sorted(bonds, key=lambda x: x.dual_low or 999)):
            if not AnalysisEngine.is_valid_bond(b, min_volume=min_volume):
                continue
            results.append({
                "rank": len(results) + 1,
                "code": b.code,
                "name": b.name,
                "price": b.price,
                "premium_ratio": b.premium_ratio,
                "dual_low": b.dual_low,
                "ytm": b.ytm,
                "volume": b.volume,
                "remaining_years": b.remaining_years,
                "stock_price": b.stock_price,
                "conversion_value": round(b.conversion_value, 2),
            })
        if sort_by:
            AnalysisEngine._apply_sort(results, sort_by, sort_order)
        if offset:
            results = results[offset:]
        if limit:
            results = results[:limit]
        return results

    @staticmethod
    def scan_pulse(bonds: list[ConvertibleQuote], limit: int = 0, offset: int = 0, min_volume: float = 0, storage=None, start_date: str | None = None, end_date: str | None = None, sort_by: str = "", sort_order: str = "asc") -> list[dict]:
        """Scan for unusual price/volume movements."""
        valid_bonds = [b for b in bonds if AnalysisEngine.is_valid_bond(b, min_volume=min_volume) and b.volume and b.volume > 0]
        avg_volume = sum(b.volume for b in valid_bonds if b.volume is not None) / max(sum(1 for b in valid_bonds if b.volume is not None), 1) if valid_bonds else 0

        # Batch fetch history for sustained divergence detection
        history_batch: dict = {}
        if storage is not None:
            try:
                codes = [b.code for b in bonds if AnalysisEngine.is_valid_bond(b, min_volume=min_volume)]
                if codes:
                    history_batch = storage.get_quote_history_batch(codes, limit=10, start_date=start_date, end_date=end_date)
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
                pass

        results = []
        for b in bonds:
            if not AnalysisEngine.is_valid_bond(b, min_volume=min_volume):
                continue
            change = abs(b.change_pct) if b.change_pct else 0
            stock_change_val = b.stock_change_pct or 0

            if change >= 3:
                pulse_type = "价格大涨" if b.change_pct > 0 else "价格大跌"
                results.append({
                    "code": b.code,
                    "name": b.name,
                    "pulse_type": pulse_type,
                    "change_pct": b.change_pct,
                    "price": b.price,
                    "volume": b.volume,
                    "premium_ratio": b.premium_ratio,
                    "dual_low": b.dual_low,
                    "severity": "high" if change >= 5 else "medium",
                })

            if b.premium_ratio and b.premium_ratio > 50:
                results.append({
                    "code": b.code,
                    "name": b.name,
                    "pulse_type": "高溢价",
                    "change_pct": b.change_pct,
                    "price": b.price,
                    "volume": b.volume,
                    "premium_ratio": b.premium_ratio,
                    "dual_low": b.dual_low,
                    "severity": "medium",
                })

            if b.remaining_years is not None and b.remaining_years < 0.5:
                results.append({
                    "code": b.code,
                    "name": b.name,
                    "pulse_type": "临近到期",
                    "change_pct": b.change_pct,
                    "price": b.price,
                    "volume": b.volume,
                    "premium_ratio": b.premium_ratio,
                    "remaining_years": b.remaining_years,
                    "severity": "high" if b.remaining_years < 0.2 else "medium",
                })

            if avg_volume > 0 and b.volume and b.volume >= avg_volume * 3:
                pulse_type = "放量" if change > 0.5 else "异动"
                vol_ratio = round(b.volume / avg_volume, 2)
                results.append({
                    "code": b.code,
                    "name": b.name,
                    "pulse_type": pulse_type,
                    "change_pct": b.change_pct,
                    "price": b.price,
                    "volume": b.volume,
                    "premium_ratio": b.premium_ratio,
                    "dual_low": b.dual_low,
                    "volume_ratio": vol_ratio,
                    "severity": "medium",
                })

            if b.dual_low and b.dual_low < 115:
                results.append({
                    "code": b.code,
                    "name": b.name,
                    "pulse_type": "低双低",
                    "change_pct": b.change_pct,
                    "price": b.price,
                    "volume": b.volume,
                    "premium_ratio": b.premium_ratio,
                    "dual_low": b.dual_low,
                    "severity": "high" if b.dual_low < 105 else "medium",
                })

            # Price divergence detection
            bond_chg = b.change_pct or 0
            if abs(bond_chg) >= 1 and abs(stock_change_val) >= 1 and bond_chg * stock_change_val < 0:
                # Check for sustained divergence from history
                severity = "medium"
                if history_batch and b.code in history_batch:
                    sustained_count = 0
                    for h in history_batch[b.code]:
                        h_bond_chg = float(h.get("change_pct")) if h.get("change_pct") is not None else None
                        h_stock_chg = float(h.get("stock_change_pct")) if h.get("stock_change_pct") is not None else None
                        if h_bond_chg is not None and h_stock_chg is not None and abs(h_bond_chg) >= 0.5 and abs(h_stock_chg) >= 0.5 and h_bond_chg * h_stock_chg < 0:
                            sustained_count += 1
                    if sustained_count >= 3:
                        severity = "high"

                results.append({
                    "code": b.code,
                    "name": b.name,
                    "pulse_type": "价背离",
                    "change_pct": b.change_pct,
                    "price": b.price,
                    "volume": b.volume,
                    "premium_ratio": b.premium_ratio,
                    "dual_low": b.dual_low,
                    "severity": severity,
                })

        severity_order = {"high": 0, "medium": 1}
        results.sort(key=lambda x: (severity_order.get(x["severity"], 99), -(abs(x.get("change_pct", 0) or 0))))

        seen = set()
        deduped = []
        for r in results:
            if r['code'] not in seen:
                seen.add(r['code'])
                deduped.append(r)
        results = deduped

        if sort_by:
            results = AnalysisEngine._apply_sort(results, sort_by, sort_order)

        if offset:
            results = results[offset:]
        if limit:
            results = results[:limit]
        return results

    @staticmethod
    def compute_revision_probability(bonds: list[ConvertibleQuote], limit: int = 0, offset: int = 0, min_volume: float = 0, storage=None, start_date: str | None = None, end_date: str | None = None, sort_by: str = "", sort_order: str = "asc") -> list[dict]:
        """Estimate downward revision probability with history lookup."""
        results = []
        for b in bonds:
            if not AnalysisEngine.is_valid_bond(b, min_volume=min_volume):
                continue
            if b.conversion_price is None or b.conversion_price <= 0 or b.stock_price is None or b.stock_price <= 0:
                continue

            ratio = b.stock_price / b.conversion_price
            price_distance = (1 - ratio) * 100

            if price_distance <= 0:
                continue

            distance_score = min(price_distance / 30, 1.0) * 40

            time_score = 0
            if b.remaining_years:
                if b.remaining_years < 0.3:
                    time_score = 5
                elif b.remaining_years < 1:
                    time_score = 30
                elif b.remaining_years < 2:
                    time_score = 40
                elif b.remaining_years < 3:
                    time_score = 25
                else:
                    time_score = 10

            premium_score = min(b.premium_ratio / 100, 1.0) * 20 if b.premium_ratio else 0

            # Revision history bonus
            revision_history_count = 0
            if storage is not None:
                try:
                    revision_history = storage.get_revision_history(b.code)
                    revision_history_count = len(revision_history) if revision_history else 0
                except Exception as e:
                    logger.debug(f"Suppressed: {e}")
                    pass

            history_bonus = min(revision_history_count * 5, 15)

            total_score = distance_score + time_score + premium_score + history_bonus
            probability = min(round(total_score, 1), 95.0)

            level = (
                "high" if probability >= 60 else
                "medium" if probability >= 30 else
                "low"
            )

            results.append({
                "code": b.code,
                "name": b.name,
                "stock_price": b.stock_price,
                "conversion_price": b.conversion_price,
                "price_distance": round(price_distance, 2),
                "ratio": round(ratio * 100, 2),
                "premium_ratio": b.premium_ratio,
                "remaining_years": b.remaining_years,
                "probability": probability,
                "level": level,
                "distance_score": round(distance_score, 1),
                "time_score": time_score,
                "premium_score": round(premium_score, 1),
                "revision_history_count": revision_history_count,
            })

        results.sort(key=lambda x: x["probability"], reverse=True)
        if sort_by:
            results = AnalysisEngine._apply_sort(results, sort_by, sort_order)
        if offset:
            results = results[offset:]
        if limit:
            results = results[:limit]
        return results

    @staticmethod
    def compute_stock_correlation(bonds: list[ConvertibleQuote], limit: int = 0, offset: int = 0, min_volume: float = 0, storage=None, start_date: str | None = None, end_date: str | None = None, sort_by: str = "", sort_order: str = "asc") -> list[dict]:
        """Analyze correlation between bond and underlying stock."""
        # Batch fetch history for Pearson correlation
        history_batch: dict = {}
        if storage is not None:
            try:
                codes = [b.code for b in bonds if AnalysisEngine.is_valid_bond(b, min_volume=min_volume)]
                if codes:
                    history_batch = storage.get_quote_history_batch(codes, limit=30, start_date=start_date, end_date=end_date)
            except Exception as e:
                logger.debug(f"Suppressed: {e}")
                pass

        results = []
        for b in bonds:
            if not AnalysisEngine.is_valid_bond(b, min_volume=min_volume):
                continue

            bond_change = b.change_pct or 0
            stock_change = b.stock_change_pct or 0

            elasticity = round(bond_change / stock_change, 4) if abs(stock_change) > 0.01 else 0

            abs_elasticity = abs(elasticity)
            if abs(stock_change) < 0.01:
                correlation = "待观察"
            elif abs_elasticity >= 0.5:
                correlation = "强关联"
            elif abs_elasticity >= 0.2:
                correlation = "中关联"
            else:
                correlation = "弱关联"

            # Compute Pearson from batch history
            pearson_corr = None
            if b.code in history_batch:
                history = history_batch[b.code]
                if history and len(history) >= 3:
                    pairs = [(float(r["price"]), float(r["stock_price"]))
                             for r in history if r.get("price") is not None and r.get("stock_price") is not None]
                    if len(pairs) >= 3:
                        prices = [p[0] for p in pairs]
                        stock_prices = [p[1] for p in pairs]
                        pearson_corr = AnalysisEngine._pearson_correlation(prices, stock_prices)

            results.append({
                "code": b.code,
                "name": b.name,
                "bond_change": bond_change,
                "stock_change": stock_change,
                "elasticity": elasticity,
                "correlation": correlation,
                "pearson_correlation": pearson_corr,
                "premium_ratio": b.premium_ratio,
                "conversion_value": round(b.conversion_value, 2),
                "price": b.price,
                "stock_price": b.stock_price,
                "dual_low": b.dual_low,
            })

        results.sort(key=lambda x: abs(x["elasticity"]), reverse=True)
        if sort_by:
            results = AnalysisEngine._apply_sort(results, sort_by, sort_order)
        if offset:
            results = results[offset:]
        if limit:
            results = results[:limit]
        return results

    @staticmethod
    def _compute_with_meta(compute_fn, bonds: list[ConvertibleQuote], **kwargs) -> dict:
        """Helper: run a compute method and return result with total_unfiltered."""
        total_unfiltered = len(bonds)
        items = compute_fn(bonds, **kwargs)
        return {"total_unfiltered": total_unfiltered, "items": items}

    @staticmethod
    def compute_dual_low_ranking_with_meta(bonds: list[ConvertibleQuote], limit: int = 0, offset: int = 0, min_volume: float = 0, sort_by: str = "", sort_order: str = "asc") -> dict:
        return AnalysisEngine._compute_with_meta(AnalysisEngine.compute_dual_low_ranking, bonds, limit=limit, offset=offset, min_volume=min_volume, sort_by=sort_by, sort_order=sort_order)

    @staticmethod
    def compute_forced_redemption_with_meta(bonds: list[ConvertibleQuote], limit: int = 0, offset: int = 0, min_volume: float = 0, sort_by: str = "", sort_order: str = "asc") -> dict:
        return AnalysisEngine._compute_with_meta(AnalysisEngine.compute_forced_redemption, bonds, limit=limit, offset=offset, min_volume=min_volume, sort_by=sort_by, sort_order=sort_order)

    @staticmethod
    def scan_pulse_with_meta(bonds: list[ConvertibleQuote], limit: int = 0, offset: int = 0, min_volume: float = 0, storage=None, sort_by: str = "", sort_order: str = "asc", start_date: str = "", end_date: str = "") -> dict:
        return AnalysisEngine._compute_with_meta(AnalysisEngine.scan_pulse, bonds, limit=limit, offset=offset, min_volume=min_volume, storage=storage, sort_by=sort_by, sort_order=sort_order, start_date=start_date, end_date=end_date)

    @staticmethod
    def compute_revision_probability_with_meta(bonds: list[ConvertibleQuote], limit: int = 0, offset: int = 0, min_volume: float = 0, storage=None, sort_by: str = "", sort_order: str = "asc", start_date: str = "", end_date: str = "") -> dict:
        return AnalysisEngine._compute_with_meta(AnalysisEngine.compute_revision_probability, bonds, limit=limit, offset=offset, min_volume=min_volume, storage=storage, sort_by=sort_by, sort_order=sort_order, start_date=start_date, end_date=end_date)

    @staticmethod
    def compute_stock_correlation_with_meta(bonds: list[ConvertibleQuote], limit: int = 0, offset: int = 0, min_volume: float = 0, storage=None, sort_by: str = "", sort_order: str = "asc", start_date: str = "", end_date: str = "") -> dict:
        return AnalysisEngine._compute_with_meta(AnalysisEngine.compute_stock_correlation, bonds, limit=limit, offset=offset, min_volume=min_volume, storage=storage, sort_by=sort_by, sort_order=sort_order, start_date=start_date, end_date=end_date)

    # Cached instance methods
    def cached_forced_redemption(self, bonds: list[ConvertibleQuote], **kwargs) -> list[dict]:
        key = self._cache_key("forced_redemption", bonds, **kwargs)
        result = self._get_cache(key)
        if result is not None:
            return result
        result = self.compute_forced_redemption(bonds, **kwargs)
        codes = [b.code for b in bonds]
        self._set_cache(key, result, method="forced_redemption", codes=codes)
        return result

    def cached_dual_low_ranking(self, bonds: list[ConvertibleQuote], **kwargs) -> list[dict]:
        key = self._cache_key("dual_low_ranking", bonds, **kwargs)
        result = self._get_cache(key)
        if result is not None:
            return result
        result = self.compute_dual_low_ranking(bonds, **kwargs)
        codes = [b.code for b in bonds]
        self._set_cache(key, result, method="dual_low_ranking", codes=codes)
        return result

    def cached_scan_pulse(self, bonds: list[ConvertibleQuote], **kwargs) -> list[dict]:
        key = self._cache_key("scan_pulse", bonds, **{k: v for k, v in kwargs.items() if k != "storage"})
        result = self._get_cache(key)
        if result is not None:
            return result
        result = self.scan_pulse(bonds, **kwargs)
        codes = [b.code for b in bonds]
        self._set_cache(key, result, method="scan_pulse", codes=codes)
        return result

    def cached_revision_probability(self, bonds: list[ConvertibleQuote], **kwargs) -> list[dict]:
        key = self._cache_key("revision_probability", bonds, **{k: v for k, v in kwargs.items() if k != "storage"})
        result = self._get_cache(key)
        if result is not None:
            return result
        result = self.compute_revision_probability(bonds, **kwargs)
        codes = [b.code for b in bonds]
        self._set_cache(key, result, method="revision_probability", codes=codes)
        return result

    def cached_stock_correlation(self, bonds: list[ConvertibleQuote], **kwargs) -> list[dict]:
        key = self._cache_key("stock_correlation", bonds, **{k: v for k, v in kwargs.items() if k != "storage"})
        result = self._get_cache(key)
        if result is not None:
            return result
        result = self.compute_stock_correlation(bonds, **kwargs)
        codes = [b.code for b in bonds]
        self._set_cache(key, result, method="stock_correlation", codes=codes)
        return result
