"""松岗量化可转债策略 V3.0 gRPC服务模块

功能:
- gRPC服务定义
- 服务发现
- 负载均衡
- 拦截器
- 健康检查
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any, Callable
from enum import Enum
import logging
import asyncio
import json

logger = logging.getLogger(__name__)

# 检查gRPC是否可用
try:
    import grpc
    from grpc import aio
    from grpc_interceptor import ServerInterceptor
    GRPC_AVAILABLE = True
except ImportError:
    GRPC_AVAILABLE = False
    grpc = None
    aio = None


# ============ 枚举类型 ============

class ServiceStatus(str, Enum):
    """服务状态"""
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


# ============ 配置类 ============

@dataclass
class GRPCConfig:
    """gRPC配置"""
    # 服务配置
    host: str = "0.0.0.0"
    port: int = 50051
    max_workers: int = 10

    # 连接配置
    max_receive_message_length: int = 4 * 1024 * 1024  # 4MB
    max_send_message_length: int = 4 * 1024 * 1024  # 4MB

    # 超时配置
    request_timeout: int = 30  # 秒

    # 服务发现
    enable_discovery: bool = False
    discovery_type: str = "static"  # static, consul, etcd
    discovery_endpoints: List[str] = field(default_factory=lambda: ["localhost:8500"])

    # 负载均衡
    load_balance_policy: str = "round_robin"  # round_robin, least_connection


# ============ Proto定义 (内嵌) ============

# 由于实际proto需要编译，这里提供接口定义
# 实际使用时需要:
# 1. 创建 sg_strategy.proto 文件
# 2. 运行 python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. sg_strategy.proto

SG_STRATEGY_PROTO = """
syntax = "proto3";

package sg_strategy;

// 打分服务
service ScoringService {
    rpc ScoreBond(ScoreRequest) returns (ScoreResponse);
    rpc ScoreBatch(BatchScoreRequest) returns (BatchScoreResponse);
}

// 信号服务
service SignalService {
    rpc GetSignals(SignalRequest) returns (SignalResponse);
    rpc SubscribeSignals(SubscribeRequest) returns (stream SignalUpdate);
}

// 交易服务
service TradingService {
    rpc GetPositions(PositionRequest) returns (PositionResponse);
    rpc PlaceOrder(OrderRequest) returns (OrderResponse);
    rpc CancelOrder(CancelRequest) returns (CancelResponse);
}

// 风控服务
service RiskService {
    rpc CheckRisk(RiskCheckRequest) returns (RiskCheckResponse);
    rpc GetRiskMetrics(MetricsRequest) returns (MetricsResponse);
}

// 数据服务
service DataService {
    rpc GetBondData(DataRequest) returns (BondDataResponse);
    rpc SyncData(SyncRequest) returns (SyncResponse);
}

// 健康检查
service Health {
    rpc Check(HealthCheckRequest) returns (HealthCheckResponse);
}

// 消息定义
message ScoreRequest {
    string code = 1;
    string date = 2;
}

message ScoreResponse {
    string code = 1;
    double total_score = 2;
    double stock_score = 3;
    double cb_score = 4;
    map<string, double> factors = 5;
}

message BatchScoreRequest {
    repeated string codes = 1;
    string date = 2;
}

message BatchScoreResponse {
    repeated ScoreResponse scores = 1;
}

message SignalRequest {
    string date = 1;
    repeated string whitelist = 2;
}

message SignalResponse {
    repeated Signal signals = 1;
}

message Signal {
    string code = 1;
    string action = 2;
    int32 quantity = 3;
    double price = 4;
    string reason = 5;
}

message SubscribeRequest {
    repeated string channels = 1;
}

message SignalUpdate {
    string type = 1;
    Signal signal = 2;
    int64 timestamp = 3;
}

message PositionRequest {
    string portfolio_id = 1;
}

message PositionResponse {
    repeated Position positions = 1;
}

message Position {
    string code = 1;
    string name = 2;
    int32 quantity = 3;
    double cost_price = 4;
    double market_price = 5;
    double market_value = 6;
}

message OrderRequest {
    string code = 1;
    string side = 2;
    int32 quantity = 3;
    double price = 4;
    string order_type = 5;
}

