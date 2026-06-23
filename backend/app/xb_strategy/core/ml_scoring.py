"""西部量化可转债策略 V3.0 机器学习增强打分模块

功能:
- 特征工程
- 模型训练 (XGBoost/LightGBM/随机森林)
- 模型预测
- 特征重要性分析
- 模型评估
- 超参数优化
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Dict, Optional, Tuple, Any
import numpy as np
import pandas as pd
import logging
import json
import os
import pickle

logger = logging.getLogger(__name__)

# 检查ML库是否可用
try:
    from sklearn.model_selection import train_test_split, cross_val_score, GridSearchCV
    from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
    from sklearn.preprocessing import StandardScaler, MinMaxScaler
    from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

try:
    import xgboost as xgb
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False

try:
    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False


# ============ 数据类型 ============

@dataclass
class FeatureConfig:
    """特征配置"""
    # 转债特征
    use_conversion_premium: bool = True
    use_remaining_years: bool = True
    use_liquidity: bool = True
    use_ytm: bool = True
    use_pure_bond_premium: bool = True

    # 正股特征
    use_stock_momentum: bool = True
    use_stock_volume: bool = True
    use_stock_turnover: bool = True
    use_stock_pe: bool = True
    use_stock_pb: bool = True

    # 技术指标
    use_ma_features: bool = True
    use_macd_features: bool = True
    use_volatility: bool = True

    # 市场特征
    use_market_sentiment: bool = True
    use_sector_features: bool = True


@dataclass
class ModelConfig:
    """模型配置"""
    model_type: str = "xgboost"  # xgboost/lightgbm/random_forest
    test_size: float = 0.2
    cv_folds: int = 5
    random_state: int = 42

    # XGBoost参数
    xgb_params: Dict = field(default_factory=lambda: {
        "n_estimators": 200,
        "max_depth": 6,
        "learning_rate": 0.1,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "objective": "reg:squarederror",
        "random_state": 42,
    })

    # LightGBM参数
    lgb_params: Dict = field(default_factory=lambda: {
        "n_estimators": 200,
        "max_depth": 6,
        "learning_rate": 0.1,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "objective": "regression",
        "random_state": 42,
    })

    # RandomForest参数
    rf_params: Dict = field(default_factory=lambda: {
        "n_estimators": 200,
        "max_depth": 10,
        "min_samples_split": 5,
        "min_samples_leaf": 2,
        "random_state": 42,
    })


@dataclass
class TrainingResult:
    """训练结果"""
    model_type: str
    train_score: float
    test_score: float
    cv_score: float
    feature_importance: Dict[str, float]
    training_time: float
    feature_count: int
    sample_count: int

    def to_dict(self) -> dict:
        return {
            "model_type": self.model_type,
            "train_score": round(self.train_score, 4),
            "test_score": round(self.test_score, 4),
            "cv_score": round(self.cv_score, 4),
            "feature_importance": {k: round(v, 4) for k, v in self.feature_importance.items()},
            "training_time": round(self.training_time, 2),
            "feature_count": self.feature_count,
            "sample_count": self.sample_count,
        }


@dataclass
class PredictionResult:
    """预测结果"""
    cb_code: str
    predicted_score: float
    confidence: float
    feature_values: Dict[str, float]
    top_features: List[Tuple[str, float]]

    def to_dict(self) -> dict:
        return {
            "cb_code": self.cb_code,
            "predicted_score": round(self.predicted_score, 2),
            "confidence": round(self.confidence, 4),
            "feature_values": {k: round(v, 4) for k, v in self.feature_values.items()},
            "top_features": [(k, round(v, 4)) for k, v in self.top_features],
        }


# ============ 特征工程 ============

class FeatureEngineer:
    """特征工程"""

    def __init__(self, config: FeatureConfig = None):
        """初始化

        Args:
            config: 特征配置
        """
        self.config = config or FeatureConfig()
        self._feature_names: List[str] = []
        self._scaler = None

    def extract_features(
        self,
        cb_data: pd.DataFrame,
        stock_data: Optional[pd.DataFrame] = None,
        market_data: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """提取特征

        Args:
            cb_data: 可转债数据
            stock_data: 正股数据
            market_data: 市场数据

        Returns:
            特征DataFrame
        """
        features = pd.DataFrame()
        features['code'] = cb_data['code']

        # 1. 转债基础特征
        if self.config.use_conversion_premium:
            features['conversion_premium'] = cb_data.get('conversion_premium', 0)
            features['conversion_premium_rank'] = cb_data.get('conversion_premium', 0).rank(pct=True)

        if self.config.use_remaining_years:
            features['remaining_years'] = cb_data.get('remaining_years', 3)
            features['remaining_years_rank'] = cb_data.get('remaining_years', 3).rank(pct=True)

        if self.config.use_liquidity:
            features['daily_amount'] = cb_data.get('daily_amount_20d', 0)
            features['liquidity_rank'] = cb_data.get('daily_amount_20d', 0).rank(pct=True)
            features['turnover_rate'] = cb_data.get('turnover_rate', 0)

        if self.config.use_ytm:
            features['ytm'] = cb_data.get('ytm', 0)
            features['ytm_rank'] = cb_data.get('ytm', 0).rank(pct=True)

        if self.config.use_pure_bond_premium:
            features['pure_bond_premium'] = cb_data.get('pure_bond_premium', 0)

        # 2. 正股特征
        if stock_data is not None and self.config.use_stock_momentum:
            features = features.merge(
                stock_data[['code', 'change_pct', 'volume_ratio', 'turnover_rate', 'pe', 'pb']].rename(
                    columns={'code': 'stock_code'}
                ),
                left_on=cb_data['stock_code'],
                right_on='stock_code',
                how='left',
                suffixes=('', '_stock')
            )

            features['stock_momentum'] = features.get('change_pct_stock', 0)
            features['stock_volume_ratio'] = features.get('volume_ratio', 1)
            features['stock_turnover'] = features.get('turnover_rate_stock', 0)
            features['stock_pe'] = features.get('pe', 0)
            features['stock_pb'] = features.get('pb', 0)

        # 3. 技术指标特征
        if self.config.use_ma_features:
            close = cb_data.get('close')
            ma5 = cb_data.get('ma5')
            ma10 = cb_data.get('ma10')
            ma20 = cb_data.get('ma20')
            features['price_ma5_ratio'] = close / ma5 if close is not None and ma5 is not None and ma5 != 0 else 1.0
            features['price_ma10_ratio'] = close / ma10 if close is not None and ma10 is not None and ma10 != 0 else 1.0
            features['price_ma20_ratio'] = close / ma20 if close is not None and ma20 is not None and ma20 != 0 else 1.0

        if self.config.use_volatility:
            features['volatility_20d'] = cb_data.get('volatility_20d', 0)
            features['iv_percentile'] = cb_data.get('implied_vol_percentile', 50)

        # 4. 市场特征
        if market_data is not None and self.config.use_market_sentiment:
            features['market_change'] = market_data.get('index_change_pct', 0)

        # 5. 派生特征
        features['premium_to_years'] = features.get('conversion_premium', 0) / (features.get('remaining_years', 1) + 0.1)
        features['amount_to_premium'] = features.get('daily_amount', 0) / (features.get('conversion_premium', 1) + 1)

        # 填充缺失值
        features = features.fillna(0)

        # 记录特征名
        self._feature_names = [c for c in features.columns if c not in ['code', 'stock_code']]

        return features

    def fit_transform(self, features: pd.DataFrame) -> np.ndarray:
        """拟合并转换特征

        Args:
            features: 特征DataFrame

        Returns:
            标准化后的特征数组
        """
        if not SKLEARN_AVAILABLE:
            return features[self._feature_names].values

        X = features[self._feature_names].values
        self._scaler = StandardScaler()
        return self._scaler.fit_transform(X)

    def transform(self, features: pd.DataFrame) -> np.ndarray:
        """转换特征

        Args:
            features: 特征DataFrame

        Returns:
            标准化后的特征数组
        """
        if self._scaler is None:
            return features[self._feature_names].values
        return self._scaler.transform(features[self._feature_names].values)

    def get_feature_names(self) -> List[str]:
        """获取特征名列表"""
        return self._feature_names


# ============ 模型训练器 ============

class MLScoringModel:
    """机器学习打分模型"""

    def __init__(self, config: ModelConfig = None):
        """初始化

        Args:
            config: 模型配置
        """
        self.config = config or ModelConfig()
        self.model = None
        self.feature_engineer = FeatureEngineer()
        self._is_trained = False
        self._training_result: Optional[TrainingResult] = None

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: List[str],
    ) -> TrainingResult:
        """训练模型

        Args:
            X: 特征数组
            y: 标签数组
            feature_names: 特征名列表

        Returns:
            训练结果
        """
        import time
        start_time = time.time()

        if not SKLEARN_AVAILABLE:
            logger.warning("sklearn未安装，无法训练模型")
            return TrainingResult("none", 0, 0, 0, {}, 0, 0, 0)

        # 划分训练集和测试集
        X_train, X_test, y_train, y_test = train_test_split(
            X, y,
            test_size=self.config.test_size,
            random_state=self.config.random_state,
        )

        # 选择模型
        if self.config.model_type == "xgboost" and XGBOOST_AVAILABLE:
            self.model = xgb.XGBRegressor(**self.config.xgb_params)
        elif self.config.model_type == "lightgbm" and LIGHTGBM_AVAILABLE:
            self.model = lgb.LGBMRegressor(**self.config.lgb_params)
        elif SKLEARN_AVAILABLE:
            self.model = RandomForestRegressor(**self.config.rf_params)
            self.config.model_type = "random_forest"
        else:
            logger.warning("没有可用的ML库")
            return TrainingResult("none", 0, 0, 0, {}, 0, 0, 0)

        # 训练模型
        self.model.fit(X_train, y_train)

        # 评估
        train_pred = self.model.predict(X_train)
        test_pred = self.model.predict(X_test)

        train_score = r2_score(y_train, train_pred)
        test_score = r2_score(y_test, test_pred)

        # 交叉验证
        cv_scores = cross_val_score(self.model, X, y, cv=self.config.cv_folds, scoring='r2')
        cv_score = cv_scores.mean()

        # 特征重要性
        feature_importance = {}
        if hasattr(self.model, 'feature_importances_'):
            for name, importance in zip(feature_names, self.model.feature_importances_):
                feature_importance[name] = float(importance)

        training_time = time.time() - start_time

        self._is_trained = True
        self._training_result = TrainingResult(
            model_type=self.config.model_type,
            train_score=train_score,
            test_score=test_score,
            cv_score=cv_score,
            feature_importance=feature_importance,
            training_time=training_time,
            feature_count=len(feature_names),
            sample_count=len(y),
        )

        logger.info(f"[MLScoring] 训练完成: {self.config.model_type}, R2={test_score:.4f}")

        return self._training_result

    def predict(
        self,
        X: np.ndarray,
        cb_codes: List[str],
        feature_values: Optional[pd.DataFrame] = None,
    ) -> List[PredictionResult]:
        """预测得分

        Args:
            X: 特征数组
            cb_codes: 转债代码列表
            feature_values: 特征值DataFrame（用于解释）

        Returns:
            预测结果列表
        """
        if not self._is_trained or self.model is None:
            return []

        predictions = self.model.predict(X)
        results = []

        feature_names = self.feature_engineer.get_feature_names()
        importance = self._training_result.feature_importance if self._training_result else {}
        sorted_features = sorted(importance.items(), key=lambda x: x[1], reverse=True)

        for i, code in enumerate(cb_codes):
            pred_score = predictions[i]

            # 计算置信度（基于预测值的稳定性）
            confidence = min(1.0, max(0.0, 1.0 - abs(pred_score - 50) / 100))

            # 特征值
            feat_values = {}
            if feature_values is not None and i < len(feature_values):
                for name in feature_names:
                    if name in feature_values.columns:
                        feat_values[name] = feature_values.iloc[i].get(name, 0)

            # Top特征
            top_features = sorted_features[:5]

            results.append(PredictionResult(
                cb_code=code,
                predicted_score=float(pred_score),
                confidence=confidence,
                feature_values=feat_values,
                top_features=top_features,
            ))

        return results

    def save_model(self, path: str):
        """保存模型

        Args:
            path: 保存路径
        """
        if self.model is None:
            return

        model_data = {
            "model": self.model,
            "config": self.config.__dict__,
            "feature_names": self.feature_engineer.get_feature_names(),
            "training_result": self._training_result.to_dict() if self._training_result else None,
        }

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            pickle.dump(model_data, f)

        logger.info(f"[MLScoring] 模型已保存: {path}")

    def load_model(self, path: str):
        """加载模型

        Args:
            path: 模型路径
        """
        with open(path, 'rb') as f:
            model_data = pickle.load(f)

        self.model = model_data["model"]
        self.feature_engineer._feature_names = model_data["feature_names"]
        self._is_trained = True

        logger.info(f"[MLScoring] 模型已加载: {path}")


# ============ ML打分增强器 ============

class MLScoringEnhancer:
    """机器学习打分增强器"""

    def __init__(self, model_config: ModelConfig = None, feature_config: FeatureConfig = None):
        """初始化

        Args:
            model_config: 模型配置
            feature_config: 特征配置
        """
        self.feature_engineer = FeatureEngineer(feature_config)
        self.model = MLScoringModel(model_config)
        self._trained = False

    def prepare_training_data(
        self,
        historical_data: pd.DataFrame,
        labels: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray, List[str]]:
        """准备训练数据

        Args:
            historical_data: 历史数据
            labels: 标签（如未来收益率）

        Returns:
            (特征数组, 标签数组, 特征名列表)
        """
        features = self.feature_engineer.extract_features(historical_data)
        X = self.feature_engineer.fit_transform(features)
        feature_names = self.feature_engineer.get_feature_names()

        return X, labels, feature_names

    def train(
        self,
        historical_data: pd.DataFrame,
        labels: np.ndarray,
    ) -> TrainingResult:
        """训练模型

        Args:
            historical_data: 历史数据
            labels: 标签

        Returns:
            训练结果
        """
        X, y, feature_names = self.prepare_training_data(historical_data, labels)
        result = self.model.train(X, y, feature_names)
        self._trained = True
        return result

    def enhance_scores(
        self,
        cb_data: pd.DataFrame,
        base_scores: np.ndarray,
        stock_data: Optional[pd.DataFrame] = None,
        market_data: Optional[pd.DataFrame] = None,
        blend_ratio: float = 0.3,
    ) -> np.ndarray:
        """增强得分

        Args:
            cb_data: 可转债数据
            base_scores: 基础得分（七维得分）
            stock_data: 正股数据
            market_data: 市场数据
            blend_ratio: 混合比例 (ML得分权重)

        Returns:
            增强后的得分
        """
        if not self._trained:
            return base_scores

        # 提取特征
        features = self.feature_engineer.extract_features(cb_data, stock_data, market_data)
        X = self.feature_engineer.transform(features)

        # 预测
        predictions = self.model.predict(X, cb_data['code'].tolist(), features)
        ml_scores = np.array([p.predicted_score for p in predictions])

        # 混合得分
        # 将ML得分归一化到与base_scores相同的范围
        ml_min, ml_max = ml_scores.min(), ml_scores.max()
        base_min, base_max = base_scores.min(), base_scores.max()

        if ml_max > ml_min:
            ml_normalized = (ml_scores - ml_min) / (ml_max - ml_min) * (base_max - base_min) + base_min
        else:
            ml_normalized = base_scores

        enhanced_scores = base_scores * (1 - blend_ratio) + ml_normalized * blend_ratio

        return enhanced_scores

    def get_feature_importance(self) -> Dict[str, float]:
        """获取特征重要性"""
        if self._trained and self.model._training_result:
            return self.model._training_result.feature_importance
        return {}

    def save(self, path: str):
        """保存模型"""
        self.model.save_model(path)

    def load(self, path: str):
        """加载模型"""
        self.model.load_model(path)
        self._trained = True
