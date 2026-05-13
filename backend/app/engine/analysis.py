import math
from datetime import datetime, timedelta
from typing import Any
from app.models.convertible import ConvertibleQuote


class AnalysisEngine:
    """Analysis engine for convertible bond data."""

    @staticmethod
    def compute_forced_redemption(bonds: list[ConvertibleQuote]) -> list[dict]:
        """
        Compute forced redemption calendar.
        A bond triggers forced redemption when the stock price stays above
        the conversion price for 15+ out of 30 consecutive trading days
        (typically 130% of conversion price).
        """
        results = []
        for b in bonds:
            if b.conversion_value <= 0:
                continue

            premium = b.premium_ratio
            stock_above_130 = b.stock_price and b.conversion_price and (
                b.stock_price / b.conversion_price >= 1.3
            )

            forced_call_days = getattr(b, "forced_call_days", 0) or 0

            # Estimate remaining days before forced redemption triggers
            if stock_above_130:
                trigger_days = max(0, 15 - forced_call_days)
                risk_level = "high" if trigger_days <= 5 else "medium" if trigger_days <= 10 else "low"
            else:
                # Stock not above threshold, estimate distance
                ratio = (b.stock_price / b.conversion_price * 100) if b.conversion_price > 0 else 0
                trigger_days = None
                risk_level = "none" if ratio < 120 else "watch"

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
            })

        # Sort by risk level (high first), then by trigger_days
        risk_order = {"high": 0, "medium": 1, "low": 2, "watch": 3, "none": 4}
        results.sort(key=lambda x: (risk_order.get(x["risk_level"], 99), x.get("trigger_days") or 999))

        return results

    @staticmethod
    def compute_dual_low_ranking(bonds: list[ConvertibleQuote]) -> list[dict]:
        """Rank bonds by dual_low value (price + premium)."""
        results = []
        for i, b in enumerate(sorted(bonds, key=lambda x: x.dual_low)):
            if b.price <= 0:
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
        return results

    @staticmethod
    def scan_pulse(bonds: list[ConvertibleQuote]) -> list[dict]:
        """Scan for unusual price/volume movements."""
        results = []
        for b in bonds:
            change = abs(b.change_pct) if b.change_pct else 0
            vol_ratio = None

            # Detect significant price changes
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

            # Detect high premium (over 50%)
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

            # Detect approaching maturity (less than 0.5 years)
            if b.remaining_years and b.remaining_years < 0.5:
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

        # Sort by severity (high first), then by abs(change_pct) desc
        severity_order = {"high": 0, "medium": 1}
        results.sort(key=lambda x: (severity_order.get(x["severity"], 99), -(abs(x.get("change_pct", 0) or 0))))

        return results

    @staticmethod
    def compute_revision_probability(bonds: list[ConvertibleQuote]) -> list[dict]:
        """
        Estimate downward revision probability.
        Companies are likely to revise downward when:
        - Stock price is significantly below conversion price
        - Bond has put-option (回售) pressure
        - Remaining years are short but not critical
        """
        results = []
        for b in bonds:
            if b.conversion_price <= 0 or b.stock_price <= 0:
                continue

            ratio = b.stock_price / b.conversion_price

            # The lower the ratio, the higher the revision pressure
            price_distance = (1 - ratio) * 100

            if price_distance <= 0:
                continue  # No revision needed if stock is above conversion price

            # Factors that increase revision probability:
            # 1. Large distance from conversion price (worse = more pressure)
            # 2. Moderate remaining time (too short = too late, too long = no hurry)
            # 3. High premium (bond disconnected from stock)

            distance_score = min(price_distance / 30, 1.0) * 40  # max 40

            time_score = 0
            if b.remaining_years:
                # Peak revision pressure around 1-2 years remaining
                if b.remaining_years < 0.3:
                    time_score = 5  # Too late
                elif b.remaining_years < 1:
                    time_score = 30
                elif b.remaining_years < 2:
                    time_score = 40
                elif b.remaining_years < 3:
                    time_score = 25
                else:
                    time_score = 10  # Still has time

            premium_score = min(b.premium_ratio / 100, 1.0) * 20 if b.premium_ratio else 0

            total_score = distance_score + time_score + premium_score
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
            })

        results.sort(key=lambda x: x["probability"], reverse=True)
        return results

    @staticmethod
    def compute_stock_correlation(bonds: list[ConvertibleQuote]) -> list[dict]:
        """Analyze correlation between bond and underlying stock."""
        results = []
        for b in bonds:
            if not b.stock_change_pct or b.stock_change_pct == 0:
                continue

            bond_change = b.change_pct or 0
            stock_change = b.stock_change_pct

            # Simple elasticity: how much bond moves relative to stock
            elasticity = round(bond_change / stock_change, 4) if abs(stock_change) > 0.01 else 0

            results.append({
                "code": b.code,
                "name": b.name,
                "bond_change": bond_change,
                "stock_change": stock_change,
                "elasticity": elasticity,
                "premium_ratio": b.premium_ratio,
                "conversion_value": round(b.conversion_value, 2),
                "price": b.price,
                "stock_price": b.stock_price,
                "dual_low": b.dual_low,
            })

        # Sort by absolute elasticity (most responsive first)
        results.sort(key=lambda x: abs(x["elasticity"]), reverse=True)
        return results
