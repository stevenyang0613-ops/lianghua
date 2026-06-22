"""西部量化可转债策略 V3.0 策略配置管理模块

功能:
- 动态参数调整
- 配置版本控制
- A/B测试框架
- 灰度发布
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, Callable
from enum import Enum
import logging
import json
import hashlib
import threading
from collections import defaultdict
import copy

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class ConfigStatus(str, Enum):
    """配置状态"""
    DRAFT = "draft"           # 草稿
    PENDING = "pending"       # 待审批
    ACTIVE = "active"         # 生效中
    DEPRECATED = "deprecated" # 已废弃
    ARCHIVED = "archived"     # 已归档


class ExperimentStatus(str, Enum):
    """实验状态"""
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class RolloutStrategy(str, Enum):
    """发布策略"""
    IMMEDIATE = "immediate"     # 立即发布
    PERCENTAGE = "percentage"   # 百分比发布
    CANARY = "canary"           # 金丝雀发布
    BLUE_GREEN = "blue_green"   # 蓝绿发布


# ============ 数据模型 ============

@dataclass
class ConfigParameter:
    """配置参数"""
    key: str
    value: Any
    value_type: str  # int, float, str, bool, list, dict
    default_value: Any = None
    min_value: float = None
    max_value: float = None
    description: str = ""
    category: str = "general"
    tags: List[str] = field(default_factory=list)
    is_sensitive: bool = False

    def validate(self) -> bool:
        """验证参数"""
        # 类型检查
        if self.value_type == "int":
            if not isinstance(self.value, (int, float)):
                return False
            if self.min_value is not None and self.value < self.min_value:
                return False
            if self.max_value is not None and self.value > self.max_value:
                return False
        elif self.value_type == "float":
            if not isinstance(self.value, (int, float)):
                return False
            if self.min_value is not None and self.value < self.min_value:
                return False
            if self.max_value is not None and self.value > self.max_value:
                return False
        elif self.value_type == "str":
            if not isinstance(self.value, str):
                return False
        elif self.value_type == "bool":
            if not isinstance(self.value, bool):
                return False

        return True

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "value_type": self.value_type,
            "default_value": self.default_value,
            "description": self.description,
            "category": self.category,
            "tags": self.tags,
        }


@dataclass
class ConfigVersion:
    """配置版本"""
    version_id: str
    config_hash: str
    parameters: Dict[str, ConfigParameter]
    status: ConfigStatus
    created_at: datetime
    created_by: str
    activated_at: datetime = None
    deprecated_at: datetime = None
    change_log: str = ""
    parent_version: str = None

    def to_dict(self) -> dict:
        return {
            "version_id": self.version_id,
            "config_hash": self.config_hash,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "activated_at": self.activated_at.isoformat() if self.activated_at else None,
            "change_log": self.change_log,
            "parameter_count": len(self.parameters),
        }


@dataclass
class Experiment:
    """A/B测试实验"""
    experiment_id: str
    name: str
    description: str
    control_config: Dict[str, Any]  # 对照组配置
    treatment_config: Dict[str, Any]  # 实验组配置
    traffic_split: float  # 实验组流量比例
    status: ExperimentStatus
    start_time: datetime
    end_time: datetime = None
    metrics: List[str] = field(default_factory=list)
    results: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "name": self.name,
            "description": self.description,
            "traffic_split": self.traffic_split,
            "status": self.status.value,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "metrics": self.metrics,
            "results": self.results,
        }


@dataclass
class Rollout:
    """灰度发布"""
    rollout_id: str
    name: str
    config_version: str
    strategy: RolloutStrategy
    status: str
    target_percentage: float
    current_percentage: float
    started_at: datetime
    completed_at: datetime = None
    stages: List[Dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "rollout_id": self.rollout_id,
            "name": self.name,
            "config_version": self.config_version,
            "strategy": self.strategy.value,
            "status": self.status,
            "target_percentage": self.target_percentage,
            "current_percentage": self.current_percentage,
            "started_at": self.started_at.isoformat(),
            "stages": self.stages,
        }


# ============ 配置管理器 ============

class ConfigManager:
    """配置管理器"""

    def __init__(self):
        self._configs: Dict[str, ConfigParameter] = {}
        self._versions: Dict[str, ConfigVersion] = {}
        self._active_version: str = None
        self._lock = threading.RLock()

        # 变更回调
        self._change_callbacks: List[Callable] = []

        # 初始化默认配置
        self._init_default_config()

    def _init_default_config(self):
        """初始化默认配置"""
        default_params = [
            # 打分权重
            ConfigParameter("score.stock_weight", 55, "int", 55, 0, 100, "正股打分权重", "scoring"),
            ConfigParameter("score.bond_weight", 45, "int", 45, 0, 100, "转债打分权重", "scoring"),

            # 一票否决阈值
            ConfigParameter("veto.max_premium", 50, "float", 50, 0, 100, "最大溢价率阈值%", "veto"),
            ConfigParameter("veto.min_maturity_days", 365, "int", 365, 0, 3650, "最短剩余期限天", "veto"),
            ConfigParameter("veto.min_balance", 1, "float", 1, 0, 100, "最小剩余规模亿", "veto"),

            # 白名单配置
            ConfigParameter("whitelist.size", 60, "int", 60, 10, 200, "白名单数量", "whitelist"),
            ConfigParameter("whitelist.buffer_size", 10, "int", 10, 0, 50, "缓冲区大小", "whitelist"),

            # 信号配置
            ConfigParameter("signal.confidence_threshold", 0.7, "float", 0.7, 0, 1, "信号置信度阈值", "signal"),
            ConfigParameter("signal.max_positions", 30, "int", 30, 1, 100, "最大持仓数", "signal"),

            # 风控配置
            ConfigParameter("risk.max_position_weight", 0.1, "float", 0.1, 0.01, 0.3, "最大持仓权重", "risk"),
            ConfigParameter("risk.max_drawdown", 0.1, "float", 0.1, 0.01, 0.3, "最大回撤限制", "risk"),
            ConfigParameter("risk.var_limit", 0.02, "float", 0.02, 0.001, 0.1, "VaR限制", "risk"),

            # 执行配置
            ConfigParameter("execution.slippage_tolerance", 0.005, "float", 0.005, 0, 0.1, "滑点容忍度", "execution"),
            ConfigParameter("execution.timeout_seconds", 300, "int", 300, 10, 3600, "执行超时秒", "execution"),
        ]

        for param in default_params:
            self._configs[param.key] = param

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置"""
        with self._lock:
            param = self._configs.get(key)
            if param:
                return param.value
            return default

    def set(self, key: str, value: Any, validate: bool = True) -> bool:
        """设置配置"""
        with self._lock:
            param = self._configs.get(key)

            if param:
                old_value = param.value
                param.value = value

                if validate and not param.validate():
                    param.value = old_value
                    return False

                # 触发回调
                self._notify_change(key, old_value, value)

                return True

            # 新参数
            value_type = type(value).__name__
            new_param = ConfigParameter(key=key, value=value, value_type=value_type)
            self._configs[key] = new_param

            return True

    def get_all(self, category: str = None) -> Dict[str, Any]:
        """获取所有配置"""
        with self._lock:
            if category:
                return {k: v.value for k, v in self._configs.items() if v.category == category}
            return {k: v.value for k, v in self._configs.items()}

    def get_by_category(self) -> Dict[str, Dict]:
        """按分类获取"""
        result = defaultdict(dict)

        with self._lock:
            for key, param in self._configs.items():
                result[param.category][key] = param.to_dict()

        return dict(result)

    def create_version(self, change_log: str = "", created_by: str = "system") -> str:
        """创建版本"""
        with self._lock:
            # 生成版本ID（使用微秒避免冲突）
            now = datetime.now()
            version_id = f"v_{now.strftime('%Y%m%d_%H%M%S')}_{now.microsecond:06d}"

            # 计算配置哈希
            config_str = json.dumps(self.get_all(), sort_keys=True)
            config_hash = hashlib.md5(config_str.encode()).hexdigest()[:8]

            # 创建版本
            version = ConfigVersion(
                version_id=version_id,
                config_hash=config_hash,
                parameters=copy.deepcopy(self._configs),
                status=ConfigStatus.DRAFT,
                created_at=datetime.now(),
                created_by=created_by,
                change_log=change_log,
            )

            self._versions[version_id] = version

            logger.info(f"[ConfigManager] 创建版本: {version_id}")

            return version_id

    def activate_version(self, version_id: str) -> bool:
        """激活版本"""
        with self._lock:
            version = self._versions.get(version_id)
            if not version:
                return False

            # 停用当前版本
            if self._active_version:
                current = self._versions.get(self._active_version)
                if current:
                    current.status = ConfigStatus.DEPRECATED
                    current.deprecated_at = datetime.now()

            # 激活新版本
            version.status = ConfigStatus.ACTIVE
            version.activated_at = datetime.now()

            # 应用配置并触发变更回调
            new_params = copy.deepcopy(version.parameters)
            changed_keys = set()
            for key, val in new_params.items():
                if key in self._configs and self._configs[key] != val:
                    changed_keys.add(key)
                elif key not in self._configs:
                    changed_keys.add(key)
            self._configs = new_params
            # 触发变更回调
            for key in changed_keys:
                for callback in self._change_callbacks.get(key, []):
                    try:
                        callback(key, self._configs[key])
                    except Exception as e:
                        logger.warning(f"[ConfigManager] 回调触发失败: {key} -> {e}")

            self._active_version = version_id

            logger.info(f"[ConfigManager] 激活版本: {version_id}")

            return True

    def rollback(self, version_id: str) -> bool:
        """回滚到指定版本"""
        return self.activate_version(version_id)

    def get_version(self, version_id: str) -> Optional[ConfigVersion]:
        """获取版本"""
        return self._versions.get(version_id)

    def list_versions(self, status: ConfigStatus = None) -> List[ConfigVersion]:
        """列出版本"""
        versions = list(self._versions.values())

        if status:
            versions = [v for v in versions if v.status == status]

        return sorted(versions, key=lambda v: v.created_at, reverse=True)

    def register_change_callback(self, callback: Callable):
        """注册变更回调"""
        self._change_callbacks.append(callback)

    def _notify_change(self, key: str, old_value: Any, new_value: Any):
        """通知变更"""
        for callback in self._change_callbacks:
            try:
                callback(key, old_value, new_value)
            except Exception as e:
                logger.error(f"[ConfigManager] 回调执行失败: {e}")