message OrderResponse {
    string order_id = 1;
    string status = 2;
    string message = 3;
}

message CancelRequest {
    string order_id = 1;
}

message CancelResponse {
    bool success = 1;
    string message = 2;
}

message RiskCheckRequest {
    string portfolio_id = 1;
}

message RiskCheckResponse {
    string status = 1;
    repeated RiskAlert alerts = 2;
}

message RiskAlert {
    string type = 1;
    string level = 2;
    string message = 3;
    double value = 4;
    double threshold = 5;
}

message MetricsRequest {
    string portfolio_id = 1;
}

message MetricsResponse {
    double var_95 = 1;
    double var_99 = 2;
    double max_drawdown = 3;
    double current_drawdown = 4;
    double sharpe_ratio = 5;
}

message DataRequest {
    string code = 1;
    string start_date = 2;
    string end_date = 3;
}

message BondDataResponse {
    string code = 1;
    repeated DailyData data = 2;
}

message DailyData {
    string date = 1;
    double open = 2;
    double high = 3;
    double low = 4;
    double close = 5;
    int64 volume = 6;
    double amount = 7;
}

message SyncRequest {
    string data_type = 1;
    string start_date = 2;
    string end_date = 3;
}

message SyncResponse {
    bool success = 1;
    int32 records_synced = 2;
    string message = 3;
}

message HealthCheckRequest {
    string service = 1;
}

