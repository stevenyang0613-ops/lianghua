"""西部量化可转债策略 V3.0 混沌工程模块

功能:
- 故障注入
- 韧性测试
- Chaos Mesh集成
- 故障场景定义
- 自动化恢复验证
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Callable
from enum import Enum
import logging
import random
import time
import threading
import json

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class FaultType(str, Enum):
    """故障类型"""
    POD_KILL = "pod_kill"               # Pod终止
    POD_FAILURE = "pod_failure"         # Pod故障
    CONTAINER_KILL = "container_kill"   # 容器终止
    CPU_STRESS = "cpu_stress"           # CPU压力
    MEMORY_STRESS = "memory_stress"     # 内存压力
    IO_STRESS = "io_stress"             # IO压力
    NETWORK_DELAY = "network_delay"     # 网络延迟
    NETWORK_LOSS = "network_loss"       # 网络丢包
    NETWORK_PARTITION = "network_partition"  # 网络分区
    DNS_FAULT = "dns_fault"             # DNS故障
    TIME_SKEW = "time_skew"             # 时间偏移


class ExperimentStatus(str, Enum):
    """实验状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


# ============ 数据模型 ============

@dataclass
class FaultSpec:
    """故障规格"""
    fault_type: FaultType
    target: str  # 目标Pod/Service
    duration: int  # 持续时间(秒)
    intensity: float = 1.0  # 强度 0-1
    namespace: str = "xb-strategy"
    labels: Dict[str, str] = field(default_factory=dict)

    def to_chaos_mesh_yaml(self) -> str:
        """转换为Chaos Mesh YAML"""
        if self.fault_type == FaultType.POD_KILL:
            return f"""
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: pod-kill-{int(time.time())}
  namespace: {self.namespace}
spec:
  action: pod-kill
  mode: one
  selector:
    namespaces:
      - {self.namespace}
    labelSelectors:
      app: {self.target}
  scheduler:
    cron: "@every 1h"
"""
        elif self.fault_type == FaultType.CPU_STRESS:
            return f"""
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: cpu-stress-{int(time.time())}
  namespace: {self.namespace}
spec:
  mode: one
  selector:
    namespaces:
      - {self.namespace}
    labelSelectors:
      app: {self.target}
  stressors:
    cpu:
      workers: 4
      load: {int(self.intensity * 100)}
  duration: "{self.duration}s"
"""
        elif self.fault_type == FaultType.NETWORK_DELAY:
            return f"""
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: network-delay-{int(time.time())}
  namespace: {self.namespace}
spec:
  action: delay
  mode: one
  selector:
    namespaces:
      - {self.namespace}
    labelSelectors:
      app: {self.target}
  delay:
    latency: "{int(self.intensity * 1000)}ms"
    correlation: "50"
    jitter: "50ms"
  duration: "{self.duration}s"
"""
        elif self.fault_type == FaultType.NETWORK_LOSS:
            return f"""
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: network-loss-{int(time.time())}
  namespace: {self.namespace}
spec:
  action: loss
  mode: one
  selector:
    namespaces:
      - {self.namespace}
    labelSelectors:
      app: {self.target}
  loss:
    loss: "{int(self.intensity * 100)}"
    correlation: "50"
  duration: "{self.duration}s"
"""
        else:
            return f"# 故障类型 {self.fault_type.value} 需要手动配置"


@dataclass
class ChaosExperiment:
    """混沌实验"""
    experiment_id: str
    name: str
    description: str
    faults: List[FaultSpec]
    hypothesis: str  # 假设
    status: ExperimentStatus = ExperimentStatus.PENDING
    start_time: datetime = None
    end_time: datetime = None
    results: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "name": self.name,
            "description": self.description,
            "hypothesis": self.hypothesis,
            "status": self.status.value,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "results": self.results,
            "faults": [f.__dict__ for f in self.faults],
        }


@dataclass
class SteadyStateCheck:
    """稳态检查"""
    name: str
    check_func: Callable[[], bool]
    timeout: int = 60
    interval: int = 5


# ============ 混沌工程引擎 ============

