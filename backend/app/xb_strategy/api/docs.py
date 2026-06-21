"""西部量化可转债策略 V3.0 API文档配置

功能:
- OpenAPI/Swagger配置
- API端点文档
- 请求/响应模型
- 示例数据
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum
import json


# ============ API信息 ============

API_INFO = {
    "title": "西部量化可转债策略 V3.0 API",
    "description": """
## 概述

西部量化可转债策略系统是一套完整的量化交易解决方案，提供可转债打分、信号生成、组合管理、风险控制等功能。

## 认证方式

API使用JWT Token认证，请在请求头中添加:
```
Authorization: Bearer <your_token>
```

## 限流策略

- 普通用户: 100次/分钟
- VIP用户: 500次/分钟

## 错误码

| 错误码 | 说明 |
|--------|------|
| 400 | 请求参数错误 |
| 401 | 未授权 |
| 403 | 权限不足 |
| 404 | 资源不存在 |
| 429 | 请求过于频繁 |
| 500 | 服务器内部错误 |

## 版本历史

- V3.0.0 (2024-01): 完整重构，新增机器学习打分
- V2.5.0 (2023-06): 新增多数据源支持
- V2.0.0 (2023-01): 新增风控模块
""",
    "version": "3.0.0",
    "contact": {
        "name": "西部量化团队",
        "email": "support@xb-strategy.com",
        "url": "https://xb-strategy.com",
    },
    "license_info": {
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
    "servers": [
        {
            "url": "https://api.xb-strategy.com",
            "description": "生产环境",
        },
        {
            "url": "https://staging-api.xb-strategy.com",
            "description": "测试环境",
        },
        {
            "url": "http://localhost:8000",
            "description": "本地开发",
        },
    ],
    "tags_metadata": [
        {"name": "scoring", "description": "可转债打分"},
        {"name": "signals", "description": "交易信号"},
        {"name": "positions", "description": "持仓管理"},
        {"name": "risk", "description": "风险控制"},
        {"name": "backtest", "description": "回测分析"},
        {"name": "data", "description": "数据查询"},
        {"name": "system", "description": "系统管理"},
    ],
}


# ============ 数据模型 ============

SCHEMAS = {
    # 可转债数据
    "ConvertibleBond": {
        "type": "object",
        "required": ["code", "name", "close"],
        "properties": {
            "code": {"type": "string", "description": "转债代码", "example": "128001"},
            "name": {"type": "string", "description": "转债名称", "example": "光大转债"},
            "stock_code": {"type": "string", "description": "正股代码", "example": "601818"},
            "stock_name": {"type": "string", "description": "正股名称", "example": "光大银行"},
            "close": {"type": "number", "description": "收盘价", "example": 105.50},
            "premium": {"type": "number", "description": "溢价率", "example": 0.05},
            "conversion_value": {"type": "number", "description": "转股价值", "example": 100.50},
            "conversion_ratio": {"type": "number", "description": "转股比例", "example": 10.0},
            "maturity": {"type": "string", "format": "date", "description": "到期日", "example": "2025-12-31"},
            "volume": {"type": "integer", "description": "成交量", "example": 100000},
            "amount": {"type": "number", "description": "成交额", "example": 10550000},
        },
    },
    # 打分结果
    "ScoreResult": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "转债代码"},
            "name": {"type": "string", "description": "转债名称"},
            "total_score": {"type": "number", "description": "总分", "example": 75.5},
            "stock_score": {"type": "number", "description": "正股得分", "example": 42.0},
            "bond_score": {"type": "number", "description": "转债得分", "example": 33.5},
            "rank": {"type": "integer", "description": "排名", "example": 15},
            "factors": {
                "type": "object",
                "description": "因子得分明细",
                "example": {
                    "momentum": 8.5,
                    "value": 7.2,
                    "quality": 9.0,
                    "sentiment": 6.5,
                },
            },
            "timestamp": {"type": "string", "format": "date-time", "description": "时间戳"},
        },
    },
    # 交易信号
    "TradingSignal": {
        "type": "object",
        "required": ["code", "action", "quantity"],
        "properties": {
            "signal_id": {"type": "string", "description": "信号ID"},
            "code": {"type": "string", "description": "转债代码"},
            "action": {"type": "string", "enum": ["buy", "sell", "hold"], "description": "操作"},
            "quantity": {"type": "integer", "description": "数量"},
            "price": {"type": "number", "description": "建议价格"},
            "confidence": {"type": "number", "description": "置信度", "minimum": 0, "maximum": 1},
            "reason": {"type": "string", "description": "信号原因"},
            "factors": {
                "type": "object",
                "description": "触发因子",
                "properties": {
                    "timing": {"type": "number"},
                    "momentum": {"type": "number"},
                    "sentiment": {"type": "number"},
                    "liquidity": {"type": "number"},
                },
            },
            "timestamp": {"type": "string", "format": "date-time"},
        },
    },
    # 持仓信息
    "Position": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "转债代码"},
            "name": {"type": "string", "description": "转债名称"},
            "quantity": {"type": "integer", "description": "持仓数量"},
            "cost_price": {"type": "number", "description": "成本价"},
            "current_price": {"type": "number", "description": "现价"},
            "market_value": {"type": "number", "description": "市值"},
            "profit_loss": {"type": "number", "description": "盈亏"},
            "profit_loss_pct": {"type": "number", "description": "盈亏比例"},
            "weight": {"type": "number", "description": "权重"},
        },
    },
    # 组合信息
    "Portfolio": {
        "type": "object",
        "properties": {
            "portfolio_id": {"type": "string", "description": "组合ID"},
            "name": {"type": "string", "description": "组合名称"},
            "nav": {"type": "number", "description": "净值"},
            "total_value": {"type": "number", "description": "总市值"},
            "cash": {"type": "number", "description": "现金"},
            "positions": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/Position"},
            },
            "metrics": {
                "type": "object",
                "properties": {
                    "return_1d": {"type": "number"},
                    "return_1w": {"type": "number"},
                    "return_1m": {"type": "number"},
                    "return_ytd": {"type": "number"},
                    "max_drawdown": {"type": "number"},
                    "sharpe": {"type": "number"},
                    "volatility": {"type": "number"},
                },
            },
        },
    },
    # 风险指标
    "RiskMetrics": {
        "type": "object",
        "properties": {
            "var_95": {"type": "number", "description": "VaR (95%)"},
            "var_99": {"type": "number", "description": "VaR (99%)"},
            "cvar_95": {"type": "number", "description": "CVaR (95%)"},
            "max_drawdown": {"type": "number", "description": "最大回撤"},
            "beta": {"type": "number", "description": "Beta"},
            "volatility": {"type": "number", "description": "波动率"},
            "sharpe_ratio": {"type": "number", "description": "夏普比率"},
            "sortino_ratio": {"type": "number", "description": "索提诺比率"},
        },
    },
    # 回测结果
    "BacktestResult": {
        "type": "object",
        "properties": {
            "backtest_id": {"type": "string", "description": "回测ID"},
            "start_date": {"type": "string", "format": "date"},
            "end_date": {"type": "string", "format": "date"},
            "initial_capital": {"type": "number"},
            "final_capital": {"type": "number"},
            "total_return": {"type": "number"},
            "annualized_return": {"type": "number"},
            "max_drawdown": {"type": "number"},
            "sharpe_ratio": {"type": "number"},
            "win_rate": {"type": "number"},
            "profit_factor": {"type": "number"},
            "trades": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "format": "date"},
                        "code": {"type": "string"},
                        "action": {"type": "string"},
                        "quantity": {"type": "integer"},
                        "price": {"type": "number"},
                    },
                },
            },
            "nav_curve": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "format": "date"},
                        "nav": {"type": "number"},
                    },
                },
            },
        },
    },
    # 错误响应
    "Error": {
        "type": "object",
        "properties": {
            "error": {"type": "string", "description": "错误类型"},
            "message": {"type": "string", "description": "错误信息"},
            "details": {"type": "object", "description": "详细信息"},
            "timestamp": {"type": "string", "format": "date-time"},
        },
    },
}


# ============ API端点文档 ============

PATHS = {
    # ============ 打分模块 ============
    "/api/v3/scoring/score": {
        "post": {
            "tags": ["scoring"],
            "summary": "批量打分",
            "description": "对转债列表进行七维打分",
            "operationId": "scoreBonds",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["codes"],
                            "properties": {
                                "codes": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "转债代码列表",
                                    "example": ["128001", "128002", "128003"],
                                },
                                "date": {
                                    "type": "string",
                                    "format": "date",
                                    "description": "打分日期，默认当天",
                                },
                            },
                        },
                    }
                },
            },
            "responses": {
                "200": {
                    "description": "打分成功",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "success": {"type": "boolean"},
                                    "data": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/ScoreResult"},
                                    },
                                    "count": {"type": "integer"},
                                },
                            },
                        }
                    },
                },
                "400": {"description": "请求参数错误", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                "401": {"description": "未授权"},
            },
        }
    },
    "/api/v3/scoring/score/{code}": {
        "get": {
            "tags": ["scoring"],
            "summary": "单个转债打分",
            "description": "获取指定转债的打分结果",
            "operationId": "getScore",
            "parameters": [
                {"name": "code", "in": "path", "required": True, "schema": {"type": "string"}, "description": "转债代码"},
                {"name": "date", "in": "query", "schema": {"type": "string", "format": "date"}, "description": "日期"},
            ],
            "responses": {
                "200": {"description": "成功", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ScoreResult"}}}},
                "404": {"description": "未找到"},
            },
        }
    },
    "/api/v3/scoring/whitelist": {
        "get": {
            "tags": ["scoring"],
            "summary": "获取白名单",
            "description": "获取当前白名单列表（Top 60）",
            "operationId": "getWhitelist",
            "parameters": [
                {"name": "date", "in": "query", "schema": {"type": "string", "format": "date"}},
                {"name": "top_n", "in": "query", "schema": {"type": "integer", "default": 60}},
            ],
            "responses": {
                "200": {
                    "description": "成功",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "whitelist": {"type": "array", "items": {"type": "string"}},
                                    "buffer": {"type": "array", "items": {"type": "string"}},
                                    "update_time": {"type": "string", "format": "date-time"},
                                },
                            }
                        }
                    },
                }
            },
        }
    },
    # ============ 信号模块 ============
    "/api/v3/signals/generate": {
        "post": {
            "tags": ["signals"],
            "summary": "生成交易信号",
            "description": "基于当前市场状态生成交易信号",
            "operationId": "generateSignals",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "portfolio_id": {"type": "string", "description": "组合ID"},
                                "mode": {"type": "string", "enum": ["auto", "manual"], "default": "auto"},
                                "constraints": {
                                    "type": "object",
                                    "properties": {
                                        "max_positions": {"type": "integer"},
                                        "min_cash": {"type": "number"},
                                    },
                                },
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": {
                    "description": "成功",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "signals": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/TradingSignal"},
                                    },
                                    "timestamp": {"type": "string", "format": "date-time"},
                                },
                            }
                        }
                    },
                }
            },
        }
    },
    "/api/v3/signals/history": {
        "get": {
            "tags": ["signals"],
            "summary": "信号历史",
            "description": "查询历史交易信号",
            "operationId": "getSignalHistory",
            "parameters": [
                {"name": "start_date", "in": "query", "schema": {"type": "string", "format": "date"}},
                {"name": "end_date", "in": "query", "schema": {"type": "string", "format": "date"}},
                {"name": "code", "in": "query", "schema": {"type": "string"}},
                {"name": "action", "in": "query", "schema": {"type": "string", "enum": ["buy", "sell"]}},
                {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                {"name": "page_size", "in": "query", "schema": {"type": "integer", "default": 50}},
            ],
            "responses": {
                "200": {
                    "description": "成功",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "signals": {"type": "array", "items": {"$ref": "#/components/schemas/TradingSignal"}},
                                    "total": {"type": "integer"},
                                    "page": {"type": "integer"},
                                    "page_size": {"type": "integer"},
                                },
                            }
                        }
                    },
                }
            },
        }
    },
    # ============ 持仓模块 ============
    "/api/v3/positions": {
        "get": {
            "tags": ["positions"],
            "summary": "获取持仓",
            "description": "获取当前组合持仓",
            "operationId": "getPositions",
            "parameters": [
                {"name": "portfolio_id", "in": "query", "schema": {"type": "string"}},
            ],
            "responses": {
                "200": {
                    "description": "成功",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/Position"},
                            }
                        }
                    },
                }
            },
        }
    },
    "/api/v3/portfolio": {
        "get": {
            "tags": ["positions"],
            "summary": "获取组合信息",
            "description": "获取组合完整信息，包括持仓、净值、指标",
            "operationId": "getPortfolio",
            "responses": {
                "200": {
                    "description": "成功",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Portfolio"}}},
                }
            },
        }
    },
    # ============ 风控模块 ============
    "/api/v3/risk/metrics": {
        "get": {
            "tags": ["risk"],
            "summary": "风险指标",
            "description": "获取当前组合风险指标",
            "operationId": "getRiskMetrics",
            "responses": {
                "200": {
                    "description": "成功",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/RiskMetrics"}}},
                }
            },
        }
    },
    "/api/v3/risk/var": {
        "post": {
            "tags": ["risk"],
            "summary": "计算VaR",
            "description": "计算组合VaR",
            "operationId": "calculateVar",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "confidence": {"type": "number", "default": 0.95},
                                "method": {"type": "string", "enum": ["historical", "parametric", "monte_carlo"]},
                                "horizon": {"type": "integer", "default": 1, "description": "持有期(天)"},
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": {
                    "description": "成功",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "var": {"type": "number"},
                                    "confidence": {"type": "number"},
                                    "method": {"type": "string"},
                                },
                            }
                        }
                    },
                }
            },
        }
    },
    "/api/v3/risk/stress-test": {
        "post": {
            "tags": ["risk"],
            "summary": "压力测试",
            "description": "执行压力测试场景",
            "operationId": "runStressTest",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "scenarios": {
                                    "type": "array",
                                    "items": {
                                        "type": "string",
                                        "enum": ["market_crash", "rate_hike", "credit_crisis", "liquidity_crisis"],
                                    },
                                }
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": {
                    "description": "成功",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "results": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "scenario": {"type": "string"},
                                                "impact": {"type": "number"},
                                                "worst_case": {"type": "number"},
                                            },
                                        },
                                    }
                                },
                            }
                        }
                    },
                }
            },
        }
    },
    # ============ 回测模块 ============
    "/api/v3/backtest/run": {
        "post": {
            "tags": ["backtest"],
            "summary": "运行回测",
            "description": "执行策略回测",
            "operationId": "runBacktest",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["start_date", "end_date", "initial_capital"],
                            "properties": {
                                "start_date": {"type": "string", "format": "date"},
                                "end_date": {"type": "string", "format": "date"},
                                "initial_capital": {"type": "number"},
                                "strategy_params": {
                                    "type": "object",
                                    "properties": {
                                        "whitelist_size": {"type": "integer", "default": 60},
                                        "max_position": {"type": "number", "default": 0.05},
                                        "signal_threshold": {"type": "number", "default": 65},
                                    },
                                },
                            },
                        }
                    }
                },
            },
            "responses": {
                "200": {
                    "description": "成功",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/BacktestResult"}}},
                }
            },
        }
    },
    "/api/v3/backtest/{backtest_id}": {
        "get": {
            "tags": ["backtest"],
            "summary": "获取回测结果",
            "description": "获取回测详细结果",
            "operationId": "getBacktestResult",
            "parameters": [
                {"name": "backtest_id", "in": "path", "required": True, "schema": {"type": "string"}},
            ],
            "responses": {
                "200": {
                    "description": "成功",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/BacktestResult"}}},
                },
                "404": {"description": "未找到"},
            },
        }
    },
    # ============ 数据模块 ============
    "/api/v3/data/bonds": {
        "get": {
            "tags": ["data"],
            "summary": "转债列表",
            "description": "获取转债基础数据",
            "operationId": "getBonds",
            "parameters": [
                {"name": "date", "in": "query", "schema": {"type": "string", "format": "date"}},
                {"name": "codes", "in": "query", "schema": {"type": "string"}, "description": "逗号分隔的代码"},
            ],
            "responses": {
                "200": {
                    "description": "成功",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/ConvertibleBond"},
                            }
                        }
                    },
                }
            },
        }
    },
    "/api/v3/data/bonds/{code}/history": {
        "get": {
            "tags": ["data"],
            "summary": "转债历史数据",
            "description": "获取转债历史行情",
            "operationId": "getBondHistory",
            "parameters": [
                {"name": "code", "in": "path", "required": True, "schema": {"type": "string"}},
                {"name": "start_date", "in": "query", "schema": {"type": "string", "format": "date"}},
                {"name": "end_date", "in": "query", "schema": {"type": "string", "format": "date"}},
            ],
            "responses": {
                "200": {
                    "description": "成功",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/ConvertibleBond"},
                            }
                        }
                    },
                }
            },
        }
    },
    # ============ 系统模块 ============
    "/api/v3/system/health": {
        "get": {
            "tags": ["system"],
            "summary": "健康检查",
            "description": "系统健康状态检查",
            "operationId": "healthCheck",
            "responses": {
                "200": {
                    "description": "健康",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "status": {"type": "string", "enum": ["healthy", "degraded", "unhealthy"]},
                                    "components": {
                                        "type": "object",
                                        "properties": {
                                            "database": {"type": "string"},
                                            "cache": {"type": "string"},
                                            "data_source": {"type": "string"},
                                        },
                                    },
                                    "uptime": {"type": "number"},
                                    "version": {"type": "string"},
                                },
                            }
                        }
                    },
                }
            },
        }
    },
    "/api/v3/system/metrics": {
        "get": {
            "tags": ["system"],
            "summary": "系统指标",
            "description": "Prometheus格式的系统指标",
            "operationId": "getMetrics",
            "responses": {
                "200": {"description": "成功", "content": {"text/plain": {"schema": {"type": "string"}}}},
            },
        }
    },
}


# ============ 安全配置 ============

SECURITY_SCHEMES = {
    "bearerAuth": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "JWT Token认证",
    },
    "apiKey": {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "API Key认证",
    },
}


# ============ OpenAPI规范生成 ============

def get_openapi_spec() -> Dict[str, Any]:
    """生成OpenAPI规范"""
    return {
        "openapi": "3.0.3",
        "info": {
            "title": API_INFO["title"],
            "description": API_INFO["description"],
            "version": API_INFO["version"],
            "contact": API_INFO["contact"],
            "license": API_INFO["license_info"],
        },
        "servers": API_INFO["servers"],
        "tags": API_INFO["tags_metadata"],
        "paths": PATHS,
        "components": {
            "schemas": SCHEMAS,
            "securitySchemes": SECURITY_SCHEMES,
        },
        "security": [{"bearerAuth": []}],
    }


def get_swagger_ui_html() -> str:
    """生成Swagger UI HTML"""
    return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>西部量化可转债策略 V3.0 API 文档</title>
    <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5.9.0/swagger-ui.css">
    <style>
        html { box-sizing: border-box; overflow: -moz-scrollbars-vertical; overflow-y: scroll; }
        *, *:before, *:after { box-sizing: inherit; }
        body { margin:0; background: #fafafa; }
        .swagger-ui .topbar { display: none; }
        .swagger-ui .info .title { font-size: 28px; }
        .swagger-ui .opblock-tag { font-size: 18px; }
    </style>
</head>
<body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5.9.0/swagger-ui-bundle.js"></script>
    <script src="https://unpkg.com/swagger-ui-dist@5.9.0/swagger-ui-standalone-preset.js"></script>
    <script>
        window.onload = function() {
            const ui = SwaggerUIBundle({
                url: "/openapi.json",
                dom_id: '#swagger-ui',
                deepLinking: true,
                presets: [
                    SwaggerUIBundle.presets.apis,
                    SwaggerUIStandalonePreset
                ],
                plugins: [
                    SwaggerUIBundle.plugins.DownloadUrl
                ],
                layout: "StandaloneLayout",
                defaultModelsExpandDepth: 1,
                defaultModelExpandDepth: 1,
                docExpansion: "list",
                filter: true,
                showExtensions: true,
                showCommonExtensions: true,
            })
            window.ui = ui
        }
    </script>
</body>
</html>
    """