# ============ A/B测试框架 ============

class ABTestFramework:
    """A/B测试框架"""

    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self._experiments: Dict[str, Experiment] = {}
        self._user_buckets: Dict[str, str] = {}  # user_id -> experiment_id
        self._lock = threading.Lock()

    def create_experiment(
        self,
        name: str,
        description: str,
        control_config: Dict[str, Any],
        treatment_config: Dict[str, Any],
        traffic_split: float = 0.5,
        metrics: List[str] = None,
    ) -> str:
        """创建实验"""
        experiment_id = f"exp_{int(datetime.now().timestamp() * 1000)}"

        experiment = Experiment(
            experiment_id=experiment_id,
            name=name,
            description=description,
            control_config=control_config,
            treatment_config=treatment_config,
            traffic_split=traffic_split,
            status=ExperimentStatus.CREATED,
            start_time=datetime.now(),
            metrics=metrics or [],
        )

        with self._lock:
            self._experiments[experiment_id] = experiment

        logger.info(f"[ABTestFramework] 创建实验: {name}")

        return experiment_id

    def start_experiment(self, experiment_id: str) -> bool:
        """启动实验"""
        with self._lock:
            experiment = self._experiments.get(experiment_id)
            if not experiment:
                return False

            experiment.status = ExperimentStatus.RUNNING
            experiment.start_time = datetime.now()

        logger.info(f"[ABTestFramework] 启动实验: {experiment_id}")

        return True

    def stop_experiment(self, experiment_id: str) -> bool:
        """停止实验"""
        with self._lock:
            experiment = self._experiments.get(experiment_id)
            if not experiment:
                return False

            experiment.status = ExperimentStatus.COMPLETED
            experiment.end_time = datetime.now()

        return True

    def get_config_for_user(self, user_id: str, experiment_id: str = None) -> Dict[str, Any]:
        """获取用户配置"""
        # 如果指定了实验
        if experiment_id:
            experiment = self._experiments.get(experiment_id)
            if experiment and experiment.status == ExperimentStatus.RUNNING:
                bucket = self._get_user_bucket(user_id, experiment_id)
                if bucket == "treatment":
                    return experiment.treatment_config
                return experiment.control_config

        # 检查所有运行中的实验
        with self._lock:
            for exp_id, experiment in self._experiments.items():
                if experiment.status != ExperimentStatus.RUNNING:
                    continue

                bucket = self._get_user_bucket(user_id, exp_id)
                if bucket == "treatment":
                    return experiment.treatment_config

        # 返回默认配置
        return self.config_manager.get_all()

    def _get_user_bucket(self, user_id: str, experiment_id: str) -> str:
        """获取用户分组"""
        key = f"{user_id}_{experiment_id}"

        if key in self._user_buckets:
            return self._user_buckets[key]

        # 基于用户ID哈希分配
        experiment = self._experiments.get(experiment_id)
        if not experiment:
            return "control"

        hash_val = int(hashlib.md5(key.encode()).hexdigest(), 16)
        bucket = "treatment" if (hash_val % 100) < (experiment.traffic_split * 100) else "control"

        self._user_buckets[key] = bucket

        return bucket

    def record_metric(self, experiment_id: str, metric_name: str, value: float, bucket: str):
        """记录指标"""
        with self._lock:
            experiment = self._experiments.get(experiment_id)
            if not experiment:
                return

            if "metrics_data" not in experiment.results:
                experiment.results["metrics_data"] = defaultdict(lambda: {"control": [], "treatment": []})

            experiment.results["metrics_data"][metric_name][bucket].append(value)

    def get_results(self, experiment_id: str) -> Dict:
        """获取实验结果"""
        with self._lock:
            experiment = self._experiments.get(experiment_id)
            if not experiment:
                return {}

            results = {
                "experiment": experiment.to_dict(),
                "metrics": {},
            }

            metrics_data = experiment.results.get("metrics_data", {})

            for metric_name, data in metrics_data.items():
                control_values = data.get("control", [])
                treatment_values = data.get("treatment", [])

                if control_values and treatment_values:
                    control_mean = sum(control_values) / len(control_values)
                    treatment_mean = sum(treatment_values) / len(treatment_values)

                    results["metrics"][metric_name] = {
                        "control_mean": control_mean,
                        "treatment_mean": treatment_mean,
                        "improvement": (treatment_mean - control_mean) / control_mean if control_mean != 0 else 0,
                        "control_count": len(control_values),
                        "treatment_count": len(treatment_values),
                    }

            return results