message HealthCheckResponse {
    string status = 1;
}
"""


# ============ 服务基类 ============

class GRPCServiceBase:
    """gRPC服务基类"""

    def __init__(self, config: GRPCConfig = None):
        self.config = config or GRPCConfig()
        self._server = None
        self._servicers: List[Any] = []

    def add_servicer(self, servicer: Any, adder: Callable):
        """添加服务"""
        self._servicers.append((servicer, adder))

    async def start(self):
        """启动服务"""
        if not GRPC_AVAILABLE:
            logger.warning("[GRPC] grpc库未安装")
            return

        self._server = aio.server(
            options=[
                ("grpc.max_receive_message_length", self.config.max_receive_message_length),
                ("grpc.max_send_message_length", self.config.max_send_message_length),
            ]
        )

        # 添加服务
        for servicer, adder in self._servicers:
            adder(servicer, self._server)

        # 绑定端口
        self._server.add_insecure_port(f"{self.config.host}:{self.config.port}")

        await self._server.start()
        logger.info(f"[GRPC] 服务启动: {self.config.host}:{self.config.port}")

    async def stop(self, grace: int = 5):
        """停止服务"""
        if self._server:
            await self._server.stop(grace)
            logger.info("[GRPC] 服务停止")

    async def wait_for_termination(self):
        """等待终止"""
        if self._server:
            await self._server.wait_for_termination()


# ============ 客户端基类 ============

class GRPCClientBase:
    """gRPC客户端基类"""

    def __init__(self, config: GRPCConfig = None):
        self.config = config or GRPCConfig()
        self._channel = None
        self._stubs: Dict[str, Any] = {}

    async def connect(self, endpoint: str = None):
        """连接服务"""
        if not GRPC_AVAILABLE:
            logger.warning("[GRPC] grpc库未安装")
            return

        target = endpoint or f"{self.config.host}:{self.config.port}"

        self._channel = aio.insecure_channel(
            target,
            options=[
                ("grpc.max_receive_message_length", self.config.max_receive_message_length),
                ("grpc.max_send_message_length", self.config.max_send_message_length),
            ]
        )

        logger.info(f"[GRPC] 连接服务: {target}")

    async def close(self):
        """关闭连接"""
        if self._channel:
            await self._channel.close()

    def create_stub(self, name: str, stub_class: Any):
        """创建存根"""
        if self._channel:
            self._stubs[name] = stub_class(self._channel)

    def get_stub(self, name: str) -> Any:
        """获取存根"""
        return self._stubs.get(name)


# ============ 服务实现示例 ============

if GRPC_AVAILABLE:
    class ScoringServiceServicer:
        """打分服务实现"""

        async def ScoreBond(self, request, context):
            """计算单个债券得分"""
            from datetime import date

            # 模拟得分计算
            code = request.code

            return type('ScoreResponse', (), {
                'code': code,
                'total_score': 75.5,
                'stock_score': 42.0,
                'cb_score': 33.5,
                'factors': {
                    'momentum': 15.0,
                    'value': 20.0,
                    'quality': 25.0,
                }
            })()

        async def ScoreBatch(self, request, context):
            """批量计算得分"""
            scores = []
            for code in request.codes:
                scores.append(type('ScoreResponse', (), {
                    'code': code,
                    'total_score': 70.0 + hash(code) % 20,
                    'stock_score': 40.0,
                    'cb_score': 30.0,
                    'factors': {}
                })())

            return type('BatchScoreResponse', (), {'scores': scores})()

    class HealthServicer:
        """健康检查服务实现"""

        async def Check(self, request, context):
            """健康检查"""
            return type('HealthCheckResponse', (), {
                'status': 'healthy'
            })()

else:
    class ScoringServiceServicer:
        pass

    class HealthServicer:
        pass


# ============ 拦截器 ============

class LoggingInterceptor:
    """日志拦截器"""

    async def intercept_service(self, continuation, handler_call_details):
        """拦截服务调用"""
        method = handler_call_details.method
        logger.debug(f"[GRPC] 调用方法: {method}")

        start_time = datetime.now()

        try:
            response = await continuation(handler_call_details)

            duration = (datetime.now() - start_time).total_seconds()
            logger.debug(f"[GRPC] 方法完成: {method}, 耗时: {duration:.3f}s")

            return response

        except Exception as e:
            logger.error(f"[GRPC] 方法异常: {method}, 错误: {e}")
            raise


class AuthInterceptor:
    """认证拦截器"""

    def __init__(self, valid_tokens: List[str] = None):
        self.valid_tokens = valid_tokens or []

    async def intercept_service(self, continuation, handler_call_details):
        """拦截服务调用"""
        if not self.valid_tokens:
            return await continuation(handler_call_details)

        # 检查认证token
        metadata = dict(handler_call_details.invocation_metadata)
        token = metadata.get("authorization", "")

        if token not in self.valid_tokens:
            if GRPC_AVAILABLE:
                raise grpc.RpcError(grpc.StatusCode.UNAUTHENTICATED, "无效的认证令牌")

        return await continuation(handler_call_details)


# ============ 服务发现 ============

class ServiceDiscovery:
    """服务发现"""

    def __init__(self, config: GRPCConfig):
        self.config = config
        self._services: Dict[str, List[str]] = {}

    def register(self, service_name: str, endpoint: str):
        """注册服务"""
        if service_name not in self._services:
            self._services[service_name] = []

        if endpoint not in self._services[service_name]:
            self._services[service_name].append(endpoint)
            logger.info(f"[Discovery] 注册服务: {service_name} -> {endpoint}")

    def deregister(self, service_name: str, endpoint: str):
        """注销服务"""
        if service_name in self._services:
            if endpoint in self._services[service_name]:
                self._services[service_name].remove(endpoint)

    def discover(self, service_name: str) -> List[str]:
        """发现服务"""
        return self._services.get(service_name, [])

    def get_one(self, service_name: str) -> Optional[str]:
        """获取一个服务实例(简单轮询)"""
        endpoints = self.discover(service_name)
        if not endpoints:
            return None

        # 简单轮询
        if not hasattr(self, '_round_robin_index'):
            self._round_robin_index = {}

        index = self._round_robin_index.get(service_name, 0)
        endpoint = endpoints[index % len(endpoints)]
        self._round_robin_index[service_name] = index + 1

        return endpoint


# ============ 便捷函数 ============

def get_grpc_config() -> GRPCConfig:
    """获取gRPC配置"""
    return GRPCConfig()


async def create_grpc_server(config: GRPCConfig = None) -> GRPCServiceBase:
    """创建gRPC服务器"""
    config = config or GRPCConfig()
    server = GRPCServiceBase(config)

    # 添加服务
    server.add_servicer(ScoringServiceServicer(), lambda s, server: None)
    server.add_servicer(HealthServicer(), lambda s, server: None)

    return server


async def create_grpc_client(endpoint: str, config: GRPCConfig = None) -> GRPCClientBase:
    """创建gRPC客户端"""
    config = config or GRPCConfig()
    client = GRPCClientBase(config)
    await client.connect(endpoint)
    return client
