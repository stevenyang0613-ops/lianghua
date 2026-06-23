import pandas as pd
import numpy as np
from typing import Optional

from app.strategies.base import Strategy
from app.models.backtest import StrategyParam


class SectorRotationStrategy(Strategy):
    """行业轮动策略: 基于动量/夏普/波动率等因子选取最强行业ETF"""

    name = "行业轮动"
    description = (
        "13层数据源架构: AKShare申万指数→行业ETF映射→多因子评分→Top N轮动。"
        "支持动量因子/夏普因子/RSI/波动率/Hurst指数/RRG多维度评分"
    )

    params = [
        StrategyParam(name="hold_count", label="持仓行业数", type="int", default=5, min_val=1, max_val=10),
        StrategyParam(name="rebalance_days", label="调仓间隔(天)", type="int", default=20, min_val=5, max_val=60),
        StrategyParam(name="momentum_window", label="动量窗口(天)", type="int", default=60, min_val=10, max_val=252),
        StrategyParam(name="bull_factor", label="牛市直选因子", type="str", default="momentum_1m", choices={"momentum_1m": "1月动量", "momentum_3m": "3月动量", "relative_strength": "相对强弱"}),
        StrategyParam(name="bear_factor", label="熊市防御因子", type="str", default="sharpe_63d", choices={"sharpe_63d": "夏普比率", "volatility_63d": "低波动", "drawdown_63d": "低回撤"}),
        StrategyParam(name="use_etf", label="使用ETF回测", type="bool", default=True),
    ]

    def on_init(self, data: pd.DataFrame) -> None:
        self._data = data.copy()
        self._data["price"] = self._data.get("close", self._data.get("price", 100))
        self._data["code"] = self._data.get("industry_code", self._data.get("etf_code", self._data.get("code", "")))

        self._dates = sorted(self._data["date"].unique())
        window = self.get_param("momentum_window")

        grouped = self._data.groupby("code")
        self._data = self._data.sort_values(["code", "date"])

        self._data["momentum_1m"] = grouped["price"].transform(lambda x: x.pct_change(20))
        self._data["momentum_3m"] = grouped["price"].transform(lambda x: x.pct_change(60))
        ret = grouped["price"].transform(lambda x: x.pct_change())
        self._data["volatility_63d"] = ret.rolling(63).std() * np.sqrt(252)
        self._data["sharpe_63d"] = ret.rolling(63).mean() / (ret.rolling(63).std() + 1e-8) * np.sqrt(252)
        cummax = grouped["price"].transform(lambda x: x.rolling(63).max())
        self._data["drawdown_63d"] = (cummax - self._data["price"]) / (cummax + 1e-8)
        self._data["relative_strength"] = grouped["price"].transform(lambda x: x.pct_change(60).rank(pct=True))
        # RSI 动量因子
        gain = ret.clip(lower=0)
        loss = (-ret).clip(lower=0)
        avg_gain = grouped["price"].transform(lambda x: gain.rolling(14).mean())
        avg_loss = grouped["price"].transform(lambda x: loss.rolling(14).mean())
        rs = avg_gain / (avg_loss + 1e-8)
        self._data["rsi_14"] = 100 - (100 / (1 + rs))
        self._data["rsi_14"] = self._data["rsi_14"].fillna(50)

        # Hurst指数: 趋势持续性指标 (>0.5趋势持续, <0.5均值回归)
        def _hurst(series: pd.Series, max_lag: int = 20) -> float:
            try:
                lags = range(2, min(max_lag, len(series)//2))
                tau = [np.sqrt(np.std(np.array(series) - np.array(series.shift(lag)).dropna())) for lag in lags]
                if len(tau) < 3:
                    return 0.5
                poly = np.polyfit(np.log(lags[:len(tau)]), np.log(tau), 1)
                return max(0.0, min(1.0, poly[0]))
            except Exception as e:
                logger.debug(f"[SectorRotation] _hurst failed: {e}")
                return 0.5
        self._data["hurst"] = grouped["price"].transform(lambda x: x.rolling(63).apply(lambda y: _hurst(y.dropna()), raw=False))
        self._data["hurst"] = self._data["hurst"].fillna(0.5)

        self._data["regime_score"] = (
            self._data["momentum_3m"].fillna(0) * 0.3
            + self._data["sharpe_63d"].fillna(0) * 0.25
            - self._data["volatility_63d"].fillna(0) * 0.2
            + self._data["relative_strength"].fillna(0.5) * 0.15
            + (self._data["rsi_14"] / 100 * 0.05)  # RSI贡献
            + (self._data["hurst"] * 0.05)  # Hurst趋势强度
        )

        self._date_data_map = {d: group for d, group in self._data.groupby("date")}
        self._prev_selected: set = set()

    def on_data(self, data: pd.DataFrame, idx: int) -> Optional[list[dict]]:
        current_date = self._dates[idx]
        if idx % self.get_param("rebalance_days") != 0:
            return None

        day_data = self._date_data_map.get(current_date, pd.DataFrame()).copy()
        if day_data.empty:
            return None

        day_data = day_data[day_data["price"] > 0].dropna(subset=["momentum_3m"])
        if day_data.empty:
            return None

        factor = self.get_param("bull_factor")
        if "momentum_1m" in day_data.columns and pd.notna(day_data["momentum_1m"].mean()) and day_data["momentum_1m"].mean() < 0:
            factor = self.get_param("bear_factor")

        if factor not in day_data.columns:
            factor = "regime_score"

        selected = day_data.nlargest(self.get_param("hold_count"), factor)
        new_codes = set(selected["code"].tolist())

        signals = []
        to_sell = self._prev_selected - new_codes
        if to_sell:
            sell_rows = day_data[day_data["code"].isin(to_sell)]
            signals.extend([
                {"code": code, "action": "sell", "price": float(price), "reason": "行业轮出"}
                for code, price in zip(sell_rows["code"], sell_rows["price"])
            ])

        buy_list = selected[["code", "price", factor]].copy()
        buy_list["reason"] = buy_list[factor].apply(lambda x: f"{factor}={x:.4f}")
        signals.extend([
            {"code": code, "action": "buy", "price": float(price), "reason": reason}
            for code, price, reason in zip(buy_list["code"], buy_list["price"], buy_list["reason"])
        ])

        self._prev_selected = new_codes
        return signals
