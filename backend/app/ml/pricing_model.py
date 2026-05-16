"""转债定价机器学习模型"""
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import os

try:
    import joblib
    JOBLIB_AVAILABLE = True
except ImportError:
    JOBLIB_AVAILABLE = False

try:
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    from sklearn.model_selection import cross_val_score, TimeSeriesSplit
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

try:
    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False


@dataclass
class PricingPrediction:
    """定价预测结果"""
    bond_code: str
    predicted_price: float
    predicted_premium: float
    confidence_interval: Tuple[float, float]
    feature_importance: Dict[str, float]
    model_version: str
    prediction_time: datetime


@dataclass
class ModelMetrics:
    """模型评估指标"""
    mae: float
    rmse: float
    mape: float
    r2: float
    cross_val_score: float


class ConvertibleBondPricer:
    """转债定价预测模型"""
    
    def __init__(self, model_type: str = "lightgbm"):
        self.model_type = model_type
        self.model = None
        self.scaler = StandardScaler() if SKLEARN_AVAILABLE else None
        self.feature_names = []
        self.model_version = "1.0.0"
        self.is_fitted = False
        
        # 初始化模型
        self._init_model()
    
    def _init_model(self):
        """初始化模型"""
        if self.model_type == "lightgbm" and LIGHTGBM_AVAILABLE:
            self.model = lgb.LGBMRegressor(
                n_estimators=200,
                max_depth=8,
                learning_rate=0.05,
                num_leaves=31,
                min_child_samples=20,
                subsample=0.8,
                colsample_bytree=0.8,
                random_state=42,
                n_jobs=-1
            )
        elif SKLEARN_AVAILABLE:
            self.model = GradientBoostingRegressor(
                n_estimators=200,
                max_depth=8,
                learning_rate=0.05,
                min_samples_split=20,
                subsample=0.8,
                random_state=42
            )
        else:
            raise ImportError("需要安装 scikit-learn 或 lightgbm")
    
    def extract_features(self, bond_data: Dict) -> np.ndarray:
        """提取定价特征"""
        features = []
        
        # 基础特征
        features.append(bond_data.get('bond_price', 0))
        features.append(bond_data.get('stock_price', 0))
        features.append(bond_data.get('conversion_price', 0))
        features.append(bond_data.get('conversion_ratio', 0))
        
        # 转股价值
        conversion_value = bond_data.get('stock_price', 0) / bond_data.get('conversion_price', 1) * 100
        features.append(conversion_value)
        
        # 溢价率
        premium = (bond_data.get('bond_price', 100) - conversion_value) / conversion_value * 100 if conversion_value > 0 else 0
        features.append(premium)
        
        # 双低指标
        features.append(bond_data.get('bond_price', 100) + premium)
        
        # 债券特征
        features.append(bond_data.get('coupon_rate', 0))
        features.append(bond_data.get('remaining_years', 0))
        features.append(bond_data.get('face_value', 100))
        
        # 信用特征
        features.append(self._credit_rating_to_score(bond_data.get('credit_rating', 'AA')))
        
        # 市场特征
        features.append(bond_data.get('volume', 0))
        features.append(bond_data.get('turnover_rate', 0))
        features.append(bond_data.get('amihud_illiquidity', 0))
        
        # 波动率特征
        features.append(bond_data.get('stock_volatility_30d', 0))
        features.append(bond_data.get('bond_volatility_30d', 0))
        
        # 期权特征
        features.append(bond_data.get('delta', 0))
        features.append(bond_data.get('gamma', 0))
        features.append(bond_data.get('vega', 0))
        features.append(bond_data.get('theta', 0))
        
        # 宏观特征
        features.append(bond_data.get('risk_free_rate', 0.03))
        features.append(bond_data.get('credit_spread', 0.01))
        
        return np.array(features)
    
    def _credit_rating_to_score(self, rating: str) -> float:
        """信用评级转换为分数"""
        rating_map = {
            'AAA': 1.0, 'AAA-': 0.95, 'AA+': 0.90, 'AA': 0.85, 'AA-': 0.80,
            'A+': 0.75, 'A': 0.70, 'A-': 0.65, 'BBB+': 0.60, 'BBB': 0.55,
            'BBB-': 0.50, 'BB+': 0.45, 'BB': 0.40, 'BB-': 0.35,
            'B+': 0.30, 'B': 0.25, 'B-': 0.20
        }
        return rating_map.get(rating, 0.5)
    
    def fit(self, X: np.ndarray, y: np.ndarray, feature_names: List[str] = None):
        """训练模型"""
        if feature_names:
            self.feature_names = feature_names
        
        # 时间序列交叉验证
        if SKLEARN_AVAILABLE:
            tscv = TimeSeriesSplit(n_splits=5)
            cv_scores = cross_val_score(self.model, X, y, cv=tscv, scoring='neg_mean_absolute_error')
            self.cv_score = -cv_scores.mean()
        
        # 训练模型
        self.model.fit(X, y)
        self.is_fitted = True
        
        return self
    
    def predict(self, bond_data: Dict) -> PricingPrediction:
        """预测转债价格"""
        if not self.is_fitted:
            raise ValueError("模型尚未训练")
        
        features = self.extract_features(bond_data).reshape(1, -1)
        
        # 预测价格
        predicted_price = self.model.predict(features)[0]
        
        # 预测置信区间（使用bootstrap或模型内置方法）
        if hasattr(self.model, 'predict_proba'):
            # 对于支持概率预测的模型
            pred_std = np.std([est.predict(features)[0] for est in self.model.estimators_])
            confidence_interval = (
                max(0, predicted_price - 1.96 * pred_std),
                predicted_price + 1.96 * pred_std
            )
        else:
            # 简单置信区间
            confidence_interval = (predicted_price * 0.95, predicted_price * 1.05)
        
        # 预测溢价率
        conversion_value = bond_data.get('stock_price', 0) / bond_data.get('conversion_price', 1) * 100
        predicted_premium = (predicted_price - conversion_value) / conversion_value * 100 if conversion_value > 0 else 0
        
        # 特征重要性
        feature_importance = self._get_feature_importance()
        
        return PricingPrediction(
            bond_code=bond_data.get('bond_code', ''),
            predicted_price=predicted_price,
            predicted_premium=predicted_premium,
            confidence_interval=confidence_interval,
            feature_importance=feature_importance,
            model_version=self.model_version,
            prediction_time=datetime.now()
        )
    
    def predict_batch(self, bonds_data: List[Dict]) -> List[PricingPrediction]:
        """批量预测"""
        return [self.predict(bond) for bond in bonds_data]
    
    def _get_feature_importance(self) -> Dict[str, float]:
        """获取特征重要性"""
        if hasattr(self.model, 'feature_importances_'):
            importances = self.model.feature_importances_
        elif hasattr(self.model, 'coef_'):
            importances = np.abs(self.model.coef_)
        else:
            return {}
        
        if self.feature_names:
            return dict(zip(self.feature_names, importances.tolist()))
        return {f"feature_{i}": imp for i, imp in enumerate(importances)}
    
    def evaluate(self, X_test: np.ndarray, y_test: np.ndarray) -> ModelMetrics:
        """评估模型"""
        from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
        
        y_pred = self.model.predict(X_test)
        
        mae = mean_absolute_error(y_test, y_pred)
        rmse = np.sqrt(mean_squared_error(y_test, y_pred))
        mape = np.mean(np.abs((y_test - y_pred) / y_test)) * 100
        r2 = r2_score(y_test, y_pred)
        
        return ModelMetrics(
            mae=mae,
            rmse=rmse,
            mape=mape,
            r2=r2,
            cross_val_score=getattr(self, 'cv_score', 0)
        )
    
    def save(self, path: str):
        """保存模型"""
        if not JOBLIB_AVAILABLE:
            raise ImportError("需要安装joblib以保存模型")

        model_data = {
            'model': self.model,
            'scaler': self.scaler,
            'feature_names': self.feature_names,
            'model_version': self.model_version,
            'model_type': self.model_type
        }
        joblib.dump(model_data, path)

    def load(self, path: str):
        """加载模型"""
        if not JOBLIB_AVAILABLE:
            raise ImportError("需要安装joblib以加载模型")

        model_data = joblib.load(path)
        self.model = model_data['model']
        self.scaler = model_data.get('scaler')
        self.feature_names = model_data.get('feature_names', [])
        self.model_version = model_data.get('model_version', '1.0.0')
        self.is_fitted = True
        return self


class EnsemblePricer:
    """集成定价模型"""
    
    def __init__(self):
        self.models = []
        self.weights = []
    
    def add_model(self, model: ConvertibleBondPricer, weight: float = 1.0):
        """添加模型"""
        self.models.append(model)
        self.weights.append(weight)
    
    def predict(self, bond_data: Dict) -> PricingPrediction:
        """集成预测"""
        predictions = [model.predict(bond_data) for model in self.models]
        
        # 加权平均
        total_weight = sum(self.weights)
        weighted_price = sum(p.predicted_price * w for p, w in zip(predictions, self.weights)) / total_weight
        
        # 返回加权结果
        result = predictions[0]
        result.predicted_price = weighted_price
        return result
