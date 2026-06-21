"""特征工程模块"""
import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class FeatureConfig:
    """特征配置"""
    # 技术指标
    ma_periods: List[int] = None
    ema_periods: List[int] = None
    rsi_period: int = 14
    macd_params: tuple = (12, 26, 9)
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    
    # 波动率
    volatility_windows: List[int] = None
    
    # 流动性
    illiquidity_window: int = 20
    
    def __post_init__(self):
        if self.ma_periods is None:
            self.ma_periods = [5, 10, 20, 60]
        if self.ema_periods is None:
            self.ema_periods = [12, 26]
        if self.volatility_windows is None:
            self.volatility_windows = [5, 10, 20, 60]


class FeatureEngineer:
    """特征工程"""
    
    def __init__(self, config: FeatureConfig = None):
        self.config = config or FeatureConfig()
    
    def extract_all_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """提取所有特征"""
        df = df.copy()
        
        # 价格特征
        df = self._extract_price_features(df)
        
        # 技术指标
        df = self._extract_technical_indicators(df)
        
        # 波动率特征
        df = self._extract_volatility_features(df)
        
        # 流动性特征
        df = self._extract_liquidity_features(df)
        
        # 转债特有特征
        df = self._extract_convertible_features(df)
        
        # 时间特征
        df = self._extract_time_features(df)
        
        return df
    
    def _extract_price_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """提取价格特征"""
        # 收益率
        df['return_1d'] = df['close'].pct_change(1)
        df['return_5d'] = df['close'].pct_change(5)
        df['return_20d'] = df['close'].pct_change(20)
        
        # 对数收益率
        df['log_return'] = np.log(df['close'] / df['close'].shift(1))
        
        # 移动平均
        for period in self.config.ma_periods:
            df[f'ma_{period}'] = df['close'].rolling(window=period).mean()
            df[f'price_to_ma_{period}'] = df['close'] / df[f'ma_{period}']
        
        # 指数移动平均
        for period in self.config.ema_periods:
            df[f'ema_{period}'] = df['close'].ewm(span=period, adjust=False).mean()
        
        # 价格位置
        df['price_position'] = (df['close'] - df['low'].rolling(20).min()) / (
            df['high'].rolling(20).max() - df['low'].rolling(20).min()
        )
        
        return df
    
    def _extract_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """提取技术指标"""
        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']
        
        # RSI
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.config.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.config.rsi_period).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # MACD
        ema_fast = close.ewm(span=self.config.macd_params[0], adjust=False).mean()
        ema_slow = close.ewm(span=self.config.macd_params[1], adjust=False).mean()
        df['macd'] = ema_fast - ema_slow
        df['macd_signal'] = df['macd'].ewm(span=self.config.macd_params[2], adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        
        # 布林带
        ma = close.rolling(window=self.config.bollinger_period).mean()
        std = close.rolling(window=self.config.bollinger_period).std()
        df['bollinger_upper'] = ma + self.config.bollinger_std * std
        df['bollinger_lower'] = ma - self.config.bollinger_std * std
        df['bollinger_width'] = (df['bollinger_upper'] - df['bollinger_lower']) / ma
        df['bollinger_position'] = (close - df['bollinger_lower']) / (df['bollinger_upper'] - df['bollinger_lower'])
        
        # KDJ
        low_min = low.rolling(window=9).min()
        high_max = high.rolling(window=9).max()
        df['kdj_k'] = (close - low_min) / (high_max - low_min) * 100
        df['kdj_d'] = df['kdj_k'].rolling(window=3).mean()
        df['kdj_j'] = 3 * df['kdj_k'] - 2 * df['kdj_d']
        
        # ATR
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr'] = tr.rolling(window=14).mean()
        
        # OBV
        df['obv'] = (np.sign(close.diff()) * volume).cumsum()
        
        return df
    
    def _extract_volatility_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """提取波动率特征"""
        close = df['close']
        
        # 历史波动率
        log_return = np.log(close / close.shift(1))
        for window in self.config.volatility_windows:
            df[f'volatility_{window}d'] = log_return.rolling(window=window).std() * np.sqrt(252)
        
        # Parkinson波动率
        df['parkinson_vol'] = np.sqrt(
            (1 / (4 * np.log(2))) * (np.log(df['high'] / df['low']) ** 2).rolling(window=20).mean()
        ) * np.sqrt(252)
        
        # Garman-Klass波动率（防御负方差：np.sqrt 内部 clamp ≥ 0）
        garman_klass_var = (
            0.5 * (np.log(df['high'] / df['low']) ** 2).rolling(window=20).mean() -
            (2 * np.log(2) - 1) * (np.log(df['close'] / df['open']) ** 2).rolling(window=20).mean()
        )
        df['garman_klass_vol'] = np.sqrt(np.maximum(garman_klass_var, 0)) * np.sqrt(252)
        
        # 偏度和峰度
        df['return_skew'] = log_return.rolling(window=20).skew()
        df['return_kurtosis'] = log_return.rolling(window=20).kurt()
        
        # 波动率变化
        df['volatility_change'] = df['volatility_20d'].pct_change()
        
        return df
    
    def _extract_liquidity_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """提取流动性特征"""
        # Amihud非流动性
        df['amihud_illiquidity'] = (abs(df['return_1d']) / (df['volume'] + 1e-10)).rolling(
            window=self.config.illiquidity_window
        ).mean()
        
        # 换手率
        if 'turnover' in df.columns:
            df['turnover_rate'] = df['turnover']
        
        # 成交量变化
        df['volume_ma_5'] = df['volume'].rolling(window=5).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma_5']
        
        # 成交额
        df['amount'] = df['close'] * df['volume']
        df['amount_ma_5'] = df['amount'].rolling(window=5).mean()
        
        # 买卖价差
        if 'bid' in df.columns and 'ask' in df.columns:
            df['bid_ask_spread'] = (df['ask'] - df['bid']) / df['mid_price']
        
        return df
    
    def _extract_convertible_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """提取转债特有特征"""
        # 转股价值
        if 'stock_price' in df.columns and 'conversion_price' in df.columns:
            df['conversion_value'] = df['stock_price'] / df['conversion_price'] * 100
            
            # 溢价率
            df['premium_rate'] = (df['close'] - df['conversion_value']) / df['conversion_value'] * 100
            
            # 双低指标
            df['double_low'] = df['close'] + df['premium_rate']
            
            # 转股溢价率变化
            df['premium_change'] = df['premium_rate'].diff()
            
            # 股债联动性
            df['stock_bond_correlation'] = df['close'].rolling(window=20).corr(df['stock_price'])
        
        # 纯债价值
        if 'coupon_rate' in df.columns and 'remaining_years' in df.columns:
            # 简化计算：假设到期收益率
            ytm = 0.03  # 假设3%到期收益率
            df['bond_value'] = self._calculate_bond_value(
                df['coupon_rate'].iloc[0],
                df['remaining_years'].iloc[0],
                ytm
            )
        
        # 期权价值（简化）
        if 'conversion_value' in df.columns:
            df['option_value'] = df['close'] - df.get('bond_value', 0)
        
        return df
    
    def _calculate_bond_value(self, coupon_rate: float, years: float, ytm: float) -> float:
        """计算纯债价值"""
        # 简化计算：贴现现金流
        annual_coupon = coupon_rate * 100
        pv_coupons = sum(annual_coupon / (1 + ytm) ** t for t in range(1, int(years) + 1))
        pv_principal = 100 / (1 + ytm) ** years
        return pv_coupons + pv_principal
    
    def _extract_time_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """提取时间特征"""
        if 'date' in df.columns or df.index.name == 'date':
            dates = pd.to_datetime(df.index if df.index.name == 'date' else df['date'])
            
            # 月份
            df['month'] = dates.month
            
            # 季度
            df['quarter'] = dates.quarter
            
            # 周几
            df['day_of_week'] = dates.dayofweek
            
            # 是否月末
            df['is_month_end'] = dates.is_month_end.astype(int)
            
            # 是否季末
            df['is_quarter_end'] = dates.is_quarter_end.astype(int)
            
            # 年内天数
            df['day_of_year'] = dates.dayofyear
        
        return df
    
    def generate_lagged_features(self, df: pd.DataFrame, columns: List[str], 
                                  lags: List[int]) -> pd.DataFrame:
        """生成滞后特征"""
        for col in columns:
            for lag in lags:
                df[f'{col}_lag_{lag}'] = df[col].shift(lag)
        return df
    
    def generate_rolling_features(self, df: pd.DataFrame, columns: List[str],
                                   windows: List[int], agg_funcs: List[str]) -> pd.DataFrame:
        """生成滚动特征"""
        for col in columns:
            for window in windows:
                for func in agg_funcs:
                    if func == 'mean':
                        df[f'{col}_rolling_mean_{window}'] = df[col].rolling(window=window).mean()
                    elif func == 'std':
                        df[f'{col}_rolling_std_{window}'] = df[col].rolling(window=window).std()
                    elif func == 'min':
                        df[f'{col}_rolling_min_{window}'] = df[col].rolling(window=window).min()
                    elif func == 'max':
                        df[f'{col}_rolling_max_{window}'] = df[col].rolling(window=window).max()
        return df
    
    def select_features(self, df: pd.DataFrame, method: str = 'importance',
                        n_features: int = 50) -> List[str]:
        """特征选择"""
        if method == 'importance':
            # 基于特征重要性选择
            from sklearn.ensemble import RandomForestRegressor
            
            # 准备数据
            df_clean = df.dropna()
            X = df_clean.select_dtypes(include=[np.number])
            y = df_clean['return_1d'].shift(-1).dropna()
            X = X.iloc[:-1]
            
            # 训练模型获取重要性
            rf = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
            rf.fit(X, y)
            
            # 选择top特征
            importance = pd.Series(rf.feature_importances_, index=X.columns)
            selected = importance.nlargest(n_features).index.tolist()
            
            return selected
        
        elif method == 'correlation':
            # 基于相关性选择
            corr_matrix = df.corr()
            target_corr = corr_matrix['return_1d'].abs().sort_values(ascending=False)
            return target_corr.head(n_features).index.tolist()
        
        return list(df.columns)
