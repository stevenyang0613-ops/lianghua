"""MLflow配置和管理"""
import os
from typing import Dict, Optional
from dataclasses import dataclass


@dataclass
class MLflowConfig:
    """MLflow配置"""
    tracking_uri: str = "http://localhost:5000"
    registry_uri: str = "http://localhost:5000"
    experiment_name: str = "convertible_bond_pricing"
    artifact_location: Optional[str] = None
    default_artifact_root: str = "/mlflow/artifacts"
    
    # 模型注册配置
    model_name: str = "cb_pricing_model"
    model_stage: str = "Production"
    
    # 自动日志配置
    autolog_enabled: bool = True
    autolog_exclusive: bool = False
    
    def setup(self):
        """设置MLflow"""
        try:
            import mlflow
            
            mlflow.set_tracking_uri(self.tracking_uri)
            
            # 创建或获取实验
            experiment = mlflow.get_experiment_by_name(self.experiment_name)
            if experiment is None:
                mlflow.create_experiment(
                    name=self.experiment_name,
                    artifact_location=self.artifact_location or self.default_artifact_root
                )
            
            mlflow.set_experiment(self.experiment_name)
            
            # 启用自动日志
            if self.autolog_enabled:
                try:
                    import mlflow.sklearn
                    mlflow.sklearn.autolog(
                        exclusive=self.autolog_exclusive,
                        log_models=True,
                        log_datasets=False
                    )
                except ImportError:
                    pass
                
                try:
                    import mlflow.lightgbm
                    mlflow.lightgbm.autolog(
                        exclusive=self.autolog_exclusive,
                        log_models=True
                    )
                except ImportError:
                    pass
            
            return True
        
        except ImportError:
            return False


class ModelRegistry:
    """模型注册中心"""
    
    def __init__(self, config: MLflowConfig = None):
        self.config = config or MLflowConfig()
        self._setup()
    
    def _setup(self):
        """初始化"""
        try:
            import mlflow
            self.client = mlflow.tracking.MlflowClient(
                tracking_uri=self.config.tracking_uri
            )
        except ImportError:
            self.client = None
    
    def register_model(self, run_id: str, model_name: str = None) -> str:
        """注册模型"""
        if not self.client:
            return None
        
        model_name = model_name or self.config.model_name
        
        model_uri = f"runs:/{run_id}/model"
        model_version = self.client.create_model_version(
            name=model_name,
            source=model_uri,
            run_id=run_id
        )
        
        return model_version.version
    
    def promote_model(self, model_name: str, version: str, stage: str = "Production"):
        """提升模型到指定阶段"""
        if not self.client:
            return None
        
        self.client.transition_model_version_stage(
            name=model_name,
            version=version,
            stage=stage
        )
    
    def get_production_model(self, model_name: str = None):
        """获取生产模型"""
        if not self.client:
            return None
        
        model_name = model_name or self.config.model_name
        
        # 获取Production阶段的模型
        versions = self.client.get_latest_versions(
            name=model_name,
            stages=["Production"]
        )
        
        if versions:
            return versions[0]
        
        return None
    
    def compare_models(self, model_name: str, version1: str, version2: str) -> Dict:
        """比较模型"""
        if not self.client:
            return {}
        
        v1 = self.client.get_model_version(model_name, version1)
        v2 = self.client.get_model_version(model_name, version2)
        
        # 获取运行指标
        run1 = self.client.get_run(v1.run_id)
        run2 = self.client.get_run(v2.run_id)
        
        return {
            'version1': {
                'version': version1,
                'metrics': run1.data.metrics,
                'params': run1.data.params
            },
            'version2': {
                'version': version2,
                'metrics': run2.data.metrics,
                'params': run2.data.params
            }
        }
    
    def list_model_versions(self, model_name: str = None) -> list:
        """列出所有模型版本"""
        if not self.client:
            return []
        
        model_name = model_name or self.config.model_name
        
        return self.client.search_model_versions(f"name='{model_name}'")


class ExperimentTracker:
    """实验追踪器"""
    
    def __init__(self, config: MLflowConfig = None):
        self.config = config or MLflowConfig()
        self.run_id = None
    
    def start_run(self, run_name: str = None, tags: Dict = None):
        """开始运行"""
        try:
            import mlflow
            
            run = mlflow.start_run(run_name=run_name, tags=tags)
            self.run_id = run.info.run_id
            return self.run_id
        except ImportError:
            return None
    
    def log_params(self, params: Dict):
        """记录参数"""
        try:
            import mlflow
            mlflow.log_params(params)
        except ImportError:
            pass
    
    def log_metrics(self, metrics: Dict, step: int = None):
        """记录指标"""
        try:
            import mlflow
            mlflow.log_metrics(metrics, step=step)
        except ImportError:
            pass
    
    def log_artifact(self, local_path: str, artifact_path: str = None):
        """记录工件"""
        try:
            import mlflow
            mlflow.log_artifact(local_path, artifact_path)
        except ImportError:
            pass
    
    def log_dict(self, dictionary: Dict, artifact_file: str):
        """记录字典"""
        try:
            import mlflow
            mlflow.log_dict(dictionary, artifact_file)
        except ImportError:
            pass
    
    def log_figure(self, figure, artifact_file: str):
        """记录图表"""
        try:
            import mlflow
            mlflow.log_figure(figure, artifact_file)
        except ImportError:
            pass
    
    def end_run(self, status: str = "FINISHED"):
        """结束运行"""
        try:
            import mlflow
            mlflow.end_run(status=status)
        except ImportError:
            pass
        self.run_id = None