# ============ 灰度发布管理器 ============

class RolloutManager:
    """灰度发布管理器"""

    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self._rollouts: Dict[str, Rollout] = {}
        self._lock = threading.Lock()

    def create_rollout(
        self,
        name: str,
        config_version: str,
        strategy: RolloutStrategy,
        target_percentage: float = 100,
        stages: List[Dict] = None,
    ) -> str:
        """创建灰度发布"""
        rollout_id = f"rollout_{int(datetime.now().timestamp() * 1000)}"

        rollout = Rollout(
            rollout_id=rollout_id,
            name=name,
            config_version=config_version,
            strategy=strategy,
            status="created",
            target_percentage=target_percentage,
            current_percentage=0,
            started_at=datetime.now(),
            stages=stages or [],
        )

        with self._lock:
            self._rollouts[rollout_id] = rollout

        logger.info(f"[RolloutManager] 创建发布: {name}")

        return rollout_id

    def start_rollout(self, rollout_id: str) -> bool:
        """启动发布"""
        with self._lock:
            rollout = self._rollouts.get(rollout_id)
            if not rollout:
                return False

            rollout.status = "running"
            rollout.current_percentage = 0

        return True

    def advance_rollout(self, rollout_id: str, percentage: float) -> bool:
        """推进发布"""
        with self._lock:
            rollout = self._rollouts.get(rollout_id)
            if not rollout or rollout.status != "running":
                return False

            rollout.current_percentage = min(percentage, rollout.target_percentage)

            # 记录阶段
            rollout.stages.append({
                "timestamp": datetime.now().isoformat(),
                "percentage": rollout.current_percentage,
            })

            if rollout.current_percentage >= rollout.target_percentage:
                rollout.status = "completed"
                rollout.completed_at = datetime.now()

        logger.info(f"[RolloutManager] 推进发布: {rollout_id} -> {percentage}%")

        return True

    def rollback_rollout(self, rollout_id: str) -> bool:
        """回滚发布"""
        with self._lock:
            rollout = self._rollouts.get(rollout_id)
            if not rollout:
                return False

            rollout.status = "rolled_back"
            rollout.current_percentage = 0

        return True

    def get_rollout(self, rollout_id: str) -> Optional[Rollout]:
        """获取发布"""
        return self._rollouts.get(rollout_id)

    def list_rollouts(self, status: str = None) -> List[Rollout]:
        """列出发布"""
        rollouts = list(self._rollouts.values())

        if status:
            rollouts = [r for r in rollouts if r.status == status]

        return sorted(rollouts, key=lambda r: r.started_at, reverse=True)


