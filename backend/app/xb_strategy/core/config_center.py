"""西部量化可转债策略 V3.0 配置中心模块

功能:
- 动态配置管理
- 配置热更新
- 配置版本管理
- 配置监听
- 多环境支持
- 配置加密
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, Callable
from enum import Enum
import json
import logging
import os
import hashlib
import threading
import copy

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class Environment(str, Enum):
    """环境"""
    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


class ConfigSource(str, Enum):
    """配置来源"""
    FILE = "file"
    ENV = "environment"
    ETCD = "etcd"
    CONSUL = "consul"
    REDIS = "redis"
    DATABASE = "database"


# ============ 数据模型 ============

@dataclass
class ConfigEntry:
    """配置项"""
    key: str
    value: Any
    version: int = 1
    source: ConfigSource = ConfigSource.FILE
    updated_at: datetime = field(default_factory=datetime.now)
    updated_by: str = "system"
    encrypted: bool = False
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value if not self.encrypted else "******",
            "version": self.version,
            "source": self.source.value,
            "updated_at": self.updated_at.isoformat(),
            "updated_by": self.updated_by,
            "encrypted": self.encrypted,
            "description": self.description,
        }


@dataclass
class ConfigHistory:
    """配置历史"""
    key: str
    old_value: Any
    new_value: Any
    version: int
    changed_at: datetime
    changed_by: str
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "version": self.version,
            "changed_at": self.changed_at.isoformat(),
            "changed_by": self.changed_by,
            "reason": self.reason,
        }


# ============ 配置管理器 ============

class ConfigCenter:
    """配置中心"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._configs: Dict[str, ConfigEntry] = {}
        self._history: List[ConfigHistory] = []
        self._listeners: Dict[str, List[Callable]] = {}
        self._environment = Environment.PRODUCTION
        self._lock = threading.RLock()

        # 加载默认配置
        self._load_defaults()

        self._initialized = True

    def _load_defaults(self):
        """加载默认配置"""
        # 策略配置
        self._configs["strategy.name"] = ConfigEntry(
            key="strategy.name",
            value="西部量化可转债策略",
            description="策略名称",
        )

        self._configs["strategy.version"] = ConfigEntry(
            key="strategy.version",
            value="3.0.0",
            description="策略版本",
        )

        # 打分配置
        self._configs["scoring.stock_weight"] = ConfigEntry(
            key="scoring.stock_weight",
            value=55,
            description="正股得分权重",
        )

        self._configs["scoring.cb_weight"] = ConfigEntry(
            key="scoring.cb_weight",
            value=45,
            description="转债得分权重",
        )

        # 白名单配置
        self._configs["whitelist.size"] = ConfigEntry(
            key="whitelist.size",
            value=60,
            description="白名单大小",
        )

        self._configs["whitelist.buffer_size"] = ConfigEntry(
            key="whitelist.buffer_size",
            value=10,
            description="缓冲区大小",
        )

        # 风控配置
        self._configs["risk.max_drawdown"] = ConfigEntry(
            key="risk.max_drawdown",
            value=0.10,
            description="最大回撤",
        )

        self._configs["risk.max_single_position"] = ConfigEntry(
            key="risk.max_single_position",
            value=0.05,
            description="单一持仓上限",
        )

        self._configs["risk.max_sector_position"] = ConfigEntry(
            key="risk.max_sector_position",
            value=0.20,
            description="单一行业持仓上限",
        )

        # 交易配置
        self._configs["trade.min_liquidity"] = ConfigEntry(
            key="trade.min_liquidity",
            value=1000,
            description="最小流动性(万元)",
        )

        self._configs["trade.max_slippage"] = ConfigEntry(
            key="trade.max_slippage",
            value=0.01,
            description="最大滑点",
        )

        # 数据配置
        self._configs["data.cache_ttl"] = ConfigEntry(
            key="data.cache_ttl",
            value=300,
            description="缓存过期时间(秒)",
        )

        self._configs["data.sync_interval"] = ConfigEntry(
            key="data.sync_interval",
            value=300,
            description="数据同步间隔(秒)",
        )

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置"""
        with self._lock:
            entry = self._configs.get(key)
            if entry:
                return entry.value
            return default

    def set(
        self,
        key: str,
        value: Any,
        updated_by: str = "system",
        reason: str = "",
    ):
        """设置配置"""
        with self._lock:
            old_entry = self._configs.get(key)
            old_value = old_entry.value if old_entry else None
            old_version = old_entry.version if old_entry else 0

            new_entry = ConfigEntry(
                key=key,
                value=value,
                version=old_version + 1,
                updated_at=datetime.now(),
                updated_by=updated_by,
                description=old_entry.description if old_entry else "",
            )

            self._configs[key] = new_entry

            # 记录历史
            history = ConfigHistory(
                key=key,
                old_value=old_value,
                new_value=value,
                version=new_entry.version,
                changed_at=datetime.now(),
                changed_by=updated_by,
                reason=reason,
            )
            self._history.append(history)

            # 限制历史记录数量
            if len(self._history) > 1000:
                self._history = self._history[-1000:]

            # 通知监听器
            self._notify_listeners(key, old_value, value)

            logger.info(f"[ConfigCenter] 配置更新: {key} = {value}")

    def delete(self, key: str):
        """删除配置"""
        with self._lock:
            if key in self._configs:
                del self._configs[key]
                logger.info(f"[ConfigCenter] 配置删除: {key}")

    def get_all(self) -> Dict[str, Any]:
        """获取所有配置"""
        with self._lock:
            return {k: v.value for k, v in self._configs.items()}

    def get_entry(self, key: str) -> Optional[ConfigEntry]:
        """获取配置项详情"""
        return self._configs.get(key)

    def get_history(self, key: str = None, limit: int = 50) -> List[Dict]:
        """获取配置历史"""
        history = self._history

        if key:
            history = [h for h in history if h.key == key]

        return [h.to_dict() for h in history[-limit:]]

    def subscribe(self, key: str, callback: Callable):
        """订阅配置变更"""
        if key not in self._listeners:
            self._listeners[key] = []

        self._listeners[key].append(callback)
        logger.debug(f"[ConfigCenter] 订阅配置: {key}")

    def unsubscribe(self, key: str, callback: Callable):
        """取消订阅"""
        if key in self._listeners and callback in self._listeners[key]:
            self._listeners[key].remove(callback)

    def _notify_listeners(self, key: str, old_value: Any, new_value: Any):
        """通知监听器"""
        listeners = self._listeners.get(key, [])

        for callback in listeners:
            try:
                callback(key, old_value, new_value)
            except Exception as e:
                logger.error(f"[ConfigCenter] 监听器回调失败: {e}")

    def load_from_file(self, file_path: str):
        """从文件加载配置"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            with self._lock:
                for key, value in data.items():
                    self.set(key, value, "file_loader", f"从文件加载: {file_path}")

            logger.info(f"[ConfigCenter] 从文件加载配置: {file_path}")

        except Exception as e:
            logger.error(f"[ConfigCenter] 加载配置文件失败: {e}")

    def save_to_file(self, file_path: str):
        """保存配置到文件"""
        try:
            data = self.get_all()

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.info(f"[ConfigCenter] 保存配置到文件: {file_path}")

        except Exception as e:
            logger.error(f"[ConfigCenter] 保存配置文件失败: {e}")

    def load_from_env(self, prefix: str = "SG_"):
        """从环境变量加载配置"""
        count = 0

        for env_key, env_value in os.environ.items():
            if env_key.startswith(prefix):
                # 转换键名: SG_SCORING_STOCK_WEIGHT -> scoring.stock_weight
                config_key = env_key[len(prefix):].lower().replace("_", ".")

                with self._lock:
                    # 尝试解析值类型
                    try:
                        value = json.loads(env_value)
                    except Exception:
                        value = env_value

                    self.set(config_key, value, "env_loader", "从环境变量加载")

                count += 1

        logger.info(f"[ConfigCenter] 从环境变量加载配置: {count}项")

    def get_environment(self) -> Environment:
        """获取当前环境"""
        return self._environment

    def set_environment(self, env: Environment):
        """设置环境"""
        self._environment = env
        logger.info(f"[ConfigCenter] 设置环境: {env.value}")

    def get_config_hash(self) -> str:
        """获取配置哈希"""
        config_str = json.dumps(self.get_all(), sort_keys=True)
        return hashlib.md5(config_str.encode()).hexdigest()

    def export(self) -> Dict[str, Any]:
        """导出配置"""
        with self._lock:
            return {
                "environment": self._environment.value,
                "config_hash": self.get_config_hash(),
                "configs": {k: v.to_dict() for k, v in self._configs.items()},
                "exported_at": datetime.now().isoformat(),
            }

    def import_config(self, data: Dict[str, Any], updated_by: str = "import"):
        """导入配置"""
        configs = data.get("configs", {})

        for key, entry_data in configs.items():
            self.set(
                key,
                entry_data.get("value"),
                updated_by,
                "配置导入",
            )

        logger.info(f"[ConfigCenter] 导入配置: {len(configs)}项")