def get_redoc_html() -> str:
    """生成ReDoc HTML"""
    return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>西部量化可转债策略 V3.0 API 文档</title>
    <style>
        body { margin: 0; padding: 0; }
    </style>
</head>
<body>
    <redoc spec-url='/openapi.json'></redoc>
    <script src="https://unpkg.com/redoc@latest/bundles/redoc.standalone.js"></script>
</body>
</html>
    """


# ============ FastAPI集成 ============

def setup_docs(app):
    """配置FastAPI文档"""
    from fastapi.openapi.utils import get_openapi

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema

        openapi_schema = get_openapi(
            title=API_INFO["title"],
            version=API_INFO["version"],
            description=API_INFO["description"],
            routes=app.routes,
            tags=API_INFO["tags_metadata"],
        )

        # 添加自定义配置
        openapi_schema["servers"] = API_INFO["servers"]
        openapi_schema["components"]["securitySchemes"] = SECURITY_SCHEMES
        openapi_schema["security"] = [{"bearerAuth": []}]

        # 添加自定义schema
        for name, schema in SCHEMAS.items():
            if name not in openapi_schema["components"]["schemas"]:
                openapi_schema["components"]["schemas"][name] = schema

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi


# ============ 导出 ============

__all__ = [
    "API_INFO",
    "SCHEMAS",
    "PATHS",
    "SECURITY_SCHEMES",
    "get_openapi_spec",
    "get_swagger_ui_html",
    "get_redoc_html",
    "setup_docs",
]
