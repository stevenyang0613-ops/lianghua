"""
共享测试夹具 - 提供认证 token 和测试用 HTTP 客户端
"""
import builtins
import _pytest.assertion.rewrite as _ar
import pytest
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

import bcrypt

if not hasattr(bcrypt, "__about__"):
    bcrypt.__about__ = type("about", (), {"__version__": getattr(bcrypt, "__version__", "4.x")})


@pytest.fixture(scope="session")
def test_token() -> str:
    """生成一个有效的 JWT 测试 token"""
    from app.config import settings
    from jose import jwt
    return jwt.encode(
        {"sub": "testuser", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


@pytest.fixture
def auth_headers(test_token: str) -> dict:
    """返回带 Bearer token 的 HTTP 请求头"""
    return {"Authorization": f"Bearer {test_token}"}


@pytest.fixture
def auto_auth_headers(request, auth_headers: dict) -> dict:
    """为非异步测试使用的认证头"""
    return auth_headers
