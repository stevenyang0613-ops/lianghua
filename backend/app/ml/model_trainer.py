"""模型训练流水线"""
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import json
import os

try:
    import mlflow
    import mlflow.sklearn
    MLFLOW_AVAILABLE = True
except ImportError:
    MLFLOW_AVAILABLE = False

try:
    import optuna
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False


@dataclass
class TrainingConfig:
    """训练配置"""
    # 数据配置
    train_ratio: float = 0.7
    val_ratio: float = 0.15
    test_ratio: float = 0.15
    
    # 特征配置
    feature_selection_method: str = 'importance'
    n_features: int = 50
    
    # 模型配置
    model_type: str = 'lightgbm'
    hyperparameter_tuning: bool = True
    n_trials: int = 50
    
    # 训练配置
    random_state: int = 42
    n_jobs: int = -1
    
    # MLflow配置
    experiment_name: str = "convertible_bond_pricing"
    tracking_uri: str = "http://localhost:5000"


@dataclass
class TrainingResult:
    """训练结果"""
    model_id: str
    model_version: str
    metrics: Dict[str, float]
    feature_importance: Dict[str, float]
    training_time: float
    config: TrainingConfig
    best_params: Dict


class ModelTrainer:
    """模型训练器"""
    
    def __init__(self, config: TrainingConfig = None):
        self.config = config or TrainingConfig()
        self.model = None
        self.best_params = {}
        
        # 初始化MLflow
        if MLFLOW_AVAILABLE:
            mlflow.set_tracking_uri(self.config.tracking_uri)
            mlflow.set_experiment(self.config.experiment_name)
    
    def prepare_data(self, df: pd.DataFrame, 
                     target_col: str = 'return_1d') -> Tuple[np.ndarray, np.ndarray]:
        """准备训练数据"""
        # 删除NaN
        df_clean = df.dropna()
        
        # 分离特征和目标
        feature_cols = [col for col in df_clean.columns 
                       if col != target_col and df_clean[col].dtype in [np.float64, np.int64]]
        
        X = df_clean[feature_cols].values
        y = df_clean[target_col].values
        
        return X, y, feature_cols
    
    def split_data(self, X: np.ndarray, y: np.ndarray) -> Tuple:
        """分割数据集"""
        n_samples = len(X)
        train_end = int(n_samples * self.config.train_ratio)
        val_end = int(n_samples * (self.config.train_ratio + self.config.val_ratio))
        
        X_train = X[:train_end]
        y_train = y[:train_end]
        
        X_val = X[train_end:val_end]
        y_val = y[train_end:val_end]
        
        X_test = X[val_end:]
        y_test = y[val_end:]
        
        return X_train, X_val, X_test, y_train, y_val, y_test
    
    def objective(self, trial, X_train, y_train, X_val, y_val):
        """Optuna优化目标函数"""
        from sklearn.metrics import mean_squared_error
        
        # 定义超参数搜索空间
        if self.config.model_type == 'lightgbm':
            import lightgbm as lgb
            
            params = {
                'n_estimators': trial.suggest_int('n_estimators', 50, 500),
                'max_depth': trial.suggest_int('max_depth', 3, 12),
                'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3, log=True),
                'num_leaves': trial.suggest_int('num_leaves', 20, 100),
                'min_child_samples': trial.suggest_int('min_child_samples', 5, 50),
                'subsample': trial.suggest_float('subsample', 0.6, 1.0),
                'colsample_bytree': trial.suggest_float('colsample_bytree', 0.6, 1.0),
                'reg_alpha': trial.suggest_float('reg_alpha', 1e-8, 10.0, log=True),
                'reg_lambda': trial.suggest_float('reg_lambda', 1e-8, 10.0, log=True),
            }
            
            model = lgb.LGBMRegressor(**params, random_state=self.config.random_state)
        
        else:
            from sklearn.ensemble import GradientBoostingRegressor
            
            params = {
                'n_estimators': trial.suggest_int('n_estimators', 50, 500),
                'max_depth': trial.suggest_int('max_depth', 3, 12),
                'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3, log=True),
                'min_samples_split': trial.suggest_int('min_samples_split', 2, 50),
                'min_samples_leaf': trial.suggest_int('min_samples_leaf', 1, 30),
                'subsample': trial.suggest_float('subsample', 0.6, 1.0),
            }
            
            model = GradientBoostingRegressor(**params, random_state=self.config.random_state)
        
        # 训练
        model.fit(X_train, y_train)
        
        # 验证
        y_pred = model.predict(X_val)
        mse = mean_squared_error(y_val, y_pred)
        
        return mse
    
    def train(self, df: pd.DataFrame, target_col: str = 'return_1d') -> TrainingResult:
        """训练模型"""
        start_time = datetime.now()
        
        # 准备数据
        X, y, feature_cols = self.prepare_data(df, target_col)
        X_train, X_val, X_test, y_train, y_val, y_test = self.split_data(X, y)
        
        # 超参数优化
        if self.config.hyperparameter_tuning and OPTUNA_AVAILABLE:
            study = optuna.create_study(direction='minimize')
            study.optimize(
                lambda trial: self.objective(trial, X_train, y_train, X_val, y_val),
                n_trials=self.config.n_trials,
                n_jobs=self.config.n_jobs
            )
            self.best_params = study.best_params
        
        # 使用最佳参数训练最终模型
        if self.config.model_type == 'lightgbm':
            import lightgbm as lgb
            self.model = lgb.LGBMRegressor(**self.best_params, random_state=self.config.random_state)
        else:
            from sklearn.ensemble import GradientBoostingRegressor
            self.model = GradientBoostingRegressor(**self.best_params, random_state=self.config.random_state)
        
        # 合并训练集和验证集
        X_train_full = np.vstack([X_train, X_val])
        y_train_full = np.hstack([y_train, y_val])
        
        # 训练
        self.model.fit(X_train_full, y_train_full)
        
        # 评估
        from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
        
        y_pred_test = self.model.predict(X_test)
        metrics = {
            'mae': mean_absolute_error(y_test, y_pred_test),
            'rmse': np.sqrt(mean_squared_error(y_test, y_pred_test)),
            'r2': r2_score(y_test, y_pred_test),
        }
        
        # 特征重要性
        feature_importance = dict(zip(feature_cols, self.model.feature_importances_.tolist()))
        
        # 计算训练时间
        training_time = (datetime.now() - start_time).total_seconds()
        
        # 生成模型ID
        model_id = f"model_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        model_version = "1.0.0"
        
        return TrainingResult(
            model_id=model_id,
            model_version=model_version,
            metrics=metrics,
            feature_importance=feature_importance,
            training_time=training_time,
            config=self.config,
            best_params=self.best_params
        )
    
    def train_with_mlflow(self, df: pd.DataFrame, target_col: str = 'return_1d') -> TrainingResult:
        """使用MLflow记录训练"""
        if not MLFLOW_AVAILABLE:
            return self.train(df, target_col)
        
        with mlflow.start_run():
            # 记录配置
            mlflow.log_params({
                'model_type': self.config.model_type,
                'train_ratio': self.config.train_ratio,
                'feature_selection': self.config.feature_selection_method,
            })
            
            # 训练
            result = self.train(df, target_col)
            
            # 记录指标
            mlflow.log_metrics(result.metrics)
            
            # 记录最佳参数
            mlflow.log_params(result.best_params)
            
            # 保存模型
            mlflow.sklearn.log_model(self.model, "model")
            
            # 记录特征重要性
            mlflow.log_dict(result.feature_importance, "feature_importance.json")
            
            return result
    
    def save_model(self, path: str):
        """保存模型"""
        import joblib
        joblib.dump(self.model, path)
    
    def load_model(self, path: str):
        """加载模型"""
        import joblib
        self.model = joblib.load(path)
        return self.model


class OnlineLearner:
    """在线学习器"""
    
    def __init__(self, model, update_frequency: int = 100):
        self.model = model
        self.update_frequency = update_frequency
        self.samples_seen = 0
        self.buffer_X = []
        self.buffer_y = []
    
    def partial_fit(self, X: np.ndarray, y: np.ndarray):
        """增量学习"""
        self.buffer_X.append(X)
        self.buffer_y.append(y)
        self.samples_seen += len(X)
        
        # 达到更新频率时更新模型
        if self.samples_seen % self.update_frequency == 0:
            X_batch = np.vstack(self.buffer_X)
            y_batch = np.hstack(self.buffer_y)
            
            if hasattr(self.model, 'partial_fit'):
                self.model.partial_fit(X_batch, y_batch)
            else:
                # 对于不支持增量学习的模型，重新训练
                self.model.fit(X_batch, y_batch)
            
            # 清空缓冲区
            self.buffer_X = []
            self.buffer_y = []
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        """预测"""
        return self.model.predict(X)
