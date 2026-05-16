"""松岗量化可转债策略 V3.0 API认证模块

功能:
- JWT认证
- 权限控制
- 限流
- API密钥管理
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Callable
from enum import Enum
import hashlib
import secrets
import time
import logging
import functools
from abc import ABC, abstractmethod

from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN, HTTP_429_TOO_MANY_REQUESTS

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class UserRole(str, Enum):
    """用户角色"""
    ADMIN = "admin"           # 管理员
    TRADER = "trader"         # 交易员
    ANALYST = "analyst"       # 分析师
    VIEWER = "viewer"         # 只读用户
    API_USER = "api_user"     # API用户


class Permission(str, Enum):
    """权限"""
    # 交易权限
    TRADE_VIEW = "trade:view"
    TRADE_EXECUTE = "trade:execute"
    TRADE_CANCEL = "trade:cancel"

    # 策略权限
    STRATEGY_VIEW = "strategy:view"
    STRATEGY_EDIT = "strategy:edit"
    STRATEGY_RUN = "strategy:run"

    # 数据权限
    DATA_VIEW = "data:view"
    DATA_EXPORT = "data:export"
    DATA_IMPORT = "data:import"

    # 系统权限
    SYSTEM_CONFIG = "system:config"
    SYSTEM_ADMIN = "system:admin"


# ============ 配置类 ============

@dataclass
class AuthConfig:
    """认证配置"""
    # JWT配置
    jwt_secret_key: str = "your-secret-key-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    jwt_refresh_expire_days: int = 7

    # API密钥配置
    api_key_length: int = 32
    api_key_expire_days: int = 365

    # 限流配置
    rate_limit_requests: int = 100      # 请求数
    rate_limit_window: int = 60          # 时间窗口(秒)
    rate_limit_burst: int = 20           # 突发请求数

    # 密码配置
    password_min_length: int = 8
    password_require_uppercase: bool = True
    password_require_lowercase: bool = True
    password_require_digit: bool = True
    password_require_special: bool = False


# ============ 角色权限映射 ============

ROLE_PERMISSIONS: Dict[UserRole, List[Permission]] = {
    UserRole.ADMIN: list(Permission),  # 所有权限
    UserRole.TRADER: [
        Permission.TRADE_VIEW,
        Permission.TRADE_EXECUTE,
        Permission.TRADE_CANCEL,
        Permission.STRATEGY_VIEW,
        Permission.STRATEGY_RUN,
        Permission.DATA_VIEW,
        Permission.DATA_EXPORT,
    ],
    UserRole.ANALYST: [
        Permission.TRADE_VIEW,
        Permission.STRATEGY_VIEW,
        Permission.STRATEGY_EDIT,
        Permission.DATA_VIEW,
        Permission.DATA_EXPORT,
        Permission.DATA_IMPORT,
    ],
    UserRole.VIEWER: [
        Permission.TRADE_VIEW,
        Permission.STRATEGY_VIEW,
        Permission.DATA_VIEW,
    ],
    UserRole.API_USER: [
        Permission.TRADE_VIEW,
        Permission.STRATEGY_VIEW,
        Permission.STRATEGY_RUN,
        Permission.DATA_VIEW,
        Permission.DATA_EXPORT,
    ],
}


# ============ 用户模型 ============

@dataclass
class User:
    """用户"""
    user_id: str
    username: str
    role: UserRole
    permissions: List[Permission] = field(default_factory=list)
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    last_login: Optional[datetime] = None

    def has_permission(self, permission: Permission) -> bool:
        """检查是否拥有权限"""
        if self.role == UserRole.ADMIN:
            return True
        return permission in self.permissions

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role.value,
            "permissions": [p.value for p in self.permissions],
            "is_active": self.is_active,
        }


@dataclass
class APIKey:
    """API密钥"""
    key_id: str
    api_key: str
    user_id: str
    name: str
    permissions: List[Permission] = field(default_factory=list)
    rate_limit: int = 100
    is_active: bool = True
    expires_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.now)
    last_used: Optional[datetime] = None
    request_count: int = 0

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at


# ============ JWT处理 ============

class JWTHandler:
    """JWT处理器"""

    def __init__(self, config: AuthConfig):
        self.config = config

    def create_token(self, user: User) -> str:
        """创建JWT令牌"""
        try:
            import jwt
        except ImportError:
            raise ImportError("请安装PyJWT: pip install PyJWT")

        payload = {
            "sub": user.user_id,
            "username": user.username,
            "role": user.role.value,
            "permissions": [p.value for p in user.permissions],
            "iat": datetime.now(),
            "exp": datetime.now() + timedelta(minutes=self.config.jwt_expire_minutes),
        }

        return jwt.encode(
            payload,
            self.config.jwt_secret_key,
            algorithm=self.config.jwt_algorithm,
        )

    def create_refresh_token(self, user: User) -> str:
        """创建刷新令牌"""
        try:
            import jwt
        except ImportError:
            raise ImportError("请安装PyJWT: pip install PyJWT")

        payload = {
            "sub": user.user_id,
            "type": "refresh",
            "iat": datetime.now(),
            "exp": datetime.now() + timedelta(days=self.config.jwt_refresh_expire_days),
        }

        return jwt.encode(
            payload,
            self.config.jwt_secret_key,
            algorithm=self.config.jwt_algorithm,
        )

    def decode_token(self, token: str) -> Optional[Dict]:
        """解码JWT令牌"""
        try:
            import jwt

            payload = jwt.decode(
                token,
                self.config.jwt_secret_key,
                algorithms=[self.config.jwt_algorithm],
            )
            return payload

        except jwt.ExpiredSignatureError:
            logger.warning("[JWT] 令牌已过期")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"[JWT] 无效令牌: {e}")
            return None
        except ImportError:
            logger.error("[JWT] PyJWT未安装")
            return None

    def verify_token(self, token: str) -> Optional[User]:
        """验证令牌并返回用户"""
        payload = self.decode_token(token)
        if not payload:
            return None

        return User(
            user_id=payload["sub"],
            username=payload["username"],
            role=UserRole(payload["role"]),
            permissions=[Permission(p) for p in payload.get("permissions", [])],
        )


# ============ 限流器 ============

class RateLimiter:
    """限流器"""

    def __init__(self, config: AuthConfig):
        self.config = config
        self._request_counts: Dict[str, List[float]] = {}

    def is_allowed(self, client_id: str, limit: int = None) -> bool:
        """检查是否允许请求"""
        limit = limit or self.config.rate_limit_requests
        now = time.time()
        window_start = now - self.config.rate_limit_window

        # 获取客户端请求记录
        if client_id not in self._request_counts:
            self._request_counts[client_id] = []

        # 清理过期记录
        self._request_counts[client_id] = [
            t for t in self._request_counts[client_id]
            if t > window_start
        ]

        # 检查请求计数
        if len(self._request_counts[client_id]) >= limit:
            return False

        # 记录本次请求
        self._request_counts[client_id].append(now)
        return True

    def get_remaining(self, client_id: str, limit: int = None) -> int:
        """获取剩余请求次数"""
        limit = limit or self.config.rate_limit_requests
        now = time.time()
        window_start = now - self.config.rate_limit_window

        if client_id not in self._request_counts:
            return limit

        # 清理过期记录
        self._request_counts[client_id] = [
            t for t in self._request_counts[client_id]
            if t > window_start
        ]

        return max(0, limit - len(self._request_counts[client_id]))

    def reset(self, client_id: str):
        """重置限流计数"""
        if client_id in self._request_counts:
            del self._request_counts[client_id]


# ============ 用户存储 ============

class UserStore:
    """用户存储"""

    def __init__(self):
        self._users: Dict[str, User] = {}
        self._api_keys: Dict[str, APIKey] = {}
        self._user_by_api_key: Dict[str, str] = {}

        # 创建默认管理员
        self._create_default_admin()

    def _create_default_admin(self):
        """创建默认管理员"""
        admin = User(
            user_id="admin",
            username="admin",
            role=UserRole.ADMIN,
            permissions=list(Permission),
        )
        self._users["admin"] = admin

    def get_user(self, user_id: str) -> Optional[User]:
        """获取用户"""
        return self._users.get(user_id)

    def get_user_by_username(self, username: str) -> Optional[User]:
        """根据用户名获取用户"""
        for user in self._users.values():
            if user.username == username:
                return user
        return None

    def add_user(self, user: User):
        """添加用户"""
        self._users[user.user_id] = user

    def update_user(self, user: User):
        """更新用户"""
        self._users[user.user_id] = user

    def delete_user(self, user_id: str):
        """删除用户"""
        if user_id in self._users:
            del self._users[user_id]

    def list_users(self) -> List[User]:
        """列出所有用户"""
        return list(self._users.values())

    # API密钥管理

    def create_api_key(
        self,
        user_id: str,
        name: str,
        permissions: List[Permission] = None,
        rate_limit: int = 100,
        expire_days: int = 365,
    ) -> APIKey:
        """创建API密钥"""
        key_id = secrets.token_hex(8)
        api_key_str = f"sg_{secrets.token_hex(16)}"

        api_key = APIKey(
            key_id=key_id,
            api_key=api_key_str,
            user_id=user_id,
            name=name,
            permissions=permissions or [],
            rate_limit=rate_limit,
            expires_at=datetime.now() + timedelta(days=expire_days),
        )

        self._api_keys[key_id] = api_key
        self._user_by_api_key[api_key_str] = key_id

        return api_key

    def get_api_key(self, api_key_str: str) -> Optional[APIKey]:
        """获取API密钥"""
        key_id = self._user_by_api_key.get(api_key_str)
        if not key_id:
            return None

        api_key = self._api_keys.get(key_id)
        if not api_key:
            return None

        # 更新使用信息
        api_key.last_used = datetime.now()
        api_key.request_count += 1

        return api_key

    def revoke_api_key(self, key_id: str):
        """撤销API密钥"""
        if key_id in self._api_keys:
            api_key = self._api_keys[key_id]
            api_key.is_active = False
            if api_key.api_key in self._user_by_api_key:
                del self._user_by_api_key[api_key.api_key]

    def list_api_keys(self, user_id: str = None) -> List[APIKey]:
        """列出API密钥"""
        keys = list(self._api_keys.values())
        if user_id:
            keys = [k for k in keys if k.user_id == user_id]
        return keys


# ============ 认证管理器 ============

class AuthManager:
    """认证管理器"""

    _instance = None

    def __new__(cls, config: AuthConfig = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: AuthConfig = None):
        if self._initialized:
            return

        self.config = config or AuthConfig()
        self.jwt_handler = JWTHandler(self.config)
        self.rate_limiter = RateLimiter(self.config)
        self.user_store = UserStore()

        self._initialized = True

    def authenticate(self, username: str, password: str) -> Optional[User]:
        """用户认证"""
        # 这里应该验证密码，简化处理
        user = self.user_store.get_user_by_username(username)
        if user and user.is_active:
            user.last_login = datetime.now()
            return user
        return None

    def login(self, username: str, password: str) -> Optional[Dict]:
        """登录，返回令牌"""
        user = self.authenticate(username, password)
        if not user:
            return None

        access_token = self.jwt_handler.create_token(user)
        refresh_token = self.jwt_handler.create_refresh_token(user)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": self.config.jwt_expire_minutes * 60,
            "user": user.to_dict(),
        }

    def refresh_token(self, refresh_token: str) -> Optional[Dict]:
        """刷新令牌"""
        payload = self.jwt_handler.decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            return None

        user = self.user_store.get_user(payload["sub"])
        if not user or not user.is_active:
            return None

        access_token = self.jwt_handler.create_token(user)
        new_refresh_token = self.jwt_handler.create_refresh_token(user)

        return {
            "access_token": access_token,
            "refresh_token": new_refresh_token,
            "token_type": "bearer",
            "expires_in": self.config.jwt_expire_minutes * 60,
        }

    def verify_api_key(self, api_key_str: str) -> Optional[User]:
        """验证API密钥"""
        api_key = self.user_store.get_api_key(api_key_str)

        if not api_key:
            return None

        if not api_key.is_active:
            return None

        if api_key.is_expired():
            return None

        user = self.user_store.get_user(api_key.user_id)
        if not user or not user.is_active:
            return None

        # 返回带有API密钥权限的用户
        return User(
            user_id=user.user_id,
            username=user.username,
            role=user.role,
            permissions=api_key.permissions or user.permissions,
        )

    def create_api_key(
        self,
        user_id: str,
        name: str,
        permissions: List[Permission] = None,
        rate_limit: int = 100,
    ) -> APIKey:
        """创建API密钥"""
        return self.user_store.create_api_key(
            user_id=user_id,
            name=name,
            permissions=permissions,
            rate_limit=rate_limit,
        )

    def check_permission(self, user: User, permission: Permission) -> bool:
        """检查权限"""
        return user.has_permission(permission)

    def check_rate_limit(self, client_id: str, limit: int = None) -> bool:
        """检查限流"""
        return self.rate_limiter.is_allowed(client_id, limit)


# ============ FastAPI依赖 ============

security = HTTPBearer(auto_error=False)


def get_auth_manager() -> AuthManager:
    """获取认证管理器"""
    return AuthManager()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    auth: AuthManager = Depends(get_auth_manager),
) -> User:
    """获取当前用户"""
    if credentials is None:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="未提供认证信息",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # 尝试JWT
    user = auth.jwt_handler.verify_token(token)
    if user:
        return user

    # 尝试API密钥
    user = auth.verify_api_key(token)
    if user:
        return user

    raise HTTPException(
        status_code=HTTP_401_UNAUTHORIZED,
        detail="无效的认证信息",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_permission(permission: Permission):
    """权限依赖"""
    async def permission_checker(
        user: User = Depends(get_current_user),
    ) -> User:
        if not user.has_permission(permission):
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail=f"没有权限: {permission.value}",
            )
        return user

    return permission_checker


def require_role(role: UserRole):
    """角色依赖"""
    async def role_checker(
        user: User = Depends(get_current_user),
    ) -> User:
        if user.role != role and user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail=f"需要角色: {role.value}",
            )
        return user

    return role_checker


async def rate_limit_dependency(
    request: Request,
    user: User = Depends(get_current_user),
    auth: AuthManager = Depends(get_auth_manager),
):
    """限流依赖"""
    client_id = f"rate:{user.user_id}"

    if not auth.check_rate_limit(client_id):
        raise HTTPException(
            status_code=HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后再试",
        )


# ============ 权限装饰器 ============

def permission_required(permission: Permission):
    """权限装饰器"""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 在FastAPI中，需要通过依赖注入获取用户
            # 这里简化处理，实际使用时需要适配
            return await func(*args, **kwargs)
        return wrapper
    return decorator


# ============ 便捷函数 ============

def get_auth_manager_singleton() -> AuthManager:
    """获取认证管理器单例"""
    return AuthManager()


def init_auth(
    jwt_secret_key: str = None,
    jwt_expire_minutes: int = 60,
) -> AuthManager:
    """初始化认证"""
    config = AuthConfig(
        jwt_secret_key=jwt_secret_key or secrets.token_hex(32),
        jwt_expire_minutes=jwt_expire_minutes,
    )
    return AuthManager(config)
