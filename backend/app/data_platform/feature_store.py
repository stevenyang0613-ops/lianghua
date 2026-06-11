"""特征存储"""
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from abc import ABC, abstractmethod
import hashlib
import json


@dataclass
class FeatureDefinition:
    """特征定义"""
    name: str
    dtype: str
    description: str
    transformation: str
    dependencies: List[str] = field(default_factory=list)
    default_value: Any = None
    validity_period: timedelta = timedelta(days=1)


@dataclass
class FeatureGroup:
    """特征组"""
    name: str
    features: List[FeatureDefinition]
    entity_key: str
    timestamp_key: str = "timestamp"
    online_store: bool = True
    offline_store: bool = True
    version: str = "1"


class FeatureStore:
    """特征存储"""
    
    def __init__(self, offline_store_path: str = "/data/features/offline",
                 online_store_config: Dict = None):
        self.offline_store_path = offline_store_path
        self.online_store_config = online_store_config or {}
        
        self.feature_groups: Dict[str, FeatureGroup] = {}
        self.feature_cache: Dict[str, Dict] = {}
        
        # 在线存储（Redis）
        self._init_online_store()
    
    def _init_online_store(self):
        """初始化在线存储"""
        try:
            import redis
            self.redis = redis.Redis(
                host=self.online_store_config.get('host', 'localhost'),
                port=self.online_store_config.get('port', 6379),
                db=self.online_store_config.get('db', 0)
            )
        except Exception:
            self.redis = None
    
    def register_feature_group(self, group: FeatureGroup):
        """注册特征组"""
        self.feature_groups[group.name] = group
        
        # 创建离线存储表
        if group.offline_store:
            self._create_offline_table(group)
    
    def _create_offline_table(self, group: FeatureGroup):
        """创建离线存储表"""
        import os
        table_path = os.path.join(self.offline_store_path, group.name)
        os.makedirs(table_path, exist_ok=True)
    
    def compute_features(
        self,
        group_name: str,
        data: pd.DataFrame,
        feature_names: List[str] = None
    ) -> pd.DataFrame:
        """计算特征"""
        if group_name not in self.feature_groups:
            raise ValueError(f"特征组 {group_name} 未注册")
        
        group = self.feature_groups[group_name]
        features_to_compute = feature_names or [f.name for f in group.features]
        
        result = data.copy()
        
        for feature_def in group.features:
            if feature_def.name not in features_to_compute:
                continue
            
            # 计算特征
            result[feature_def.name] = self._apply_transformation(
                data, 
                feature_def.transformation,
                feature_def.dependencies
            )
        
        return result
    
    def _apply_transformation(
        self,
        data: pd.DataFrame,
        transformation: str,
        dependencies: List[str]
    ) -> pd.Series:
        """应用特征转换"""
        # 简化的特征计算
        if transformation == "identity":
            return data[dependencies[0]]
        
        elif transformation == "mean":
            return data[dependencies].mean(axis=1)
        
        elif transformation == "std":
            return data[dependencies[0]].rolling(window=20).std()
        
        elif transformation == "return":
            return data[dependencies[0]].pct_change()
        
        elif transformation == "log_return":
            return np.log(data[dependencies[0]] / data[dependencies[0]].shift(1))
        
        elif transformation.startswith("rolling_"):
            window = int(transformation.split("_")[1])
            return data[dependencies[0]].rolling(window=window).mean()
        
        elif transformation == "zscore":
            col = dependencies[0]
            return (data[col] - data[col].rolling(20).mean()) / data[col].rolling(20).std()
        
        elif transformation == "rank":
            return data[dependencies[0]].rank(pct=True)
        
        elif transformation == "delta":
            return data[dependencies[0]].diff()
        
        else:
            # 自定义转换
            return pd.Series(0, index=data.index)
    
    def get_online_features(
        self,
        group_name: str,
        entity_ids: List[str],
        feature_names: List[str] = None
    ) -> pd.DataFrame:
        """获取在线特征"""
        if not self.redis:
            return pd.DataFrame()
        
        group = self.feature_groups[group_name]
        features = feature_names or [f.name for f in group.features]
        
        results = []
        
        for entity_id in entity_ids:
            key = f"features:{group_name}:{entity_id}"
            values = self.redis.hmget(key, features)
            
            row = {group.entity_key: entity_id}
            for feat, val in zip(features, values):
                row[feat] = json.loads(val) if val else None
            results.append(row)
        
        return pd.DataFrame(results)
    
    def write_online_features(
        self,
        group_name: str,
        data: pd.DataFrame
    ):
        """写入在线特征"""
        if not self.redis:
            return
        
        group = self.feature_groups[group_name]
        
        for _, row in data.iterrows():
            entity_id = str(row[group.entity_key])
            key = f"features:{group_name}:{entity_id}"
            
            # 写入每个特征
            for feat in group.features:
                if feat.name in row:
                    self.redis.hset(
                        key,
                        feat.name,
                        json.dumps(row[feat.name], default=str)
                    )
            
            # 设置过期时间
            self.redis.expire(key, feat.validity_period.total_seconds())
    
    def get_offline_features(
        self,
        group_name: str,
        entity_df: pd.DataFrame,
        feature_names: List[str] = None
    ) -> pd.DataFrame:
        """获取离线特征"""
        import os
        import glob
        
        group = self.feature_groups[group_name]
        features = feature_names or [f.name for f in group.features]
        
        # 读取离线数据
        table_path = os.path.join(self.offline_store_path, group.name)
        parquet_files = glob.glob(os.path.join(table_path, "*.parquet"))
        
        if not parquet_files:
            return pd.DataFrame()
        
        # 合并数据
        dfs = [pd.read_parquet(f) for f in parquet_files]
        offline_data = pd.concat(dfs, ignore_index=True)
        
        # 按实体和时间点连接
        result = pd.merge(
            entity_df,
            offline_data[[group.entity_key, group.timestamp_key] + features],
            on=[group.entity_key, group.timestamp_key],
            how='left'
        )
        
        return result
    
    def write_offline_features(
        self,
        group_name: str,
        data: pd.DataFrame
    ):
        """写入离线特征"""
        import os
        
        group = self.feature_groups[group_name]
        table_path = os.path.join(self.offline_store_path, group.name)
        
        # 按日期分区存储
        if group.timestamp_key in data.columns:
            data['partition_date'] = pd.to_datetime(data[group.timestamp_key]).dt.date
        
        # 写入Parquet
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(table_path, f"features_{timestamp}.parquet")
        data.to_parquet(file_path, index=False)
    
    def create_training_dataset(
        self,
        feature_groups: List[str],
        entity_df: pd.DataFrame,
        label_column: str = None
    ) -> pd.DataFrame:
        """创建训练数据集"""
        result = entity_df.copy()
        
        for group_name in feature_groups:
            group = self.feature_groups[group_name]
            features = [f.name for f in group.features]
            
            # 获取离线特征
            group_features = self.get_offline_features(group_name, result, features)
            
            # 合并
            result = pd.concat([result, group_features[[group.entity_key] + features]], axis=1)
        
        return result
    
    def get_feature_vector(
        self,
        group_name: str,
        entity_id: str,
        feature_names: List[str] = None
    ) -> np.ndarray:
        """获取特征向量"""
        df = self.get_online_features(group_name, [entity_id], feature_names)
        
        if df.empty:
            return np.array([])
        
        features = feature_names or [f.name for f in self.feature_groups[group_name].features]
        return df[features].values[0]
    
    def invalidate_features(
        self,
        group_name: str,
        entity_ids: List[str] = None
    ):
        """使特征失效"""
        if not self.redis:
            return
        
        if entity_ids:
            for entity_id in entity_ids:
                key = f"features:{group_name}:{entity_id}"
                self.redis.delete(key)
        else:
            # 删除整个特征组
            pattern = f"features:{group_name}:*"
            keys = self.redis.keys(pattern)
            if keys:
                self.redis.delete(*keys)


class FeaturePipeline:
    """特征流水线"""
    
    def __init__(self, feature_store: FeatureStore):
        self.feature_store = feature_store
        self.pipelines: Dict[str, List[Callable]] = {}
    
    def register_pipeline(
        self,
        name: str,
        steps: List[Callable]
    ):
        """注册特征流水线"""
        self.pipelines[name] = steps
    
    def run_pipeline(
        self,
        name: str,
        data: pd.DataFrame
    ) -> pd.DataFrame:
        """运行特征流水线"""
        if name not in self.pipelines:
            raise ValueError(f"流水线 {name} 未注册")
        
        result = data.copy()
        
        for step in self.pipelines[name]:
            result = step(result)
        
        return result
    
    def schedule_pipeline(
        self,
        name: str,
        schedule: str,
        data_loader: Callable
    ):
        """调度特征流水线"""
        # 简化实现，生产环境应使用Celery等
        pass
