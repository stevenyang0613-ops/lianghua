"""西部量化可转债策略 V3.0 安全加固模块

功能:
- SQL注入防护
- XSS防护
- API限流增强
- 输入验证
- 敏感数据脱敏
- 安全审计日志
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Callable, Pattern
from enum import Enum
import logging
import re
import html
import json
import hashlib
import secrets
import time
import threading
from collections import defaultdict
from functools import wraps
import ipaddress

logger = logging.getLogger(__name__)


# ============ 枚举类型 ============

class ThreatLevel(str, Enum):
    """威胁等级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AttackType(str, Enum):
    """攻击类型"""
    SQL_INJECTION = "sql_injection"
    XSS = "xss"
    CSRF = "csrf"
    PATH_TRAVERSAL = "path_traversal"
    COMMAND_INJECTION = "command_injection"
    BRUTE_FORCE = "brute_force"
    DDOS = "ddos"


# ============ 配置类 ============

@dataclass
class SecurityConfig:
    """安全配置"""
    # SQL注入防护
    sql_injection_enabled: bool = True
    sql_max_query_length: int = 10000

    # XSS防护
    xss_enabled: bool = True
    xss_max_input_length: int = 100000

    # 限流配置
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 100
    rate_limit_window: int = 60  # 秒
    rate_limit_burst: int = 20

    # IP黑名单
    ip_blacklist_enabled: bool = True
    ip_blacklist_ttl: int = 3600  # 秒

    # 输入验证
    input_validation_enabled: bool = True
    max_input_depth: int = 10
    max_array_length: int = 1000


# ============ SQL注入防护 ============

class SQLInjectionProtector:
    """SQL注入防护器"""

    # SQL注入模式
    SQL_PATTERNS = [
        # 注释
        r'--',
        r'/\*.*\*/',
        r'#',
        # UNION注入
        r'\bUNION\b.*\bSELECT\b',
        r'\bUNION\b.*\bALL\b',
        # 堆叠查询
        r';\s*SELECT\b',
        r';\s*INSERT\b',
        r';\s*UPDATE\b',
        r';\s*DELETE\b',
        r';\s*DROP\b',
        # 布尔盲注
        r'\bOR\b\s+\d+\s*=\s*\d+',
        r'\bAND\b\s+\d+\s*=\s*\d+',
        r'\bOR\b\s+[\'"].*[\'"]\s*=\s*[\'"]',
        # 时间盲注
        r'\bSLEEP\s*\(',
        r'\bBENCHMARK\s*\(',
        r'\bWAITFOR\b.*\bDELAY\b',
        # 危险函数
        r'\bLOAD_FILE\s*\(',
        r'\bINTO\s+OUTFILE\b',
        r'\bINTO\s+DUMPFILE\b',
        # 信息收集
        r'\bVERSION\s*\(\)',
        r'\bDATABASE\s*\(\)',
        r'\bUSER\s*\(\)',
        r'@@version',
        r'@@hostname',
        # 十六进制编码
        r'0x[0-9a-fA-F]+',
        # 字符串连接
        r'\bCONCAT\s*\(',
        r'\bCONCAT_WS\s*\(',
        r'\bGROUP_CONCAT\s*\(',
    ]

    # 白名单模式（允许的模式）
    ALLOWED_PATTERNS = [
        r'^\d+$',  # 纯数字
        r'^[a-zA-Z0-9_-]+$',  # 字母数字下划线
        r'^\d{4}-\d{2}-\d{2}$',  # 日期
    ]

    def __init__(self, config: SecurityConfig = None):
        self.config = config or SecurityConfig()
        self._compiled_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.SQL_PATTERNS
        ]
        self._allowed_patterns = [
            re.compile(pattern) for pattern in self.ALLOWED_PATTERNS
        ]

    def detect(self, input_value: str) -> Dict[str, Any]:
        """检测SQL注入"""
        if not self.config.sql_injection_enabled:
            return {"safe": True, "threats": []}

        if not isinstance(input_value, str):
            return {"safe": True, "threats": []}

        # 检查长度
        if len(input_value) > self.config.sql_max_query_length:
            return {
                "safe": False,
                "threats": [{"type": "length_exceeded", "value": len(input_value)}]
            }

        # 检查白名单
        for pattern in self._allowed_patterns:
            if pattern.match(input_value):
                return {"safe": True, "threats": []}

        # 检查威胁模式
        threats = []
        for i, pattern in enumerate(self._compiled_patterns):
            if pattern.search(input_value):
                threats.append({
                    "type": AttackType.SQL_INJECTION.value,
                    "pattern": self.SQL_PATTERNS[i],
                    "match": pattern.search(input_value).group(),
                })

        return {
            "safe": len(threats) == 0,
            "threats": threats,
            "level": ThreatLevel.HIGH.value if threats else ThreatLevel.LOW.value,
        }

    def sanitize(self, input_value: str) -> str:
        """清理输入"""
        if not isinstance(input_value, str):
            return str(input_value)

        # 移除危险字符
        result = input_value

        # 转义单引号
        result = result.replace("'", "''")

        # 移除注释
        result = re.sub(r'--.*$', '', result, flags=re.MULTILINE)
        result = re.sub(r'/\*.*?\*/', '', result, flags=re.DOTALL)

        return result.strip()

    def validate_parameter(self, param_name: str, param_value: Any) -> bool:
        """验证参数"""
        detection = self.detect(str(param_value))
        return detection["safe"]


