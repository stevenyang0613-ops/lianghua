"""
用户权限系统

功能：
- 用户认证JWT
- 角色权限管理
- 账户隔离
- 操作日志审计
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Set
from enum import Enum
import hashlib
import secrets
import jwt
import logging

logger = logging.getLogger(__name__)

# JWT配置
JWT_SECRET_KEY = secrets.token_hex(32)  # 生产环境应从配置读取
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24


class Role(Enum):
    """用户角色"""
    ADMIN = 'admin'
    TRADER = 'trader'
    ANALYST = 'analyst'
    VIEWER = 'viewer'


class Permission(Enum):
    """权限"""
    # 行情权限
    VIEW_MARKET = 'view_market'

    # 交易权限
    TRADE_BUY = 'trade_buy'
    TRADE_SELL = 'trade_sell'
    TRADE_AUTO = 'trade_auto'

    # 策略权限
    VIEW_STRATEGY = 'view_strategy'
    EDIT_STRATEGY = 'edit_strategy'
    RUN_BACKTEST = 'run_backtest'

    # 账户权限
    VIEW_ACCOUNT = 'view_account'
    MANAGE_ACCOUNT = 'manage_account'

    # 系统权限
    ADMIN_USERS = 'admin_users'
    ADMIN_SYSTEM = 'admin_system'


# 角色权限映射
ROLE_PERMISSIONS: dict[Role, Set[Permission]] = {
    Role.ADMIN: {
        Permission.VIEW_MARKET,
        Permission.TRADE_BUY, Permission.TRADE_SELL, Permission.TRADE_AUTO,
        Permission.VIEW_STRATEGY, Permission.EDIT_STRATEGY, Permission.RUN_BACKTEST,
        Permission.VIEW_ACCOUNT, Permission.MANAGE_ACCOUNT,
        Permission.ADMIN_USERS, Permission.ADMIN_SYSTEM,
    },
    Role.TRADER: {
        Permission.VIEW_MARKET,
        Permission.TRADE_BUY, Permission.TRADE_SELL, Permission.TRADE_AUTO,
        Permission.VIEW_STRATEGY, Permission.RUN_BACKTEST,
        Permission.VIEW_ACCOUNT,
    },
    Role.ANALYST: {
        Permission.VIEW_MARKET,
        Permission.VIEW_STRATEGY, Permission.EDIT_STRATEGY, Permission.RUN_BACKTEST,
        Permission.VIEW_ACCOUNT,
    },
    Role.VIEWER: {
        Permission.VIEW_MARKET,
        Permission.VIEW_STRATEGY,
        Permission.VIEW_ACCOUNT,
    },
}


@dataclass
class User:
    """用户"""
    user_id: str
    username: str
    email: str
    password_hash: str
    role: Role
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.now)
    last_login: Optional[datetime] = None
    accounts: List[str] = field(default_factory=list)  # 关联账户ID列表

    def has_permission(self, permission: Permission) -> bool:
        """检查是否有指定权限"""
        return permission in ROLE_PERMISSIONS.get(self.role, set())

    def check_password(self, password: str) -> bool:
        """检查密码"""
        return self.password_hash == self._hash_password(password)

    @staticmethod
    def _hash_password(password: str) -> str:
        """密码哈希"""
        return hashlib.sha256(password.encode()).hexdigest()


@dataclass
class AuthToken:
    """认证令牌"""
    token: str
    user_id: str
    expires_at: datetime
    created_at: datetime = field(default_factory=datetime.now)


class AuthService:
    """认证服务"""

    def __init__(self):
        self._users: dict[str, User] = {}
        self._tokens: dict[str, AuthToken] = {}
        self._user_sessions: dict[str, List[str]] = {}  # user_id -> token列表

    def create_user(
        self,
        username: str,
        email: str,
        password: str,
        role: Role = Role.VIEWER,
    ) -> User:
        """创建用户"""
        if username in self._users:
            raise ValueError(f"用户名 {username} 已存在")

        user_id = f"user_{secrets.token_hex(8)}"
        user = User(
            user_id=user_id,
            username=username,
            email=email,
            password_hash=User._hash_password(password),
            role=role,
        )

        self._users[username] = user
        logger.info(f"[Auth] Created user: {username} with role: {role.value}")

        return user

    def authenticate(self, username: str, password: str) -> Optional[AuthToken]:
        """认证用户"""
        user = self._users.get(username)
        if not user:
            return None

        if not user.is_active:
            return None

        if not user.check_password(password):
            return None

        # 生成JWT令牌
        token = self._generate_token(user)

        # 更新最后登录时间
        user.last_login = datetime.now()

        # 记录会话
        if user.user_id not in self._user_sessions:
            self._user_sessions[user.user_id] = []
        self._user_sessions[user.user_id].append(token.token)

        logger.info(f"[Auth] User authenticated: {username}")

        return token

    def _generate_token(self, user: User) -> AuthToken:
        """生成JWT令牌"""
        expires_at = datetime.now() + timedelta(hours=JWT_EXPIRATION_HOURS)

        payload = {
            'user_id': user.user_id,
            'username': user.username,
            'role': user.role.value,
            'exp': expires_at.timestamp(),
        }

        token_str = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

        token = AuthToken(
            token=token_str,
            user_id=user.user_id,
            expires_at=expires_at,
        )

        self._tokens[token_str] = token

        return token

    def validate_token(self, token_str: str) -> Optional[dict]:
        """验证令牌"""
        try:
            payload = jwt.decode(token_str, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])

            # 检查是否在有效令牌列表中
            if token_str not in self._tokens:
                return None

            token = self._tokens[token_str]
            if datetime.now() > token.expires_at:
                del self._tokens[token_str]
                return None

            return payload

        except jwt.ExpiredSignatureError:
            logger.warning("[Auth] Token expired")
            return None
        except jwt.InvalidTokenError:
            logger.warning("[Auth] Invalid token")
            return None

    def logout(self, token_str: str) -> bool:
        """登出"""
        if token_str in self._tokens:
            token = self._tokens[token_str]
            del self._tokens[token_str]

            # 从用户会话中移除
            if token.user_id in self._user_sessions:
                if token_str in self._user_sessions[token.user_id]:
                    self._user_sessions[token.user_id].remove(token_str)

            logger.info(f"[Auth] User logged out: {token.user_id}")
            return True

        return False

    def get_user(self, username: str) -> Optional[User]:
        """获取用户"""
        return self._users.get(username)

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """通过ID获取用户"""
        for user in self._users.values():
            if user.user_id == user_id:
                return user
        return None

    def update_role(self, username: str, new_role: Role) -> bool:
        """更新用户角色"""
        user = self._users.get(username)
        if user:
            user.role = new_role
            logger.info(f"[Auth] Updated role for {username} to {new_role.value}")
            return True
        return False

    def deactivate_user(self, username: str) -> bool:
        """停用用户"""
        user = self._users.get(username)
        if user:
            user.is_active = False
            # 清除所有会话
            if user.user_id in self._user_sessions:
                for token_str in self._user_sessions[user.user_id]:
                    if token_str in self._tokens:
                        del self._tokens[token_str]
                del self._user_sessions[user.user_id]
            logger.info(f"[Auth] Deactivated user: {username}")
            return True
        return False

    def link_account(self, username: str, account_id: str) -> bool:
        """关联账户"""
        user = self._users.get(username)
        if user:
            if account_id not in user.accounts:
                user.accounts.append(account_id)
            return True
        return False

    def check_permission(self, username: str, permission: Permission) -> bool:
        """检查权限"""
        user = self._users.get(username)
        if user and user.is_active:
            return user.has_permission(permission)
        return False


class AuditLogger:
    """操作审计日志"""

    def __init__(self):
        self._logs: List[dict] = []
        self._max_logs = 100000

    def log(
        self,
        user_id: str,
        action: str,
        resource: str,
        details: dict = None,
        ip_address: str = None,
    ) -> None:
        """记录操作日志"""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'user_id': user_id,
            'action': action,
            'resource': resource,
            'details': details or {},
            'ip_address': ip_address,
        }

        self._logs.append(entry)

        # 限制日志数量
        if len(self._logs) > self._max_logs:
            self._logs = self._logs[-self._max_logs:]

        logger.info(f"[Audit] {user_id} {action} {resource}")

    def get_logs(
        self,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[dict]:
        """查询日志"""
        logs = self._logs.copy()

        if user_id:
            logs = [l for l in logs if l['user_id'] == user_id]

        if action:
            logs = [l for l in logs if l['action'] == action]

        if start_time:
            logs = [l for l in logs if datetime.fromisoformat(l['timestamp']) >= start_time]

        if end_time:
            logs = [l for l in logs if datetime.fromisoformat(l['timestamp']) <= end_time]

        return logs[-limit:]

    def get_user_activity(self, user_id: str, days: int = 7) -> dict:
        """获取用户活动统计"""
        cutoff = datetime.now() - timedelta(days=days)
        logs = [l for l in self._logs if l['user_id'] == user_id and datetime.fromisoformat(l['timestamp']) >= cutoff]

        action_counts = {}
        for log in logs:
            action = log['action']
            action_counts[action] = action_counts.get(action, 0) + 1

        return {
            'user_id': user_id,
            'period_days': days,
            'total_actions': len(logs),
            'action_breakdown': action_counts,
            'last_activity': logs[-1]['timestamp'] if logs else None,
        }


# 全局实例
_auth_service: Optional[AuthService] = None
_audit_logger: Optional[AuditLogger] = None


def get_auth_service() -> AuthService:
    """获取认证服务"""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
        # 创建默认管理员
        _auth_service.create_user(
            username='admin',
            email='admin@lianghua.local',
            password='admin123',  # 生产环境应从配置读取
            role=Role.ADMIN,
        )
    return _auth_service


def get_audit_logger() -> AuditLogger:
    """获取审计日志"""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
