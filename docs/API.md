# API 文档

## 基础配置

**Base URL**: `http://localhost:8000/api/v1`

## 认证

所有 API 请求需要在 Header 中携带认证 Token:

```
Authorization: Bearer <token>
```

## 端点列表

### 债券数据

#### 获取债券列表

```
GET /bonds
```

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| page | int | 否 | 页码，默认 1 |
| size | int | 否 | 每页数量，默认 50 |
| sort | string | 否 | 排序字段 |
| order | string | 否 | 排序方向 asc/desc |

**响应**:
```json
{
  "data": [
    {
      "code": "110001",
      "name": "某转债",
      "price": 100.5,
      "change_percent": 0.5,
      "ytm": 2.5,
      "premium": 15.3,
      "volume": 1000000,
      "amount": 100500000
    }
  ],
  "total": 500,
  "page": 1,
  "size": 50
}
```

#### 获取债券详情

```
GET /bonds/{code}
```

**响应**:
```json
{
  "code": "110001",
  "name": "某转债",
  "price": 100.5,
  "ytm": 2.5,
  "premium": 15.3,
  "conversion_value": 95.2,
  "bond_value": 98.5,
  "rating": "AA+",
  "listing_date": "2020-01-01",
  "maturity_date": "2026-01-01",
  "coupon_rate": 0.5,
  "issue_size": 100000000,
  "remaining_size": 80000000
}
```

#### 获取 K 线数据

```
GET /bonds/{code}/kline
```

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| period | string | 否 | 周期: 1d/1w/1m，默认 1d |
| start | string | 否 | 开始日期 YYYY-MM-DD |
| end | string | 否 | 结束日期 YYYY-MM-DD |

**响应**:
```json
{
  "data": [
    {
      "date": "2024-01-01",
      "open": 100.0,
      "close": 101.5,
      "high": 102.0,
      "low": 99.5,
      "volume": 1000000
    }
  ]
}
```

### 交易信号

#### 获取信号列表

```
GET /signals
```

**响应**:
```json
{
  "data": [
    {
      "id": "sig_001",
      "code": "110001",
      "name": "某转债",
      "type": "buy",
      "price": 100.5,
      "reason": "技术指标金叉",
      "confidence": 0.85,
      "created_at": "2024-01-01T10:00:00Z"
    }
  ]
}
```

#### 订阅信号推送

```
WebSocket /ws/signals
```

**消息格式**:
```json
{
  "type": "signal",
  "data": {
    "id": "sig_001",
    "code": "110001",
    "type": "buy",
    "price": 100.5
  }
}
```

### 策略管理

#### 获取策略列表

```
GET /strategies
```

**响应**:
```json
{
  "data": [
    {
      "id": "strat_001",
      "name": "双均线策略",
      "description": "基于快慢均线交叉",
      "status": "running",
      "returns": 15.5,
      "max_drawdown": -8.3,
      "sharpe_ratio": 1.8,
      "created_at": "2024-01-01T00:00:00Z"
    }
  ]
}
```

#### 创建策略

```
POST /strategies
```

**请求体**:
```json
{
  "name": "我的策略",
  "description": "策略描述",
  "config": {
    "fast_period": 5,
    "slow_period": 20,
    "stop_loss": 0.05,
    "take_profit": 0.1
  }
}
```

#### 运行回测

```
POST /strategies/{id}/backtest
```

**请求体**:
```json
{
  "start_date": "2023-01-01",
  "end_date": "2023-12-31",
  "initial_capital": 1000000
}
```

**响应**:
```json
{
  "total_returns": 25.5,
  "annual_returns": 25.5,
  "max_drawdown": -12.3,
  "sharpe_ratio": 1.5,
  "win_rate": 55.2,
  "total_trades": 120,
  "trades": [
    {
      "date": "2023-01-15",
      "action": "buy",
      "code": "110001",
      "price": 100.5,
      "quantity": 1000
    }
  ]
}
```

### 账户管理

#### 获取账户信息

```
GET /accounts
```

**响应**:
```json
{
  "accounts": [
    {
      "id": "acc_001",
      "name": "主账户",
      "broker": "某券商",
      "balance": 1000000,
      "available": 800000,
      "frozen": 200000,
      "market_value": 500000
    }
  ]
}
```

### 预警管理

#### 创建预警

```
POST /alerts
```

**请求体**:
```json
{
  "code": "110001",
  "type": "price",
  "condition": "gte",
  "value": 105,
  "notify": ["email", "desktop"]
}
```

### 数据同步

#### 导出数据

```
GET /export
```

**参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| type | string | 是 | 数据类型: watchlist/strategies/settings |
| format | string | 否 | 格式: json/csv，默认 json |

#### 导入数据

```
POST /import
```

**请求体**: FormData with file

## 错误响应

所有错误响应格式:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "参数验证失败",
    "details": [
      {
        "field": "price",
        "message": "价格必须为正数"
      }
    ]
  }
}
```

## 速率限制

- 默认限制: 100 请求/分钟
- WebSocket 连接: 5 个/用户

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0.0 | 2024-01-01 | 初始版本 |