# ============ 配置分组 ============

class ConfigGroup:
    """配置分组"""

    def __init__(self, prefix: str, config_center: ConfigCenter = None):
        self.prefix = prefix
        self.config = config_center or ConfigCenter()

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置"""
        full_key = f"{self.prefix}.{key}"
        return self.config.get(full_key, default)

    def set(self, key: str, value: Any, **kwargs):
        """设置配置"""
        full_key = f"{self.prefix}.{key}"
        self.config.set(full_key, value, **kwargs)

    def get_all(self) -> Dict[str, Any]:
        """获取所有配置"""
        all_configs = self.config.get_all()
        return {
            k[len(self.prefix) + 1:]: v
            for k, v in all_configs.items()
            if k.startswith(f"{self.prefix}.")
        }


# ============ 预定义配置分组 ============

class StrategyConfig(ConfigGroup):
    """策略配置"""

    def __init__(self):
        super().__init__("strategy")

    @property
    def name(self) -> str:
        return self.get("name", "西部量化可转债策略")

    @property
    def version(self) -> str:
        return self.get("version", "3.0.0")


class ScoringConfig(ConfigGroup):
    """打分配置"""

    def __init__(self):
        super().__init__("scoring")

    @property
    def stock_weight(self) -> int:
        return self.get("stock_weight", 55)

    @property
    def cb_weight(self) -> int:
        return self.get("cb_weight", 45)


class WhitelistConfig(ConfigGroup):
    """白名单配置"""

    def __init__(self):
        super().__init__("whitelist")

    @property
    def size(self) -> int:
        return self.get("size", 60)

    @property
    def buffer_size(self) -> int:
        return self.get("buffer_size", 10)


class RiskConfig(ConfigGroup):
    """风控配置"""

    def __init__(self):
        super().__init__("risk")

    @property
    def max_drawdown(self) -> float:
        return self.get("max_drawdown", 0.10)

    @property
    def max_single_position(self) -> float:
        return self.get("max_single_position", 0.05)

    @property
    def max_sector_position(self) -> float:
        return self.get("max_sector_position", 0.20)


class TradeConfig(ConfigGroup):
    """交易配置"""

    def __init__(self):
        super().__init__("trade")

    @property
    def min_liquidity(self) -> float:
        return self.get("min_liquidity", 1000)

    @property
    def max_slippage(self) -> float:
        return self.get("max_slippage", 0.01)


# ============ 便捷函数 ============

def get_config(key: str, default: Any = None) -> Any:
    """获取配置"""
    return ConfigCenter().get(key, default)


def set_config(key: str, value: Any, **kwargs):
    """设置配置"""
    ConfigCenter().set(key, value, **kwargs)


def get_config_center() -> ConfigCenter:
    """获取配置中心"""
    return ConfigCenter()


def get_strategy_config() -> StrategyConfig:
    """获取策略配置"""
    return StrategyConfig()


def get_scoring_config() -> ScoringConfig:
    """获取打分配置"""
    return ScoringConfig()


def get_whitelist_config() -> WhitelistConfig:
    """获取白名单配置"""
    return WhitelistConfig()


def get_risk_config() -> RiskConfig:
    """获取风控配置"""
    return RiskConfig()


def get_trade_config() -> TradeConfig:
    """获取交易配置"""
    return TradeConfig()