# ============ XSS防护 ============

class XSSProtector:
    """XSS防护器"""

    # XSS模式
    XSS_PATTERNS = [
        # Script标签
        r'<\s*script[^>]*>.*?<\s*/\s*script\s*>',
        r'<\s*script[^>]*>',
        # 事件处理器
        r'\bon\w+\s*=',
        # JavaScript协议
        r'javascript\s*:',
        r'vbscript\s*:',
        r'data\s*:\s*text/html',
        # iframe
        r'<\s*iframe[^>]*>',
        # object/embed
        r'<\s*object[^>]*>',
        r'<\s*embed[^>]*>',
        # style表达式
        r'expression\s*\(',
        r'@import\s+',
        # HTML实体编码绕过
        r'&#x?[0-9a-fA-F]+;',
        r'&#[0-9]+;',
        # SVG
        r'<\s*svg[^>]*>',
        r'<\s*math[^>]*>',
    ]

    # 允许的HTML标签
    ALLOWED_TAGS = [
        'p', 'br', 'b', 'i', 'u', 'strong', 'em',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'ul', 'ol', 'li', 'a', 'img',
        'table', 'tr', 'td', 'th', 'thead', 'tbody',
    ]

    # 允许的属性
    ALLOWED_ATTRIBUTES = {
        'a': ['href', 'title'],
        'img': ['src', 'alt', 'title'],
        '*': ['class', 'id'],
    }

    def __init__(self, config: SecurityConfig = None):
        self.config = config or SecurityConfig()
        self._compiled_patterns = [
            re.compile(pattern, re.IGNORECASE | re.DOTALL)
            for pattern in self.XSS_PATTERNS
        ]

    def detect(self, input_value: str) -> Dict[str, Any]:
        """检测XSS"""
        if not self.config.xss_enabled:
            return {"safe": True, "threats": []}

        if not isinstance(input_value, str):
            return {"safe": True, "threats": []}

        # 检查长度
        if len(input_value) > self.config.xss_max_input_length:
            return {
                "safe": False,
                "threats": [{"type": "length_exceeded", "value": len(input_value)}]
            }

        # 检查威胁模式
        threats = []
        for i, pattern in enumerate(self._compiled_patterns):
            matches = pattern.findall(input_value)
            if matches:
                threats.append({
                    "type": AttackType.XSS.value,
                    "pattern": self.XSS_PATTERNS[i],
                    "matches": matches[:5],  # 限制返回数量
                })

        return {
            "safe": len(threats) == 0,
            "threats": threats,
            "level": ThreatLevel.HIGH.value if threats else ThreatLevel.LOW.value,
        }

    def sanitize(self, input_value: str) -> str:
        """清理输入 - HTML转义"""
        if not isinstance(input_value, str):
            return str(input_value)

        # HTML实体编码
        result = html.escape(input_value, quote=True)

        return result

    def sanitize_html(self, input_value: str) -> str:
        """清理HTML - 允许安全标签"""
        if not isinstance(input_value, str):
            return ""

        # 先完全转义
        result = self.sanitize(input_value)

        # 这里的实现简化，实际应使用 bleach 等库
        # 仅保留允许的标签

        return result


