"""西部量化可转债策略 V3.0 Python SDK

功能:
- API客户端封装
- 签名认证
- 自动重试
- 异步支持
- 类型提示
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, Union
from enum import Enum
import hashlib
import hmac
import time
import json
import logging
import threading
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

# 检查依赖
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False


# ============ 配置类 ============

@dataclass
class ClientConfig:
    """客户端配置"""
    api_key: str
    api_secret: str
    base_url: str = "https://api.xb-strategy.com"
    timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0
    verify_ssl: bool = True


@dataclass
class APIResponse:
    """API响应"""
    success: bool
    status_code: int
    data: Any
    message: str = ""
    request_id: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "status_code": self.status_code,
            "data": self.data,
            "message": self.message,
            "request_id": self.request_id,
        }


# ============ 签名认证 ============

class SignatureAuth:
    """签名认证"""

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret

    def sign(self, method: str, path: str, params: Dict = None, body: str = "") -> Dict[str, str]:
        """生成签名"""
        timestamp = str(int(time.time()))
        nonce = hashlib.md5(f"{timestamp}{self.api_key}".encode()).hexdigest()[:16]

        # 构建签名字符串
        query_string = urlencode(sorted(params.items())) if params else ""
        sign_str = f"{method.upper()}\n{path}\n{query_string}\n{body}\n{timestamp}"

        # HMAC-SHA256签名
        signature = hmac.new(
            self.api_secret.encode(),
            sign_str.encode(),
            hashlib.sha256,
        ).hexdigest()

        return {
            "X-API-Key": self.api_key,
            "X-Timestamp": timestamp,
            "X-Nonce": nonce,
            "X-Signature": signature,
        }


# ============ 同步客户端 ============

class SGStrategyClient:
    """西部策略客户端（同步）"""

    def __init__(self, config: ClientConfig):
        if not REQUESTS_AVAILABLE:
            raise ImportError("requests库未安装，请执行: pip install requests")

        self.config = config
        self.auth = SignatureAuth(config.api_key, config.api_secret)
        self._session = None
        self._lock = threading.Lock()

    def _get_session(self):
        """获取会话"""
        if self._session is None:
            self._session = requests.Session()
            self._session.verify = self.config.verify_ssl
        return self._session

    def _request(
        self,
        method: str,
        path: str,
        params: Dict = None,
        data: Dict = None,
        json_data: Dict = None,
    ) -> APIResponse:
        """发送请求"""
        url = f"{self.config.base_url}{path}"
        body = json.dumps(json_data) if json_data else ""

        # 重试机制
        for attempt in range(self.config.max_retries):
            try:
                # 生成签名头
                headers = self.auth.sign(method, path, params, body)
                headers["Content-Type"] = "application/json"

                session = self._get_session()

                response = session.request(
                    method=method,
                    url=url,
                    params=params,
                    data=data,
                    json=json_data,
                    headers=headers,
                    timeout=self.config.timeout,
                )

                # 解析响应
                try:
                    result = response.json()
                except:
                    result = {"message": response.text}

                return APIResponse(
                    success=response.status_code == 200,
                    status_code=response.status_code,
                    data=result.get("data", result),
                    message=result.get("message", ""),
                    request_id=response.headers.get("X-Request-ID", ""),
                )

            except requests.exceptions.RequestException as e:
                logger.warning(f"请求失败 (尝试 {attempt + 1}/{self.config.max_retries}): {e}")
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    return APIResponse(
                        success=False,
                        status_code=0,
                        data=None,
                        message=str(e),
                    )

    # ============ 打分接口 ============

    def score_bond(self, code: str, date: str = None) -> APIResponse:
        """单个转债打分"""
        params = {"date": date} if date else None
        return self._request("GET", f"/api/v3/scoring/score/{code}", params=params)

    def score_bonds(self, codes: List[str], date: str = None) -> APIResponse:
        """批量打分"""
        json_data = {"codes": codes}
        if date:
            json_data["date"] = date
        return self._request("POST", "/api/v3/scoring/score", json_data=json_data)

    def get_whitelist(self, date: str = None, top_n: int = 60) -> APIResponse:
        """获取白名单"""
        params = {"top_n": top_n}
        if date:
            params["date"] = date
        return self._request("GET", "/api/v3/scoring/whitelist", params=params)

    # ============ 信号接口 ============

    def generate_signals(
        self,
        portfolio_id: str = None,
        mode: str = "auto",
        constraints: Dict = None,
    ) -> APIResponse:
        """生成交易信号"""
        json_data = {
            "portfolio_id": portfolio_id,
            "mode": mode,
        }
        if constraints:
            json_data["constraints"] = constraints
        return self._request("POST", "/api/v3/signals/generate", json_data=json_data)

    def get_signal_history(
        self,
        start_date: str = None,
        end_date: str = None,
        code: str = None,
        action: str = None,
        page: int = 1,
        page_size: int = 50,
    ) -> APIResponse:
        """获取信号历史"""
        params = {"page": page, "page_size": page_size}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if code:
            params["code"] = code
        if action:
            params["action"] = action
        return self._request("GET", "/api/v3/signals/history", params=params)

    # ============ 持仓接口 ============

    def get_positions(self, portfolio_id: str = None) -> APIResponse:
        """获取持仓"""
        params = {"portfolio_id": portfolio_id} if portfolio_id else None
        return self._request("GET", "/api/v3/positions", params=params)

    def get_portfolio(self) -> APIResponse:
        """获取组合信息"""
        return self._request("GET", "/api/v3/portfolio")

    # ============ 风控接口 ============

    def get_risk_metrics(self) -> APIResponse:
        """获取风险指标"""
        return self._request("GET", "/api/v3/risk/metrics")

    def calculate_var(
        self,
        confidence: float = 0.95,
        method: str = "historical",
        horizon: int = 1,
    ) -> APIResponse:
        """计算VaR"""
        json_data = {
            "confidence": confidence,
            "method": method,
            "horizon": horizon,
        }
        return self._request("POST", "/api/v3/risk/var", json_data=json_data)

    def run_stress_test(self, scenarios: List[str] = None) -> APIResponse:
        """压力测试"""
        json_data = {"scenarios": scenarios or ["market_crash", "rate_hike"]}
        return self._request("POST", "/api/v3/risk/stress-test", json_data=json_data)

    # ============ 回测接口 ============

    def run_backtest(
        self,
        start_date: str,
        end_date: str,
        initial_capital: float,
        strategy_params: Dict = None,
    ) -> APIResponse:
        """运行回测"""
        json_data = {
            "start_date": start_date,
            "end_date": end_date,
            "initial_capital": initial_capital,
        }
        if strategy_params:
            json_data["strategy_params"] = strategy_params
        return self._request("POST", "/api/v3/backtest/run", json_data=json_data)

    def get_backtest_result(self, backtest_id: str) -> APIResponse:
        """获取回测结果"""
        return self._request("GET", f"/api/v3/backtest/{backtest_id}")

    # ============ 数据接口 ============

    def get_bonds(self, date: str = None, codes: List[str] = None) -> APIResponse:
        """获取转债列表"""
        params = {}
        if date:
            params["date"] = date
        if codes:
            params["codes"] = ",".join(codes)
        return self._request("GET", "/api/v3/data/bonds", params=params)

    def get_bond_history(
        self,
        code: str,
        start_date: str = None,
        end_date: str = None,
    ) -> APIResponse:
        """获取转债历史"""
        params = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self._request("GET", f"/api/v3/data/bonds/{code}/history", params=params)

    # ============ 系统接口 ============

    def health_check(self) -> APIResponse:
        """健康检查"""
        return self._request("GET", "/api/v3/system/health")

    def close(self):
        """关闭连接"""
        if self._session:
            self._session.close()
            self._session = None


# ============ 异步客户端 ============

class AsyncSGStrategyClient:
    """西部策略客户端（异步）"""

    def __init__(self, config: ClientConfig):
        if not AIOHTTP_AVAILABLE:
            raise ImportError("aiohttp库未安装，请执行: pip install aiohttp")

        self.config = config
        self.auth = SignatureAuth(config.api_key, config.api_secret)
        self._session = None

    async def _get_session(self):
        """获取会话"""
        if self._session is None:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.config.timeout),
            )
        return self._session

    async def _request(
        self,
        method: str,
        path: str,
        params: Dict = None,
        json_data: Dict = None,
    ) -> APIResponse:
        """发送异步请求"""
        url = f"{self.config.base_url}{path}"
        body = json.dumps(json_data) if json_data else ""

        # 重试机制
        for attempt in range(self.config.max_retries):
            try:
                headers = self.auth.sign(method, path, params, body)
                headers["Content-Type"] = "application/json"

                session = await self._get_session()

                async with session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_data,
                    headers=headers,
                    ssl=self.config.verify_ssl,
                ) as response:
                    try:
                        result = await response.json()
                    except:
                        result = {"message": await response.text()}

                    return APIResponse(
                        success=response.status == 200,
                        status_code=response.status,
                        data=result.get("data", result),
                        message=result.get("message", ""),
                        request_id=response.headers.get("X-Request-ID", ""),
                    )

            except Exception as e:
                logger.warning(f"异步请求失败 (尝试 {attempt + 1}): {e}")
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    return APIResponse(
                        success=False,
                        status_code=0,
                        data=None,
                        message=str(e),
                    )

    async def score_bond(self, code: str, date: str = None) -> APIResponse:
        """异步打分"""
        params = {"date": date} if date else None
        return await self._request("GET", f"/api/v3/scoring/score/{code}", params=params)

    async def get_whitelist(self, date: str = None, top_n: int = 60) -> APIResponse:
        """异步获取白名单"""
        params = {"top_n": top_n}
        if date:
            params["date"] = date
        return await self._request("GET", "/api/v3/scoring/whitelist", params=params)

    async def close(self):
        """关闭连接"""
        if self._session:
            await self._session.close()
            self._session = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# ============ 便捷函数 ============

def create_client(api_key: str, api_secret: str, base_url: str = None) -> SGStrategyClient:
    """创建客户端"""
    config = ClientConfig(
        api_key=api_key,
        api_secret=api_secret,
        base_url=base_url or "https://api.xb-strategy.com",
    )
    return SGStrategyClient(config)


def create_async_client(api_key: str, api_secret: str, base_url: str = None) -> AsyncSGStrategyClient:
    """创建异步客户端"""
    config = ClientConfig(
        api_key=api_key,
        api_secret=api_secret,
        base_url=base_url or "https://api.xb-strategy.com",
    )
    return AsyncSGStrategyClient(config)


# ============ 使用示例 ============

"""
# 同步使用示例
from xb_strategy_client import create_client

client = create_client("your_api_key", "your_api_secret")

# 打分
result = client.score_bond("128001")
print(result.data)

# 批量打分
result = client.score_bonds(["128001", "128002", "128003"])
print(result.data)

# 获取白名单
result = client.get_whitelist()
print(result.data)

# 关闭连接
client.close()

# 异步使用示例
import asyncio
from xb_strategy_client import create_async_client

async def main():
    async with create_async_client("your_api_key", "your_api_secret") as client:
        result = await client.get_whitelist()
        print(result.data)

asyncio.run(main())
"""
