"""西部量化可转债策略 V3.0 机器学习平台集成模块

功能:
- MLflow集成
- 模型版本管理
- 特征存储
- 实验追踪
- 模型部署
- 超参数优化
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, Callable
from enum import Enum
import logging
import functools
import os
import json
import pickle
import time
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 检查MLflow是否可用
try:
    import mlflow
    import mlflow.sklearn
    import mlflow.xgboost
    import mlflow.lightgbm
    from mlflow.tracking import MlflowClient
    from mlflow.entities import ViewType
    MLFLOW_AVAILABLE = True
except ImportError:
    MLFLOW_AVAILABLE = False

# 检查Feature Store
try:
    from feast import FeatureStore
    FEAST_AVAILABLE = True
except ImportError:
    FEAST_AVAILABLE = False


# ============ 枚举类型 ============

class ModelStage(str, Enum):
    """模型阶段"""
    NONE = "None"
    STAGING = "Staging"
    PRODUCTION = "Production"
    ARCHIVED = "Archived"


class MetricType(str, Enum):
    """指标类型"""
    ACCURACY = "accuracy"
    PRECISION = "precision"
    RECALL = "recall"
    F1 = "f1"
    AUC = "auc"
    RMSE = "rmse"
    MAE = "mae"
    R2 = "r2"


# ============ 配置类 ============

@dataclass
class MLflowConfig:
    """MLflow配置"""
    # 跟踪服务器
    tracking_uri: str = "http://localhost:5000"
    registry_uri: str = None  # 默认与tracking_uri相同

    # 实验配置
    experiment_name: str = "xb_strategy"
    default_artifact_root: str = "mlruns"

    # 模型注册
    model_name: str = "sg_scoring_model"
    auto_register: bool = True

    # 特征存储
    feast_repo_path: str = "feature_repo"


@dataclass
class ExperimentConfig:
    """实验配置"""
    name: str
    description: str = ""
    tags: Dict[str, str] = field(default_factory=dict)


@dataclass
class RunConfig:
    """运行配置"""
    run_name: str = ""
    description: str = ""
    tags: Dict[str, str] = field(default_factory=dict)
    params: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, float] = field(default_factory=dict)


# ============ MLflow管理器 ============

class MLflowManager:
    """MLflow管理器"""

    _instance = None

    def __new__(cls, config: MLflowConfig = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: MLflowConfig = None):
        if self._initialized:
            return

        self.config = config or MLflowConfig()
        self._client = None
        self._experiment_id = None

        if MLFLOW_AVAILABLE:
            self._init_mlflow()

        self._initialized = True

    def _init_mlflow(self):
        """初始化MLflow"""
        # 设置跟踪URI
        mlflow.set_tracking_uri(self.config.tracking_uri)

        # 创建客户端
        self._client = MlflowClient(
            tracking_uri=self.config.tracking_uri,
            registry_uri=self.config.registry_uri,
        )

        # 获取或创建实验
        experiment = self._client.get_experiment_by_name(self.config.experiment_name)
        if experiment is None:
            self._experiment_id = self._client.create_experiment(
                name=self.config.experiment_name,
                artifact_location=os.path.join(
                    self.config.default_artifact_root,
                    self.config.experiment_name,
                ),
            )
        else:
            self._experiment_id = experiment.experiment_id

        mlflow.set_experiment(self.config.experiment_name)

        logger.info(f"[MLflow] 初始化完成: {self.config.tracking_uri}")

    def start_run(
        self,
        run_name: str = None,
        description: str = "",
        tags: Dict[str, str] = None,
    ):
        """开始运行"""
        if not MLFLOW_AVAILABLE:
            return NoOpRun()

        return mlflow.start_run(
            run_name=run_name,
            description=description,
            tags=tags,
        )

    def log_params(self, params: Dict[str, Any]):
        """记录参数"""
        if MLFLOW_AVAILABLE:
            mlflow.log_params(params)

    def log_metrics(self, metrics: Dict[str, float], step: int = None):
        """记录指标"""
        if MLFLOW_AVAILABLE:
            mlflow.log_metrics(metrics, step=step)

    def log_metric(self, key: str, value: float, step: int = None):
        """记录单个指标"""
        if MLFLOW_AVAILABLE:
            mlflow.log_metric(key, value, step=step)

    def log_model(
        self,
        model: Any,
        artifact_path: str = "model",
        model_type: str = "sklearn",
        **kwargs,
    ):
        """记录模型"""
        if not MLFLOW_AVAILABLE:
            return

        if model_type == "sklearn":
            mlflow.sklearn.log_model(model, artifact_path, **kwargs)
        elif model_type == "xgboost":
            mlflow.xgboost.log_model(model, artifact_path, **kwargs)
        elif model_type == "lightgbm":
            mlflow.lightgbm.log_model(model, artifact_path, **kwargs)
        else:
            # 通用保存
            model_path = os.path.join(mlflow.get_artifact_uri(), artifact_path)
            os.makedirs(model_path, exist_ok=True)
            with open(os.path.join(model_path, "model.pkl"), "wb") as f:
                pickle.dump(model, f)

        logger.info(f"[MLflow] 模型已记录: {artifact_path}")

    def log_artifact(self, local_path: str, artifact_path: str = None):
        """记录产物"""
        if MLFLOW_AVAILABLE:
            mlflow.log_artifact(local_path, artifact_path)

    def log_artifacts(self, local_dir: str, artifact_path: str = None):
        """记录产物目录"""
        if MLFLOW_AVAILABLE:
            mlflow.log_artifacts(local_dir, artifact_path)

    def log_figure(self, figure: Any, artifact_file: str):
        """记录图表"""
        if MLFLOW_AVAILABLE:
            mlflow.log_figure(figure, artifact_file)

    def register_model(
        self,
        model_name: str = None,
        model_uri: str = None,
        tags: Dict[str, str] = None,
        description: str = None,
    ) -> Optional[str]:
        """注册模型"""
        if not MLFLOW_AVAILABLE:
            return None

        model_name = model_name or self.config.model_name

        if model_uri is None:
            model_uri = f"runs:/{mlflow.active_run().info.run_id}/model"

        try:
            result = self._client.create_model_version(
                name=model_name,
                source=model_uri,
                tags=tags,
                description=description,
            )
            logger.info(f"[MLflow] 模型已注册: {model_name}, version: {result.version}")
            return result.version

        except Exception as e:
            # 如果模型不存在，先创建
            if "NOT_FOUND" in str(e) or "does not exist" in str(e):
                self._client.create_registered_model(model_name)
                return self.register_model(model_name, model_uri, tags, description)

            logger.error(f"[MLflow] 模型注册失败: {e}")
            return None

    def transition_model(
        self,
        model_name: str,
        version: str,
        stage: ModelStage,
    ):
        """转换模型阶段"""
        if not MLFLOW_AVAILABLE:
            return

        self._client.transition_model_version_stage(
            name=model_name,
            version=version,
            stage=stage.value,
        )

        logger.info(f"[MLflow] 模型阶段转换: {model_name} v{version} -> {stage.value}")

    def load_model(
        self,
        model_name: str = None,
        version: str = None,
        stage: ModelStage = ModelStage.PRODUCTION,
    ):
        """加载模型"""
        if not MLFLOW_AVAILABLE:
            return None

        model_name = model_name or self.config.model_name

        if version:
            model_uri = f"models:/{model_name}/{version}"
        else:
            model_uri = f"models:/{model_name}/{stage.value}"

        try:
            return mlflow.pyfunc.load_model(model_uri)
        except Exception as e:
            logger.error(f"[MLflow] 加载模型失败: {e}")
            return None

    def get_model_versions(
        self,
        model_name: str = None,
        stages: List[ModelStage] = None,
    ) -> List[Dict]:
        """获取模型版本列表"""
        if not MLFLOW_AVAILABLE:
            return []

        model_name = model_name or self.config.model_name

        filter_string = ""
        if stages:
            stage_list = [f"'{s.value}'" for s in stages]
            filter_string = f"current_stage IN ({','.join(stage_list)})"

        versions = self._client.search_model_versions(
            filter_string=f"name='{model_name}'"
        )

        return [
            {
                "version": v.version,
                "stage": v.current_stage,
                "creation_timestamp": datetime.fromtimestamp(
                    v.creation_timestamp / 1000
                ).isoformat(),
                "last_updated_timestamp": datetime.fromtimestamp(
                    v.last_updated_timestamp / 1000
                ).isoformat(),
                "description": v.description,
                "run_id": v.run_id,
            }
            for v in versions
        ]

    def get_best_run(
        self,
        metric_name: str,
        max_results: int = 5,
        ascending: bool = True,
    ) -> List[Dict]:
        """获取最佳运行"""
        if not MLFLOW_AVAILABLE:
            return []

        order = "ASC" if ascending else "DESC"

        runs = self._client.search_runs(
            experiment_ids=[self._experiment_id],
            filter_string=f"metrics.{metric_name} IS NOT NULL",
            order_by=[f"metrics.{metric_name} {order}"],
            max_results=max_results,
        )

        return [
            {
                "run_id": run.info.run_id,
                "run_name": run.data.tags.get("mlflow.runName", ""),
                "metrics": run.data.metrics,
                "params": run.data.params,
                "start_time": datetime.fromtimestamp(
                    run.info.start_time / 1000
                ).isoformat() if run.info.start_time else None,
            }
            for run in runs
        ]

    def search_runs(
        self,
        filter_string: str = "",
        max_results: int = 100,
    ) -> List[Dict]:
        """搜索运行"""
        if not MLFLOW_AVAILABLE:
            return []

        runs = self._client.search_runs(
            experiment_ids=[self._experiment_id],
            filter_string=filter_string,
            max_results=max_results,
        )

        return [
            {
                "run_id": run.info.run_id,
                "run_name": run.data.tags.get("mlflow.runName", ""),
                "status": run.info.status,
                "metrics": run.data.metrics,
                "params": run.data.params,
            }
            for run in runs
        ]

    def delete_run(self, run_id: str):
        """删除运行"""
        if MLFLOW_AVAILABLE:
            self._client.delete_run(run_id)

    def end_run(self, status: str = "FINISHED"):
        """结束运行"""
        if MLFLOW_AVAILABLE:
            mlflow.end_run(status)


class NoOpRun:
    """空操作运行"""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


# ============ 特征存储管理器 ============

class FeatureStoreManager:
    """特征存储管理器"""

    def __init__(self, repo_path: str = None):
        self.repo_path = repo_path or "feature_repo"
        self._store = None

        if FEAST_AVAILABLE:
            self._init_store()

    def _init_store(self):
        """初始化特征存储"""
        try:
            self._store = FeatureStore(repo_path=self.repo_path)
            logger.info(f"[FeatureStore] 初始化完成: {self.repo_path}")
        except Exception as e:
            logger.warning(f"[FeatureStore] 初始化失败: {e}")

    def get_online_features(
        self,
        entity_rows: List[Dict[str, Any]],
        feature_refs: List[str],
    ) -> pd.DataFrame:
        """获取在线特征"""
        if not FEAST_AVAILABLE or not self._store:
            return pd.DataFrame()

        try:
            return self._store.get_online_features(
                entity_rows=entity_rows,
                features=feature_refs,
            ).to_df()
        except Exception as e:
            logger.error(f"[FeatureStore] 获取在线特征失败: {e}")
            return pd.DataFrame()

    def get_historical_features(
        self,
        entity_df: pd.DataFrame,
        feature_refs: List[str],
    ) -> pd.DataFrame:
        """获取历史特征"""
        if not FEAST_AVAILABLE or not self._store:
            return pd.DataFrame()

        try:
            return self._store.get_historical_features(
                entity_df=entity_df,
                features=feature_refs,
            ).to_df()
        except Exception as e:
            logger.error(f"[FeatureStore] 获取历史特征失败: {e}")
            return pd.DataFrame()


# ============ 实验追踪装饰器 ============

def track_experiment(
    experiment_name: str = None,
    run_name: str = None,
    log_params: bool = True,
    log_metrics: bool = True,
    log_model: bool = True,
    model_type: str = "sklearn",
):
    """实验追踪装饰器"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            manager = get_mlflow_manager()

            if experiment_name:
                mlflow.set_experiment(experiment_name)

            with manager.start_run(run_name=run_name):
                # 记录参数
                if log_params:
                    params = {
                        k: v for k, v in kwargs.items()
                        if isinstance(v, (int, float, str, bool))
                    }
                    manager.log_params(params)

                # 执行函数
                result = func(*args, **kwargs)

                # 记录指标
                if log_metrics and isinstance(result, dict):
                    metrics = result.get("metrics", {})
                    manager.log_metrics(metrics)

                # 记录模型
                if log_model and isinstance(result, dict):
                    model = result.get("model")
                    if model:
                        manager.log_model(model, "model", model_type)

                return result

        return wrapper
    return decorator


# ============ 便捷函数 ============

def get_mlflow_manager(config: MLflowConfig = None) -> MLflowManager:
    """获取MLflow管理器"""
    return MLflowManager(config)


def get_feature_store(repo_path: str = None) -> FeatureStoreManager:
    """获取特征存储"""
    return FeatureStoreManager(repo_path)


def init_mlflow(
    tracking_uri: str = "http://localhost:5000",
    experiment_name: str = "xb_strategy",
) -> MLflowManager:
    """初始化MLflow"""
    config = MLflowConfig(
        tracking_uri=tracking_uri,
        experiment_name=experiment_name,
    )
    return MLflowManager(config)


def log_experiment(
    params: Dict[str, Any] = None,
    metrics: Dict[str, float] = None,
    model: Any = None,
    model_type: str = "sklearn",
    artifacts: List[str] = None,
):
    """记录实验"""
    manager = get_mlflow_manager()

    with manager.start_run():
        if params:
            manager.log_params(params)

        if metrics:
            manager.log_metrics(metrics)

        if model:
            manager.log_model(model, "model", model_type)

        if artifacts:
            for artifact in artifacts:
                manager.log_artifact(artifact)