# ============ API限流 ============

class RateLimiter:
    """API限流器"""

    def __init__(self, config: SecurityConfig = None):
        self.config = config or SecurityConfig()
        self._requests: Dict[str, List[float]] = defaultdict(list)
        self._blocked: Dict[str, float] = {}
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> Dict[str, Any]:
        """检查是否允许请求"""
        if not self.config.rate_limit_enabled:
            return {"allowed": True, "remaining": self.config.rate_limit_requests}

        now = time.time()
        window_start = now - self.config.rate_limit_window

        with self._lock:
            # 检查是否被阻止
            if key in self._blocked:
                if now < self._blocked[key]:
                    return {
                        "allowed": False,
                        "reason": "temporarily_blocked",
                        "retry_after": int(self._blocked[key] - now),
                    }
                else:
                    del self._blocked[key]

            # 清理过期请求
            self._requests[key] = [
                t for t in self._requests[key] if t > window_start
            ]

            # 检查请求数量
            current_count = len(self._requests[key])

            if current_count >= self.config.rate_limit_requests:
                # 超出限制，阻止一段时间
                self._blocked[key] = now + 300  # 阻止5分钟

                return {
                    "allowed": False,
                    "reason": "rate_limit_exceeded",
                    "retry_after": self.config.rate_limit_window,
                    "current": current_count,
                    "limit": self.config.rate_limit_requests,
                }

            # 记录请求
            self._requests[key].append(now)

            return {
                "allowed": True,
                "remaining": self.config.rate_limit_requests - current_count - 1,
                "reset": int(window_start + self.config.rate_limit_window),
            }

    def get_stats(self, key: str = None) -> Dict[str, Any]:
        """获取统计"""
        with self._lock:
            if key:
                return {
                    "requests": len(self._requests.get(key, [])),
                    "blocked": key in self._blocked,
                }
            else:
                return {
                    "total_keys": len(self._requests),
                    "total_blocked": len(self._blocked),
                    "top_consumers": sorted(
                        [(k, len(v)) for k, v in self._requests.items()],
                        key=lambda x: x[1],
                        reverse=True,
                    )[:10],
                }


class TokenBucket:
    """令牌桶限流"""

    def __init__(self, rate: float = 10.0, capacity: int = 100):
        self.rate = rate  # 令牌/秒
        self.capacity = capacity
        self._tokens: Dict[str, float] = defaultdict(lambda: capacity)
        self._last_update: Dict[str, float] = defaultdict(time.time)
        self._lock = threading.Lock()

    def consume(self, key: str, tokens: int = 1) -> bool:
        """消费令牌"""
        with self._lock:
            now = time.time()
            elapsed = now - self._last_update[key]

            # 补充令牌
            self._tokens[key] = min(
                self.capacity,
                self._tokens[key] + elapsed * self.rate
            )
            self._last_update[key] = now

            # 检查并消费
            if self._tokens[key] >= tokens:
                self._tokens[key] -= tokens
                return True

            return False

    def get_tokens(self, key: str) -> float:
        """获取当前令牌数"""
        with self._lock:
            now = time.time()
            elapsed = now - self._last_update[key]
            return min(
                self.capacity,
                self._tokens[key] + elapsed * self.rate
            )


