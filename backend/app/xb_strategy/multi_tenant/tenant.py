"""西部量化可转债策略 V3.0 多租户支持模块

功能:
- 租户隔离
- 资源配额
- 租户权限管理
- 数据隔离
- 计费统计
"""
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import List, Dict, Optional, Any, Set
from enum import Enum
import logging
import json
import threading
from collections import defaultdict
import hashlib

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class TenantStatus(str, Enum):
    """租户状态"""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TRIAL = "trial"
    EXPIRED = "expired"


class TenantTier(str, Enum):
    """租户等级"""
    FREE = "free"
    BASIC = "basic"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class ResourceType(str, Enum):
    """资源类型"""
    API_CALLS = "api_calls"
    SCORING_REQUESTS = "scoring_requests"
    BACKTEST_RUNS = "backtest_runs"
    DATA_STORAGE = "data_storage"  # GB
    PORTFOLIOS = "portfolios"


# ============ 数据模型 ============

@dataclass
class ResourceQuota:
    """资源配额"""
    resource_type: ResourceType
    limit: int
    used: int = 0
    period: str = "monthly"  # daily, monthly

    def to_dict(self) -> dict:
        return {
            "resource_type": self.resource_type.value,
            "limit": self.limit,
            "used": self.used,
            "period": self.period,
            "remaining": max(0, self.limit - self.used),
            "usage_percent": round(self.used / self.limit * 100, 2) if self.limit > 0 else 0,
        }

    def is_exceeded(self) -> bool:
        """检查是否超限"""
        return self.used >= self.limit


@dataclass
class Tenant:
    """租户"""
    tenant_id: str
    name: str
    tier: TenantTier
    status: TenantStatus = TenantStatus.ACTIVE
    created_at: datetime = None
    expires_at: datetime = None
    contact_email: str = ""
    contact_phone: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    quotas: Dict[ResourceType, ResourceQuota] = field(default_factory=dict)
    features: Set[str] = field(default_factory=set)
    admins: List[str] = field(default_factory=list)

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if not self.quotas:
            self._init_default_quotas()
        if not self.features:
            self._init_default_features()

    def _init_default_quotas(self):
        """初始化默认配额"""
        quota_limits = {
            TenantTier.FREE: {
                ResourceType.API_CALLS: 1000,
                ResourceType.SCORING_REQUESTS: 100,
                ResourceType.BACKTEST_RUNS: 5,
                ResourceType.DATA_STORAGE: 1,
                ResourceType.PORTFOLIOS: 1,
            },
            TenantTier.BASIC: {
                ResourceType.API_CALLS: 10000,
                ResourceType.SCORING_REQUESTS: 1000,
                ResourceType.BACKTEST_RUNS: 50,
                ResourceType.DATA_STORAGE: 10,
                ResourceType.PORTFOLIOS: 3,
            },
            TenantTier.PROFESSIONAL: {
                ResourceType.API_CALLS: 100000,
                ResourceType.SCORING_REQUESTS: 10000,
                ResourceType.BACKTEST_RUNS: 500,
                ResourceType.DATA_STORAGE: 100,
                ResourceType.PORTFOLIOS: 10,
            },
            TenantTier.ENTERPRISE: {
                ResourceType.API_CALLS: 1000000,
                ResourceType.SCORING_REQUESTS: 100000,
                ResourceType.BACKTEST_RUNS: 5000,
                ResourceType.DATA_STORAGE: 1000,
                ResourceType.PORTFOLIOS: 100,
            },
        }

        limits = quota_limits.get(self.tier, quota_limits[TenantTier.FREE])
        for resource_type, limit in limits.items():
            self.quotas[resource_type] = ResourceQuota(
                resource_type=resource_type,
                limit=limit,
                used=0,
                period="monthly",
            )

    def _init_default_features(self):
        """初始化默认功能"""
        features_by_tier = {
            TenantTier.FREE: {"scoring", "whitelist"},
            TenantTier.BASIC: {"scoring", "whitelist", "signals", "backtest"},
            TenantTier.PROFESSIONAL: {"scoring", "whitelist", "signals", "backtest", "risk", "api"},
            TenantTier.ENTERPRISE: {"scoring", "whitelist", "signals", "backtest", "risk", "api", "ml", "custom"},
        }
        self.features = features_by_tier.get(self.tier, features_by_tier[TenantTier.FREE])

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "name": self.name,
            "tier": self.tier.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "contact_email": self.contact_email,
            "quotas": {k.value: v.to_dict() for k, v in self.quotas.items()},
            "features": list(self.features),
            "admins": self.admins,
        }

    def has_feature(self, feature: str) -> bool:
        """检查是否有功能"""
        return feature in self.features

    def check_quota(self, resource_type: ResourceType, amount: int = 1) -> bool:
        """检查配额"""
        quota = self.quotas.get(resource_type)
        if not quota:
            return False
        return quota.used + amount <= quota.limit

    def use_resource(self, resource_type: ResourceType, amount: int = 1) -> bool:
        """使用资源"""
        if not self.check_quota(resource_type, amount):
            return False

        quota = self.quotas.get(resource_type)
        if quota:
            quota.used += amount
        return True