# ============ 策略配置服务 ============

class StrategyConfigService:
    """策略配置服务"""

    def __init__(self):
        self.config_manager = ConfigManager()
        self.ab_test = ABTestFramework(self.config_manager)
        self.rollout = RolloutManager(self.config_manager)

    def get_config(self, key: str = None, user_id: str = None) -> Any:
        """获取配置"""
        if user_id:
            config = self.ab_test.get_config_for_user(user_id)
            if key:
                return config.get(key)
            return config

        if key:
            return self.config_manager.get(key)
        return self.config_manager.get_all()

    def update_config(self, key: str, value: Any) -> bool:
        """更新配置"""
        return self.config_manager.set(key, value)

    def create_config_version(self, change_log: str = "") -> str:
        """创建配置版本"""
        return self.config_manager.create_version(change_log)

    def start_ab_test(
        self,
        name: str,
        treatment_config: Dict[str, Any],
        traffic_split: float = 0.1,
    ) -> str:
        """启动A/B测试"""
        control_config = self.config_manager.get_all()

        return self.ab_test.create_experiment(
            name=name,
            description=f"A/B test for {name}",
            control_config=control_config,
            treatment_config=treatment_config,
            traffic_split=traffic_split,
        )

    def create_rollout(
        self,
        config_version: str,
        strategy: RolloutStrategy = RolloutStrategy.PERCENTAGE,
        target_percentage: float = 100,
    ) -> str:
        """创建灰度发布"""
        return self.rollout.create_rollout(
            name=f"Rollout for {config_version}",
            config_version=config_version,
            strategy=strategy,
            target_percentage=target_percentage,
        )

    def export_config(self) -> str:
        """导出配置"""
        config = self.config_manager.get_all()
        return json.dumps(config, indent=2, ensure_ascii=False)

    def import_config(self, config_json: str) -> bool:
        """导入配置"""
        try:
            config = json.loads(config_json)

            for key, value in config.items():
                self.config_manager.set(key, value)

            return True
        except Exception as e:
            logger.error(f"[StrategyConfigService] 导入失败: {e}")
            return False


# ============ 便捷函数 ============

def create_config_service() -> StrategyConfigService:
    """创建配置服务"""
    return StrategyConfigService()


def get_config(key: str, default: Any = None) -> Any:
    """获取配置"""
    service = StrategyConfigService()
    return service.get_config(key) or default