# ============ 输入验证 ============

class InputValidator:
    """输入验证器"""

    def __init__(self, config: SecurityConfig = None):
        self.config = config or SecurityConfig()
        self._validators: Dict[str, Callable] = {}

    def register_validator(self, name: str, validator: Callable):
        """注册验证器"""
        self._validators[name] = validator

    def validate(self, data: Any, schema: Dict = None) -> Dict[str, Any]:
        """验证数据"""
        errors = []

        # 基础验证
        if isinstance(data, dict):
            errors.extend(self._validate_dict(data, 0))
        elif isinstance(data, list):
            errors.extend(self._validate_list(data, 0))
        elif isinstance(data, str):
            errors.extend(self._validate_string(data))

        # Schema验证
        if schema:
            errors.extend(self._validate_schema(data, schema))

        return {
            "valid": len(errors) == 0,
            "errors": errors,
        }

    def _validate_dict(self, data: Dict, depth: int) -> List[str]:
        """验证字典"""
        errors = []

        if depth > self.config.max_input_depth:
            errors.append(f"嵌套深度超过限制: {depth}")
            return errors

        for key, value in data.items():
            # 验证键
            if not isinstance(key, str):
                errors.append(f"键必须是字符串: {key}")

            # 验证值
            if isinstance(value, dict):
                errors.extend(self._validate_dict(value, depth + 1))
            elif isinstance(value, list):
                errors.extend(self._validate_list(value, depth + 1))

        return errors

    def _validate_list(self, data: List, depth: int) -> List[str]:
        """验证列表"""
        errors = []

        if len(data) > self.config.max_array_length:
            errors.append(f"数组长度超过限制: {len(data)}")

        if depth > self.config.max_input_depth:
            errors.append(f"嵌套深度超过限制: {depth}")
            return errors

        for item in data:
            if isinstance(item, dict):
                errors.extend(self._validate_dict(item, depth + 1))
            elif isinstance(item, list):
                errors.extend(self._validate_list(item, depth + 1))

        return errors

    def _validate_string(self, data: str) -> List[str]:
        """验证字符串"""
        errors = []

        # 检查控制字符
        if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', data):
            errors.append("字符串包含非法控制字符")

        return errors

    def _validate_schema(self, data: Any, schema: Dict) -> List[str]:
        """Schema验证"""
        errors = []

        schema_type = schema.get("type")
        if schema_type:
            if schema_type == "string" and not isinstance(data, str):
                errors.append(f"期望字符串，得到: {type(data).__name__}")
            elif schema_type == "number" and not isinstance(data, (int, float)):
                errors.append(f"期望数字，得到: {type(data).__name__}")
            elif schema_type == "integer" and not isinstance(data, int):
                errors.append(f"期望整数，得到: {type(data).__name__}")
            elif schema_type == "boolean" and not isinstance(data, bool):
                errors.append(f"期望布尔值，得到: {type(data).__name__}")
            elif schema_type == "array" and not isinstance(data, list):
                errors.append(f"期望数组，得到: {type(data).__name__}")
            elif schema_type == "object" and not isinstance(data, dict):
                errors.append(f"期望对象，得到: {type(data).__name__}")

        # 最小/最大值
        if isinstance(data, (int, float)):
            if "minimum" in schema and data < schema["minimum"]:
                errors.append(f"值 {data} 小于最小值 {schema['minimum']}")
            if "maximum" in schema and data > schema["maximum"]:
                errors.append(f"值 {data} 大于最大值 {schema['maximum']}")

        # 字符串长度
        if isinstance(data, str):
            if "minLength" in schema and len(data) < schema["minLength"]:
                errors.append(f"字符串长度 {len(data)} 小于最小长度 {schema['minLength']}")
            if "maxLength" in schema and len(data) > schema["maxLength"]:
                errors.append(f"字符串长度 {len(data)} 大于最大长度 {schema['maxLength']}")

        # 枚举值
        if "enum" in schema and data not in schema["enum"]:
            errors.append(f"值 {data} 不在允许的枚举值中")

        # 正则匹配
        if "pattern" in schema and isinstance(data, str):
            if not re.match(schema["pattern"], data):
                errors.append(f"值 '{data}' 不匹配模式 '{schema['pattern']}'")

        return errors