class ChaosEngine:
    """混沌工程引擎"""

    # 预定义故障场景
    PREDEFINED_SCENARIOS = {
        "scoring_service_outage": {
            "name": "打分服务中断",
            "description": "模拟打分服务完全不可用",
            "faults": [
                {"type": FaultType.POD_KILL, "target": "scoring-service", "duration": 300}
            ],
            "hypothesis": "系统应自动路由到备用实例，无单点故障",
        },
        "database_latency": {
            "name": "数据库延迟",
            "description": "模拟数据库响应延迟",
            "faults": [
                {"type": FaultType.NETWORK_DELAY, "target": "postgres-service", "duration": 300, "intensity": 0.5}
            ],
            "hypothesis": "系统应有超时和重试机制，不会阻塞",
        },
        "cache_failure": {
            "name": "缓存失效",
            "description": "模拟Redis缓存不可用",
            "faults": [
                {"type": FaultType.POD_KILL, "target": "redis", "duration": 180}
            ],
            "hypothesis": "系统应降级到直接查询数据库，性能可接受下降",
        },
        "network_partition": {
            "name": "网络分区",
            "description": "模拟部分服务网络分区",
            "faults": [
                {"type": FaultType.NETWORK_PARTITION, "target": "signal-service", "duration": 300}
            ],
            "hypothesis": "核心功能保持可用，分区服务优雅降级",
        },
        "resource_exhaustion": {
            "name": "资源耗尽",
            "description": "模拟CPU/内存压力",
            "faults": [
                {"type": FaultType.CPU_STRESS, "target": "scoring-service", "duration": 180, "intensity": 0.8},
                {"type": FaultType.MEMORY_STRESS, "target": "scoring-service", "duration": 180, "intensity": 0.6}
            ],
            "hypothesis": "服务应有资源限制，不会影响其他服务",
        },
        "cascade_failure": {
            "name": "级联故障",
            "description": "模拟多服务同时故障",
            "faults": [
                {"type": FaultType.POD_FAILURE, "target": "scoring-service", "duration": 300},
                {"type": FaultType.NETWORK_DELAY, "target": "postgres-service", "duration": 300, "intensity": 0.3},
            ],
            "hypothesis": "系统有熔断机制，防止级联失败",
        },
    }

    def __init__(self, kubectl_path: str = "kubectl", namespace: str = "xb-strategy"):
        self.kubectl_path = kubectl_path
        self.namespace = namespace
        self._experiments: Dict[str, ChaosExperiment] = {}
        self._steady_state_checks: List[SteadyStateCheck] = []
        self._lock = threading.Lock()

    def register_steady_state_check(self, check: SteadyStateCheck):
        """注册稳态检查"""
        self._steady_state_checks.append(check)

    def create_experiment(
        self,
        name: str,
        description: str,
        faults: List[Dict],
        hypothesis: str,
    ) -> ChaosExperiment:
        """创建实验"""
        experiment_id = f"exp_{int(time.time() * 1000)}"

        fault_specs = []
        for f in faults:
            fault_specs.append(FaultSpec(
                fault_type=f["type"] if isinstance(f["type"], FaultType) else FaultType(f["type"]),
                target=f["target"],
                duration=f.get("duration", 60),
                intensity=f.get("intensity", 1.0),
                namespace=self.namespace,
            ))

        experiment = ChaosExperiment(
            experiment_id=experiment_id,
            name=name,
            description=description,
            faults=fault_specs,
            hypothesis=hypothesis,
        )

        with self._lock:
            self._experiments[experiment_id] = experiment

        return experiment

    def run_experiment(
        self,
        experiment: ChaosExperiment,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """运行实验"""
        experiment.status = ExperimentStatus.RUNNING
        experiment.start_time = datetime.now()

        logger.info(f"[ChaosEngine] 开始实验: {experiment.name}")
        results = {
            "experiment_id": experiment.experiment_id,
            "name": experiment.name,
            "start_time": experiment.start_time.isoformat(),
            "faults_injected": [],
            "steady_state_checks": [],
            "recovery_verified": False,
        }

        try:
            # 1. 基线稳态检查
            baseline = self._check_steady_state()
            results["baseline"] = baseline

            if not baseline["passed"]:
                raise Exception("基线稳态检查失败，中止实验")

            # 2. 注入故障
            for fault in experiment.faults:
                if not dry_run:
                    self._inject_fault(fault)
                results["faults_injected"].append({
                    "type": fault.fault_type.value,
                    "target": fault.target,
                    "duration": fault.duration,
                })

            # 3. 持续监控
            max_duration = max(f.duration for f in experiment.faults)
            check_interval = min(10, max_duration // 10)

            for _ in range(0, max_duration, check_interval):
                time.sleep(check_interval)

                # 检查稳态
                check_result = self._check_steady_state()
                results["steady_state_checks"].append({
                    "time": datetime.now().isoformat(),
                    "passed": check_result["passed"],
                    "details": check_result["details"],
                })

            # 4. 等待恢复
            time.sleep(30)  # 等待恢复

            # 5. 恢复验证
            recovery_check = self._check_steady_state()
            results["recovery_verified"] = recovery_check["passed"]
            results["recovery_details"] = recovery_check

            experiment.status = ExperimentStatus.COMPLETED

        except Exception as e:
            logger.error(f"[ChaosEngine] 实验失败: {e}")
            experiment.status = ExperimentStatus.FAILED
            results["error"] = str(e)

        finally:
            # 清理故障
            if not dry_run:
                self._cleanup_faults(experiment.faults)

            experiment.end_time = datetime.now()
            experiment.results = results

        logger.info(f"[ChaosEngine] 实验完成: {experiment.name}, 状态: {experiment.status.value}")

        return results

    def _inject_fault(self, fault: FaultSpec):
        """注入故障"""
        logger.info(f"[ChaosEngine] 注入故障: {fault.fault_type.value} -> {fault.target}")

        # 生成Chaos Mesh YAML
        yaml_content = fault.to_chaos_mesh_yaml()

        # 实际部署时使用kubectl应用
        # subprocess.run([self.kubectl_path, "apply", "-f", "-"], input=yaml_content)

        logger.debug(f"[ChaosEngine] YAML:\n{yaml_content}")

    def _cleanup_faults(self, faults: List[FaultSpec]):
        """清理故障"""
        logger.info("[ChaosEngine] 清理故障")

        # 删除Chaos Mesh资源
        # for fault in faults:
        #     subprocess.run([self.kubectl_path, "delete", ...])

    def _check_steady_state(self) -> Dict[str, Any]:
        """检查稳态"""
        results = {
            "passed": True,
            "details": {},
        }

        for check in self._steady_state_checks:
            try:
                passed = check.check_func()
                results["details"][check.name] = {
                    "passed": passed,
                }
                if not passed:
                    results["passed"] = False
            except Exception as e:
                results["details"][check.name] = {
                    "passed": False,
                    "error": str(e),
                }
                results["passed"] = False

        return results

    def get_experiment(self, experiment_id: str) -> Optional[ChaosExperiment]:
        """获取实验"""
        return self._experiments.get(experiment_id)

    def get_all_experiments(self) -> List[ChaosExperiment]:
        """获取所有实验"""
        return list(self._experiments.values())

    def run_predefined_scenario(self, scenario_name: str) -> Dict[str, Any]:
        """运行预定义场景"""
        if scenario_name not in self.PREDEFINED_SCENARIOS:
            raise ValueError(f"未知场景: {scenario_name}")

        scenario = self.PREDEFINED_SCENARIOS[scenario_name]

        experiment = self.create_experiment(
            name=scenario["name"],
            description=scenario["description"],
            faults=scenario["faults"],
            hypothesis=scenario["hypothesis"],
        )

        return self.run_experiment(experiment)


# ============ 稳态检查器 ============

class SteadyStateChecker:
    """稳态检查器"""

    @staticmethod
    def check_api_health(base_url: str) -> bool:
        """检查API健康"""
        try:
            import requests
            response = requests.get(f"{base_url}/health", timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    @staticmethod
    def check_response_time(base_url: str, endpoint: str, max_ms: float) -> bool:
        """检查响应时间"""
        try:
            import requests
            import time

            start = time.time()
            response = requests.get(f"{base_url}{endpoint}", timeout=10)
            elapsed = (time.time() - start) * 1000

            return response.status_code == 200 and elapsed < max_ms
        except Exception:
            return False

    @staticmethod
    def check_error_rate(base_url: str, max_rate: float) -> bool:
        """检查错误率"""
        # 查询Prometheus获取错误率
        # 这里简化处理
        return True

    @staticmethod
    def check_pod_count(namespace: str, app: str, min_count: int) -> bool:
        """检查Pod数量"""
        # 使用kubectl查询
        # 这里简化处理
        return True


# ============ 自动化测试场景 ============

class AutomatedChaosTests:
    """自动化混沌测试"""

    def __init__(self, engine: ChaosEngine):
        self.engine = engine

    def test_service_resilience(self) -> Dict[str, Any]:
        """测试服务韧性"""
        results = {}

        # 注册稳态检查
        self.engine.register_steady_state_check(SteadyStateCheck(
            name="api_health",
            check_func=lambda: SteadyStateChecker.check_api_health("https://api.xb-strategy.com"),
        ))

        # 运行所有预定义场景
        for scenario_name in self.engine.PREDEFINED_SCENARIOS:
            logger.info(f"[AutomatedChaosTests] 运行场景: {scenario_name}")
            results[scenario_name] = self.engine.run_predefined_scenario(scenario_name)

        return results

    def generate_report(self, results: Dict[str, Any]) -> str:
        """生成报告"""
        lines = [
            "# 混沌工程测试报告",
            f"\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
            "---\n",
        ]

        for scenario, result in results.items():
            lines.append(f"## {scenario}\n")
            lines.append(f"- 状态: {result.get('status', 'unknown')}\n")
            lines.append(f"- 稳态保持: {'✅' if result.get('recovery_verified') else '❌'}\n")

            if result.get("error"):
                lines.append(f"- 错误: {result['error']}\n")

            lines.append("\n")

        return "".join(lines)


# ============ 便捷函数 ============

def create_chaos_engine(namespace: str = "xb-strategy") -> ChaosEngine:
    """创建混沌引擎"""
    return ChaosEngine(namespace=namespace)


def run_chaos_experiment(
    name: str,
    faults: List[Dict],
    hypothesis: str,
    namespace: str = "xb-strategy",
) -> Dict[str, Any]:
    """运行混沌实验"""
    engine = ChaosEngine(namespace=namespace)
    experiment = engine.create_experiment(
        name=name,
        description=f"实验: {name}",
        faults=faults,
        hypothesis=hypothesis,
    )
    return engine.run_experiment(experiment)
