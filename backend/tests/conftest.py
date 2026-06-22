"""
共享测试夹具 - 提供认证 token 和测试用 HTTP 客户端
"""
import builtins
import _pytest.assertion.rewrite as _ar
import warnings
import pytest
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

# 在 jieba 导入前静默其 SyntaxWarning（jieba/posseg/__init__.py 中的无效转义序列）
warnings.filterwarnings("ignore", category=SyntaxWarning, module="jieba")
warnings.filterwarnings("ignore", category=SyntaxWarning, module="jieba.posseg")
# passlib 内部使用已弃用的 crypt 模块（Python 3.13 将移除），静默该警告
warnings.filterwarnings("ignore", category=DeprecationWarning, module="passlib")


def pytest_configure(config):
    """注册自定义 pytest 标记，避免使用未注册标记时的 warning。"""
    config.addinivalue_line(
        "markers",
        "serial: 标记该测试必须串行执行（不可与其他测试并行）。"
        "适用于存在 fixture 共享状态竞争的测试。",
    )

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


_DE_TOUCHED = False


@pytest.fixture(autouse=True)
def _reset_module_state(request):
    """测试结束后重置模块级全局状态，防止测试间状态污染。

    历史问题：data_enrich.py 和 enhanced_timing_model.py 等模块使用模块级
    dict/set 作为内存缓存。如果上一个测试写入了数据，下一个测试看到的就是
    污染后的状态，导致"独立运行通过、批量运行失败"的 flaky tests。

    实现：只对使用了 data_enrich 模块的测试生效（按需 lazy import），
    避免对所有测试增加 import 开销（~30s）。
    """
    global _DE_TOUCHED
    yield  # 测试运行
    if _DE_TOUCHED:
        try:
            from app.engine import data_enrich as de
            if hasattr(de, 'reset_module_state_for_testing'):
                de.reset_module_state_for_testing()
        except ImportError:
            pass
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _track_de_touch(request):
    """跟踪是否触达了 data_enrich 模块。如果测试代码 import 了它，
    标记 _DE_TOUCHED=True 让下一个测试结束时执行 reset。
    """
    global _DE_TOUCHED
    # 在测试开始前检查 sys.modules，判断测试是否使用 data_enrich
    import sys
    touched_before = 'app.engine.data_enrich' in sys.modules
    yield
    if not touched_before and 'app.engine.data_enrich' in sys.modules:
        # 测试期间触达了 data_enrich
        _DE_TOUCHED = True