# ============ 敏感数据脱敏 ============

class DataMasker:
    """数据脱敏器"""

    @staticmethod
    def mask_phone(phone: str) -> str:
        """脱敏手机号"""
        if not phone or len(phone) < 7:
            return phone
        return phone[:3] + "****" + phone[-4:]

    @staticmethod
    def mask_email(email: str) -> str:
        """脱敏邮箱"""
        if not email or '@' not in email:
            return email
        parts = email.split('@')
        name = parts[0]
        if len(name) <= 2:
            return name[0] + "***@" + parts[1]
        return name[:2] + "***@" + parts[1]

    @staticmethod
    def mask_id_card(id_card: str) -> str:
        """脱敏身份证"""
        if not id_card or len(id_card) < 10:
            return id_card
        return id_card[:6] + "********" + id_card[-4:]

    @staticmethod
    def mask_bank_card(card: str) -> str:
        """脱敏银行卡"""
        if not card or len(card) < 8:
            return card
        return card[:4] + "****" + card[-4:]

    @staticmethod
    def mask_password(password: str) -> str:
        """脱敏密码"""
        if not password:
            return ""
        return "*" * len(password)

    @staticmethod
    def mask_api_key(key: str) -> str:
        """脱敏API Key"""
        if not key or len(key) < 8:
            return key
        return key[:4] + "****" + key[-4:]


# ============ IP黑名单 ============

class IPBlacklist:
    """IP黑名单"""

    def __init__(self, config: SecurityConfig = None):
        self.config = config or SecurityConfig()
        self._blacklist: Dict[str, float] = {}
        self._lock = threading.Lock()

    def add(self, ip: str, duration: int = None):
        """添加到黑名单"""
        duration = duration or self.config.ip_blacklist_ttl

        with self._lock:
            self._blacklist[ip] = time.time() + duration

        logger.warning(f"[IPBlacklist] 添加IP到黑名单: {ip}, 持续时间: {duration}秒")

    def remove(self, ip: str):
        """从黑名单移除"""
        with self._lock:
            if ip in self._blacklist:
                del self._blacklist[ip]

    def is_blocked(self, ip: str) -> bool:
        """检查是否被阻止"""
        with self._lock:
            if ip not in self._blacklist:
                return False

            if time.time() > self._blacklist[ip]:
                del self._blacklist[ip]
                return False

            return True

    def get_all(self) -> List[Dict[str, Any]]:
        """获取所有黑名单"""
        now = time.time()
        with self._lock:
            return [
                {"ip": ip, "expires_at": exp}
                for ip, exp in self._blacklist.items()
                if exp > now
            ]


# ============ 安全中间件 ============

