"""Tests for rate limiting middleware"""
import pytest
import time
from unittest.mock import MagicMock, AsyncMock
from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.rate_limit import (
    RateLimitConfig, TokenBucket, RateLimiter,
    get_rate_limiter, rate_limit_middleware,
)


class TestTokenBucket:
    """令牌桶算法测试"""

    def test_initial_state(self):
        """测试初始状态"""
        bucket = TokenBucket(rate=10.0, capacity=20)
        assert bucket.consume('client1') is True

    def test_consume_tokens(self):
        """测试消费令牌"""
        bucket = TokenBucket(rate=1.0, capacity=5)

        # 初始有5个令牌
        for _ in range(5):
            assert bucket.consume('client1') is True

        # 消耗完后应该失败
        assert bucket.consume('client1') is False

    def test_token_refill(self):
        """测试令牌补充"""
        bucket = TokenBucket(rate=10.0, capacity=5)  # 每秒10个令牌

        # 消耗所有令牌
        for _ in range(5):
            bucket.consume('client1')

        assert bucket.consume('client1') is False

        # 等待0.2秒应补充约2个令牌
        time.sleep(0.25)
        assert bucket.consume('client1') is True

    def test_multiple_clients(self):
        """测试多客户端隔离"""
        bucket = TokenBucket(rate=1.0, capacity=3)

        # client1消耗3个
        for _ in range(3):
            bucket.consume('client1')

        # client2应该独立
        assert bucket.consume('client2') is True

    def test_burst_capacity(self):
        """测试突发容量"""
        bucket = TokenBucket(rate=1.0, capacity=10)

        # 可以突发10个请求
        count = 0
        for _ in range(15):
            if bucket.consume('client1'):
                count += 1

        assert count == 10

    def test_wait_time(self):
        """测试等待时间计算"""
        bucket = TokenBucket(rate=10.0, capacity=5)

        # 消耗所有令牌
        for _ in range(5):
            bucket.consume('client1')

        # 等待时间应大于0
        wait_time = bucket.get_wait_time('client1')
        assert wait_time > 0

        # 未使用的客户端等待时间应为0
        assert bucket.get_wait_time('unknown') == 0


class TestRateLimiter:
    """限流器测试"""

    def test_check_allowed(self):
        """测试允许请求"""
        limiter = RateLimiter(RateLimitConfig(
            requests_per_second=10.0,
            burst_size=20,
            enabled=True,
        ))

        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = '127.0.0.1'
        request.headers = MagicMock()
        request.headers.get = MagicMock(return_value=None)
        request.url = MagicMock()
        request.url.path = '/api/test'
        request.state = MagicMock()
        request.state.user = None

        assert limiter.check(request) is True

    def test_check_rate_limited(self):
        """测试请求被限流"""
        limiter = RateLimiter(RateLimitConfig(
            requests_per_second=1.0,
            burst_size=3,
            enabled=True,
        ))

        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = '127.0.0.1'
        request.headers = MagicMock()
        request.headers.get = MagicMock(return_value=None)
        request.url = MagicMock()
        request.url.path = '/api/test'
        request.state = MagicMock()
        request.state.user = None

        # 突发3个请求
        for _ in range(3):
            limiter.check(request)

        # 第4个应该被限流
        assert limiter.check(request) is False

    def test_whitelist(self):
        """测试白名单"""
        limiter = RateLimiter(RateLimitConfig(
            requests_per_second=1.0,
            burst_size=1,
            enabled=True,
        ))
        limiter.add_to_whitelist('ip:127.0.0.1')

        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = '127.0.0.1'
        request.headers = MagicMock()
        request.headers.get = MagicMock(return_value=None)
        request.url = MagicMock()
        request.url.path = '/api/test'
        request.state = MagicMock()
        request.state.user = None  # 确保没有用户信息

        # 白名单用户不受限流
        for _ in range(10):
            assert limiter.check(request) is True

    def test_disabled(self):
        """测试禁用限流"""
        limiter = RateLimiter(RateLimitConfig(enabled=False))

        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = '127.0.0.1'
        request.headers = MagicMock()
        request.headers.get = MagicMock(return_value=None)
        request.url = MagicMock()
        request.url.path = '/api/test'
        request.state = MagicMock()
        request.state.user = None

        # 禁用后应允许所有请求
        for _ in range(100):
            assert limiter.check(request) is True

    def test_x_forwarded_for(self):
        """测试X-Forwarded-For头解析"""
        limiter = RateLimiter(RateLimitConfig(
            requests_per_second=1.0,
            burst_size=2,
            enabled=True,
        ))

        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = '10.0.0.1'
        request.headers = MagicMock()
        request.headers.get = MagicMock(return_value='192.168.1.1, 10.0.0.1')
        request.url = MagicMock()
        request.url.path = '/api/test'
        request.state = MagicMock()
        request.state.user = None

        # 应使用X-Forwarded-For中的第一个IP
        for _ in range(2):
            limiter.check(request)

        assert limiter.check(request) is False


class TestRateLimitMiddleware:
    """限流中间件测试"""

    @pytest.mark.asyncio
    async def test_middleware_pass(self):
        """测试中间件放行请求"""
        limiter = get_rate_limiter()

        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = '127.0.0.1'
        request.headers = MagicMock()
        request.headers.get = MagicMock(return_value=None)
        request.url = MagicMock()
        request.url.path = '/api/test'
        request.state = MagicMock()
        request.state.user = None

        async def call_next(req):
            return MagicMock(status_code=200)

        response = await rate_limit_middleware(request, call_next)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_middleware_rate_limited(self):
        """测试中间件限流响应"""
        from app.core.rate_limit import RateLimitConfig, RateLimiter, get_rate_limiter

        # 创建新的限流器（低阈值便于测试）
        limiter = RateLimiter(RateLimitConfig(
            requests_per_second=1.0,
            burst_size=2,
            enabled=True,
        ))

        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = '127.0.0.2'
        request.headers = MagicMock()
        request.headers.get = MagicMock(return_value=None)
        request.url = MagicMock()
        request.url.path = '/api/test'
        request.state = MagicMock()
        request.state.user = None

        async def call_next(req):
            return MagicMock(status_code=200)

        # 消耗配额
        limiter.check(request)
        limiter.check(request)

        # 替换全局限流器
        import app.core.rate_limit as rate_limit_module
        original_limiter = rate_limit_module._rate_limiter
        rate_limit_module._rate_limiter = limiter

        try:
            # 应返回429
            response = await rate_limit_middleware(request, call_next)
            assert response.status_code == 429
        finally:
            rate_limit_module._rate_limiter = original_limiter

    @pytest.mark.asyncio
    async def test_health_check_bypass(self):
        """测试健康检查端点跳过限流"""
        request = MagicMock(spec=Request)
        request.url = MagicMock()
        request.url.path = '/api/v1/health'

        async def call_next(req):
            return MagicMock(status_code=200)

        response = await rate_limit_middleware(request, call_next)
        assert response.status_code == 200


class TestRateLimitConfig:
    """限流配置测试"""

    def test_default_config(self):
        """测试默认配置"""
        config = RateLimitConfig()
        assert config.requests_per_second == 10.0
        assert config.requests_per_minute == 100
        assert config.burst_size == 20
        assert config.enabled is True

    def test_custom_config(self):
        """测试自定义配置"""
        config = RateLimitConfig(
            requests_per_second=5.0,
            requests_per_minute=50,
            burst_size=10,
            enabled=False,
        )
        assert config.requests_per_second == 5.0
        assert config.requests_per_minute == 50
        assert config.burst_size == 10
        assert config.enabled is False