@dataclass
class TenantUser:
    """租户用户"""
    user_id: str
    tenant_id: str
    username: str
    email: str
    role: str  # admin, analyst, viewer
    created_at: datetime = None
    last_login: datetime = None
    permissions: Set[str] = field(default_factory=set)

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if not self.permissions:
            self._init_default_permissions()

    def _init_default_permissions(self):
        """初始化默认权限"""
        permissions_by_role = {
            "admin": {"read", "write", "delete", "manage_users", "manage_settings"},
            "analyst": {"read", "write", "run_backtest"},
            "viewer": {"read"},
        }
        self.permissions = permissions_by_role.get(self.role, {"read"})

    def has_permission(self, permission: str) -> bool:
        """检查权限"""
        return permission in self.permissions

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "permissions": list(self.permissions),
        }


# ============ 租户管理器 ============

class TenantManager:
    """租户管理器"""

    def __init__(self):
        self._tenants: Dict[str, Tenant] = {}
        self._users: Dict[str, TenantUser] = {}
        self._user_tenant_map: Dict[str, str] = {}  # user_id -> tenant_id
        self._usage_history: Dict[str, List[Dict]] = defaultdict(list)  # tenant_id -> usage records
        self._lock = threading.Lock()

    def create_tenant(
        self,
        name: str,
        tier: TenantTier,
        contact_email: str = "",
        admin_user: str = None,
        expires_at: datetime = None,
    ) -> Tenant:
        """创建租户"""
        tenant_id = self._generate_tenant_id(name)

        tenant = Tenant(
            tenant_id=tenant_id,
            name=name,
            tier=tier,
            status=TenantStatus.ACTIVE,
            contact_email=contact_email,
            expires_at=expires_at,
        )

        if admin_user:
            tenant.admins.append(admin_user)

        with self._lock:
            self._tenants[tenant_id] = tenant

        logger.info(f"[TenantManager] 创建租户: {name} ({tenant_id}), 等级: {tier.value}")

        return tenant

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """获取租户"""
        return self._tenants.get(tenant_id)

    def get_tenant_by_user(self, user_id: str) -> Optional[Tenant]:
        """通过用户获取租户"""
        tenant_id = self._user_tenant_map.get(user_id)
        if tenant_id:
            return self._tenants.get(tenant_id)
        return None

    def update_tenant(
        self,
        tenant_id: str,
        tier: TenantTier = None,
        status: TenantStatus = None,
        quotas: Dict[ResourceType, int] = None,
    ) -> Optional[Tenant]:
        """更新租户"""
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return None

        with self._lock:
            if tier:
                tenant.tier = tier
                tenant._init_default_quotas()
                tenant._init_default_features()

            if status:
                tenant.status = status

            if quotas:
                for resource_type, limit in quotas.items():
                    if resource_type in tenant.quotas:
                        tenant.quotas[resource_type].limit = limit

        return tenant

    def delete_tenant(self, tenant_id: str) -> bool:
        """删除租户"""
        with self._lock:
            if tenant_id in self._tenants:
                del self._tenants[tenant_id]
                # 清理用户映射
                self._user_tenant_map = {
                    k: v for k, v in self._user_tenant_map.items()
                    if v != tenant_id
                }
                return True
        return False

    def add_user(
        self,
        tenant_id: str,
        username: str,
        email: str,
        role: str = "viewer",
    ) -> Optional[TenantUser]:
        """添加用户"""
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return None

        user_id = self._generate_user_id(tenant_id, username)

        user = TenantUser(
            user_id=user_id,
            tenant_id=tenant_id,
            username=username,
            email=email,
            role=role,
        )

        with self._lock:
            self._users[user_id] = user
            self._user_tenant_map[user_id] = tenant_id

        logger.info(f"[TenantManager] 添加用户: {username} -> {tenant_id}")

        return user

    def get_user(self, user_id: str) -> Optional[TenantUser]:
        """获取用户"""
        return self._users.get(user_id)

    def remove_user(self, user_id: str) -> bool:
        """移除用户"""
        with self._lock:
            if user_id in self._users:
                del self._users[user_id]
                if user_id in self._user_tenant_map:
                    del self._user_tenant_map[user_id]
                return True
        return False

    def record_usage(
        self,
        tenant_id: str,
        resource_type: ResourceType,
        amount: int,
        details: Dict = None,
    ) -> bool:
        """记录使用"""
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return False

        # 更新配额
        if not tenant.use_resource(resource_type, amount):
            logger.warning(f"[TenantManager] 配额超限: {tenant_id} - {resource_type.value}")
            return False

        # 记录历史
        usage_record = {
            "timestamp": datetime.now().isoformat(),
            "resource_type": resource_type.value,
            "amount": amount,
            "details": details or {},
        }

        with self._lock:
            self._usage_history[tenant_id].append(usage_record)
            # 保留最近10000条记录
            if len(self._usage_history[tenant_id]) > 10000:
                self._usage_history[tenant_id] = self._usage_history[tenant_id][-10000:]

        return True

    def get_usage_history(
        self,
        tenant_id: str,
        resource_type: ResourceType = None,
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> List[Dict]:
        """获取使用历史"""
        history = self._usage_history.get(tenant_id, [])

        # 过滤
        if resource_type:
            history = [r for r in history if r["resource_type"] == resource_type.value]

        if start_date:
            history = [r for r in history if datetime.fromisoformat(r["timestamp"]) >= start_date]

        if end_date:
            history = [r for r in history if datetime.fromisoformat(r["timestamp"]) <= end_date]

        return history

    def get_tenant_quotas(self, tenant_id: str) -> Dict[str, Any]:
        """获取租户配额"""
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return {}

        return {
            "tenant_id": tenant_id,
            "tier": tenant.tier.value,
            "quotas": {k.value: v.to_dict() for k, v in tenant.quotas.items()},
        }

    def check_access(
        self,
        tenant_id: str,
        user_id: str,
        resource: str,
        action: str,
    ) -> bool:
        """检查访问权限"""
        tenant = self._tenants.get(tenant_id)
        if not tenant or tenant.status != TenantStatus.ACTIVE:
            return False

        user = self._users.get(user_id)
        if not user or user.tenant_id != tenant_id:
            return False

        # 检查功能权限
        if not tenant.has_feature(resource):
            return False

        # 检查用户权限
        if action == "read":
            return user.has_permission("read")
        elif action == "write":
            return user.has_permission("write")
        elif action == "delete":
            return user.has_permission("delete")

        return False

    def list_tenants(self, status: TenantStatus = None) -> List[Tenant]:
        """列出租户"""
        tenants = list(self._tenants.values())

        if status:
            tenants = [t for t in tenants if t.status == status]

        return tenants

    def _generate_tenant_id(self, name: str) -> str:
        """生成租户ID"""
        base = f"{name}_{datetime.now().isoformat()}"
        return f"tenant_{hashlib.md5(base.encode()).hexdigest()[:12]}"

    def _generate_user_id(self, tenant_id: str, username: str) -> str:
        """生成用户ID"""
        base = f"{tenant_id}_{username}"
        return f"user_{hashlib.md5(base.encode()).hexdigest()[:12]}"


# ============ 数据隔离管理 ============

class DataIsolationManager:
    """数据隔离管理器"""

    def __init__(self):
        self._tenant_data_prefix = "tenant_"

    def get_tenant_key(self, tenant_id: str, key: str) -> str:
        """获取租户数据键"""
        return f"{self._tenant_data_prefix}{tenant_id}:{key}"

    def get_tenant_table(self, tenant_id: str, table: str) -> str:
        """获取租户表名"""
        return f"{table}_{tenant_id.replace('-', '_')}"

    def add_tenant_filter(self, tenant_id: str, query: str) -> str:
        """添加租户过滤"""
        if "WHERE" in query.upper():
            return f"{query} AND tenant_id = '{tenant_id}'"
        else:
            return f"{query} WHERE tenant_id = '{tenant_id}'"

    def validate_tenant_access(self, tenant_id: str, resource_tenant_id: str) -> bool:
        """验证租户访问"""
        return tenant_id == resource_tenant_id


# ============ 计费统计 ============

class BillingManager:
    """计费管理器"""

    # 价格配置
    PRICING = {
        TenantTier.FREE: {"base": 0, "per_call": 0},
        TenantTier.BASIC: {"base": 99, "per_call": 0.001},
        TenantTier.PROFESSIONAL: {"base": 499, "per_call": 0.0005},
        TenantTier.ENTERPRISE: {"base": 4999, "per_call": 0.0001},
    }

    def __init__(self, tenant_manager: TenantManager):
        self.tenant_manager = tenant_manager
        self._invoices: Dict[str, List[Dict]] = defaultdict(list)

    def calculate_bill(self, tenant_id: str, period_start: date, period_end: date) -> Dict:
        """计算账单"""
        tenant = self.tenant_manager.get_tenant(tenant_id)
        if not tenant:
            return {}

        pricing = self.PRICING.get(tenant.tier, self.PRICING[TenantTier.FREE])

        # 获取使用量
        usage_history = self.tenant_manager.get_usage_history(
            tenant_id,
            start_date=datetime.combine(period_start, datetime.min.time()),
            end_date=datetime.combine(period_end, datetime.max.time()),
        )

        # 统计API调用
        api_calls = sum(
            r["amount"] for r in usage_history
            if r["resource_type"] == ResourceType.API_CALLS.value
        )

        # 计算费用
        base_fee = pricing["base"]
        usage_fee = api_calls * pricing["per_call"]
        total_fee = base_fee + usage_fee

        invoice = {
            "invoice_id": f"inv_{tenant_id}_{period_start.strftime('%Y%m')}",
            "tenant_id": tenant_id,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "base_fee": base_fee,
            "usage_fee": round(usage_fee, 2),
            "total_fee": round(total_fee, 2),
            "api_calls": api_calls,
            "currency": "CNY",
            "status": "pending",
            "created_at": datetime.now().isoformat(),
        }

        self._invoices[tenant_id].append(invoice)

        return invoice

    def get_invoices(self, tenant_id: str) -> List[Dict]:
        """获取账单"""
        return self._invoices.get(tenant_id, [])

    def get_usage_summary(self, tenant_id: str) -> Dict:
        """获取使用摘要"""
        tenant = self.tenant_manager.get_tenant(tenant_id)
        if not tenant:
            return {}

        quotas = tenant.quotas

        return {
            "tenant_id": tenant_id,
            "tier": tenant.tier.value,
            "current_period": {
                "api_calls": quotas.get(ResourceType.API_CALLS, ResourceQuota(ResourceType.API_CALLS, 0)).to_dict(),
                "scoring_requests": quotas.get(ResourceType.SCORING_REQUESTS, ResourceQuota(ResourceType.SCORING_REQUESTS, 0)).to_dict(),
                "backtest_runs": quotas.get(ResourceType.BACKTEST_RUNS, ResourceQuota(ResourceType.BACKTEST_RUNS, 0)).to_dict(),
            },
            "estimated_cost": self._estimate_cost(tenant),
        }

    def _estimate_cost(self, tenant: Tenant) -> float:
        """预估成本"""
        pricing = self.PRICING.get(tenant.tier, self.PRICING[TenantTier.FREE])

        api_quota = tenant.quotas.get(ResourceType.API_CALLS)
        if not api_quota:
            return 0

        estimated_usage = api_quota.used + (api_quota.limit - api_quota.used) * 0.5

        return round(
            pricing["base"] + estimated_usage * pricing["per_call"],
            2
        )


# ============ 便捷函数 ============

def create_tenant_manager() -> TenantManager:
    """创建租户管理器"""
    return TenantManager()


def create_billing_manager(tenant_manager: TenantManager) -> BillingManager:
    """创建计费管理器"""
    return BillingManager(tenant_manager)