class SecurityMiddleware:
    """安全中间件"""

    def __init__(self, config: SecurityConfig = None):
        self.config = config or SecurityConfig()
        self.sql_protector = SQLInjectionProtector(config)
        self.xss_protector = XSSProtector(config)
        self.rate_limiter = RateLimiter(config)
        self.input_validator = InputValidator(config)
        self.ip_blacklist = IPBlacklist(config)
        self.data_masker = DataMasker()

    def check_request(self, request: Dict) -> Dict[str, Any]:
        """检查请求"""
        results = {
            "safe": True,
            "threats": [],
            "actions": [],
        }

        # 检查IP黑名单
        client_ip = request.get("ip", "")
        if self.ip_blacklist.is_blocked(client_ip):
            results["safe"] = False
            results["threats"].append({
                "type": "ip_blocked",
                "ip": client_ip,
            })
            results["actions"].append("block")
            return results

        # 检查限流
        rate_result = self.rate_limiter.is_allowed(client_ip)
        if not rate_result["allowed"]:
            results["safe"] = False
            results["threats"].append({
                "type": "rate_limit",
                "retry_after": rate_result.get("retry_after"),
            })
            results["actions"].append("throttle")
            return results

        # 检查SQL注入
        if "query" in request:
            sql_result = self.sql_protector.detect(request["query"])
            if not sql_result["safe"]:
                results["safe"] = False
                results["threats"].extend(sql_result["threats"])
                results["actions"].append("sanitize")

        # 检查XSS
        if "body" in request:
            xss_result = self.xss_protector.detect(str(request["body"]))
            if not xss_result["safe"]:
                results["safe"] = False
                results["threats"].extend(xss_result["threats"])
                results["actions"].append("sanitize")

        return results

    def sanitize_request(self, request: Dict) -> Dict:
        """清理请求"""
        sanitized = request.copy()

        if "query" in sanitized:
            sanitized["query"] = self.sql_protector.sanitize(sanitized["query"])

        if "body" in sanitized:
            sanitized["body"] = self.xss_protector.sanitize(str(sanitized["body"]))

        return sanitized


# ============ 安全审计日志 ============

class SecurityAuditLogger:
    """安全审计日志"""

    def __init__(self):
        self._logs: List[Dict] = []
        self._lock = threading.Lock()

    def log(
        self,
        event_type: str,
        severity: str,
        details: Dict,
        request: Dict = None,
    ):
        """记录安全事件"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "severity": severity,
            "details": details,
            "request": {
                "ip": request.get("ip") if request else None,
                "path": request.get("path") if request else None,
                "method": request.get("method") if request else None,
            },
        }

        with self._lock:
            self._logs.append(entry)

            # 保留最近10000条
            if len(self._logs) > 10000:
                self._logs = self._logs[-10000:]

        # 记录到日志
        if severity in ["high", "critical"]:
            logger.warning(f"[SecurityAudit] {event_type}: {details}")
        else:
            logger.info(f"[SecurityAudit] {event_type}: {details}")

    def log_attack(self, attack_type: AttackType, request: Dict, details: Dict):
        """记录攻击"""
        self.log(
            event_type="attack_detected",
            severity="high",
            details={
                "attack_type": attack_type.value,
                **details,
            },
            request=request,
        )

    def get_logs(
        self,
        event_type: str = None,
        severity: str = None,
        limit: int = 100,
    ) -> List[Dict]:
        """获取日志"""
        with self._lock:
            logs = self._logs.copy()

        if event_type:
            logs = [l for l in logs if l["event_type"] == event_type]
        if severity:
            logs = [l for l in logs if l["severity"] == severity]

        return logs[-limit:]


# ============ 安全装饰器 ============

def secure_request(middleware: SecurityMiddleware = None):
    """安全请求装饰器"""
    mw = middleware or SecurityMiddleware()

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 检查请求（简化版）
            request_data = kwargs.get("request", {})

            check_result = mw.check_request(request_data)
            if not check_result["safe"]:
                raise SecurityError(f"安全检查失败: {check_result['threats']}")

            return func(*args, **kwargs)

        return wrapper
    return decorator


class SecurityError(Exception):
    """安全错误"""
    pass


# ============ 便捷函数 ============

def sanitize_sql(value: str) -> str:
    """清理SQL输入"""
    return SQLInjectionProtector().sanitize(value)


def sanitize_html(value: str) -> str:
    """清理HTML输入"""
    return XSSProtector().sanitize(value)


def mask_sensitive_data(data: Dict, fields: List[str]) -> Dict:
    """脱敏敏感数据"""
    masker = DataMasker()
    result = data.copy()

    for field in fields:
        if field in result:
            value = str(result[field])
            if '@' in value:
                result[field] = masker.mask_email(value)
            elif len(value) == 11 and value.isdigit():
                result[field] = masker.mask_phone(value)
            else:
                result[field] = masker.mask_api_key(value)

    return result
