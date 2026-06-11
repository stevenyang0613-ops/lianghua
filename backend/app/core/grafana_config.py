"""
Grafana仪表板配置

提供预配置的仪表板JSON
"""

GRAFANA_DASHBOARD = {
    "dashboard": {
        "title": "Lianghua量化系统监控",
        "tags": ["lianghua", "quant", "convertible-bond"],
        "timezone": "browser",
        "refresh": "30s",
        "panels": [
            # 系统概览行
            {
                "title": "系统概览",
                "type": "row",
                "collapsed": False,
                "panels": [
                    {
                        "title": "CPU使用率",
                        "type": "gauge",
                        "datasource": "Prometheus",
                        "targets": [{
                            "expr": "lianghua_cpu_usage_percent",
                            "legendFormat": "CPU %",
                        }],
                        "fieldConfig": {
                            "defaults": {
                                "unit": "percent",
                                "max": 100,
                                "min": 0,
                                "thresholds": {
                                    "mode": "absolute",
                                    "steps": [
                                        {"color": "green", "value": None},
                                        {"color": "yellow", "value": 70},
                                        {"color": "red", "value": 90},
                                    ]
                                }
                            }
                        },
                        "gridPos": {"x": 0, "y": 0, "w": 4, "h": 4},
                    },
                    {
                        "title": "内存使用",
                        "type": "gauge",
                        "datasource": "Prometheus",
                        "targets": [{
                            "expr": "lianghua_memory_usage_percent",
                            "legendFormat": "Memory %",
                        }],
                        "fieldConfig": {
                            "defaults": {
                                "unit": "percent",
                                "max": 100,
                                "min": 0,
                                "thresholds": {
                                    "mode": "absolute",
                                    "steps": [
                                        {"color": "green", "value": None},
                                        {"color": "yellow", "value": 70},
                                        {"color": "red", "value": 90},
                                    ]
                                }
                            }
                        },
                        "gridPos": {"x": 4, "y": 0, "w": 4, "h": 4},
                    },
                    {
                        "title": "活跃线程",
                        "type": "stat",
                        "datasource": "Prometheus",
                        "targets": [{
                            "expr": "lianghua_active_threads",
                        }],
                        "gridPos": {"x": 8, "y": 0, "w": 4, "h": 4},
                    },
                    {
                        "title": "WebSocket连接",
                        "type": "stat",
                        "datasource": "Prometheus",
                        "targets": [{
                            "expr": "lianghua_websocket_connections",
                        }],
                        "gridPos": {"x": 12, "y": 0, "w": 4, "h": 4},
                    },
                ],
            },
            # HTTP请求行
            {
                "title": "HTTP请求",
                "type": "row",
                "collapsed": False,
                "panels": [
                    {
                        "title": "请求速率",
                        "type": "timeseries",
                        "datasource": "Prometheus",
                        "targets": [{
                            "expr": "rate(lianghua_http_requests_total[1m])",
                            "legendFormat": "{{method}} {{endpoint}}",
                        }],
                        "gridPos": {"x": 0, "y": 4, "w": 12, "h": 6},
                    },
                    {
                        "title": "请求延迟P99",
                        "type": "timeseries",
                        "datasource": "Prometheus",
                        "targets": [{
                            "expr": "histogram_quantile(0.99, rate(lianghua_http_request_duration_seconds_bucket[5m]))",
                            "legendFormat": "P99",
                        }],
                        "gridPos": {"x": 12, "y": 4, "w": 12, "h": 6},
                    },
                ],
            },
            # 策略执行行
            {
                "title": "策略执行",
                "type": "row",
                "collapsed": False,
                "panels": [
                    {
                        "title": "策略执行次数",
                        "type": "timeseries",
                        "datasource": "Prometheus",
                        "targets": [{
                            "expr": "rate(lianghua_strategy_executions_total[5m])",
                            "legendFormat": "{{strategy}} - {{status}}",
                        }],
                        "gridPos": {"x": 0, "y": 10, "w": 8, "h": 6},
                    },
                    {
                        "title": "策略执行耗时",
                        "type": "heatmap",
                        "datasource": "Prometheus",
                        "targets": [{
                            "expr": "rate(lianghua_strategy_execution_duration_seconds_bucket[5m])",
                        }],
                        "gridPos": {"x": 8, "y": 10, "w": 8, "h": 6},
                    },
                    {
                        "title": "信号生成数",
                        "type": "stat",
                        "datasource": "Prometheus",
                        "targets": [{
                            "expr": "sum(increase(lianghua_strategy_signals_total[1h]))",
                        }],
                        "gridPos": {"x": 16, "y": 10, "w": 8, "h": 6},
                    },
                ],
            },
            # 交易行
            {
                "title": "交易监控",
                "type": "row",
                "collapsed": False,
                "panels": [
                    {
                        "title": "交易次数",
                        "type": "timeseries",
                        "datasource": "Prometheus",
                        "targets": [{
                            "expr": "rate(lianghua_trades_total[1h])",
                            "legendFormat": "{{action}} - {{status}}",
                        }],
                        "gridPos": {"x": 0, "y": 16, "w": 8, "h": 6},
                    },
                    {
                        "title": "交易金额",
                        "type": "timeseries",
                        "datasource": "Prometheus",
                        "targets": [{
                            "expr": "rate(lianghua_trade_amount_total[1h])",
                            "legendFormat": "{{action}}",
                        }],
                        "gridPos": {"x": 8, "y": 16, "w": 8, "h": 6},
                    },
                    {
                        "title": "账户价值",
                        "type": "stat",
                        "datasource": "Prometheus",
                        "targets": [{
                            "expr": "lianghua_account_value",
                        }],
                        "fieldConfig": {
                            "defaults": {
                                "unit": "currencyCNY",
                            }
                        },
                        "gridPos": {"x": 16, "y": 16, "w": 8, "h": 6},
                    },
                ],
            },
            # 数据源行
            {
                "title": "数据源状态",
                "type": "row",
                "collapsed": False,
                "panels": [
                    {
                        "title": "连接状态",
                        "type": "stat",
                        "datasource": "Prometheus",
                        "targets": [{
                            "expr": "lianghua_datasource_connected",
                            "legendFormat": "{{source}}",
                        }],
                        "gridPos": {"x": 0, "y": 22, "w": 6, "h": 4},
                    },
                    {
                        "title": "请求延迟",
                        "type": "timeseries",
                        "datasource": "Prometheus",
                        "targets": [{
                            "expr": "histogram_quantile(0.95, rate(lianghua_datasource_latency_seconds_bucket[5m]))",
                            "legendFormat": "{{source}}",
                        }],
                        "gridPos": {"x": 6, "y": 22, "w": 10, "h": 4},
                    },
                    {
                        "title": "请求成功率",
                        "type": "gauge",
                        "datasource": "Prometheus",
                        "targets": [{
                            "expr": "sum(rate(lianghua_datasource_requests_total{status=\"success\"}[5m])) / sum(rate(lianghua_datasource_requests_total[5m]))",
                        }],
                        "gridPos": {"x": 16, "y": 22, "w": 8, "h": 4},
                    },
                ],
            },
            # 缓存行
            {
                "title": "缓存性能",
                "type": "row",
                "collapsed": False,
                "panels": [
                    {
                        "title": "缓存命中率",
                        "type": "gauge",
                        "datasource": "Prometheus",
                        "targets": [{
                            "expr": "sum(rate(lianghua_cache_hits_total[5m])) / (sum(rate(lianghua_cache_hits_total[5m])) + sum(rate(lianghua_cache_misses_total[5m])))",
                        }],
                        "fieldConfig": {
                            "defaults": {
                                "unit": "percentunit",
                                "max": 1,
                                "min": 0,
                            }
                        },
                        "gridPos": {"x": 0, "y": 28, "w": 6, "h": 4},
                    },
                    {
                        "title": "缓存大小",
                        "type": "timeseries",
                        "datasource": "Prometheus",
                        "targets": [{
                            "expr": "lianghua_cache_size",
                            "legendFormat": "{{cache_name}}",
                        }],
                        "gridPos": {"x": 6, "y": 28, "w": 18, "h": 4},
                    },
                ],
            },
        ],
    },
    "overwrite": True,
}


# Prometheus配置
PROMETHEUS_CONFIG = """
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'lianghua'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'

alerting:
  alertmanagers:
    - static_configs:
        - targets: []

rule_files: []
"""


# Docker Compose配置
DOCKER_COMPOSE_MONITORING = """
version: '3.8'

services:
  prometheus:
    image: prom/prometheus:latest
    container_name: lianghua-prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus-data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.enable-lifecycle'

  grafana:
    image: grafana/grafana:latest
    container_name: lianghua-grafana
    ports:
      - "3000:3000"
    volumes:
      - grafana-data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=admin123
      - GF_USERS_ALLOW_SIGN_UP=false

volumes:
  prometheus-data:
  grafana-data:
"""


def export_dashboard(filename: str = 'grafana_dashboard.json') -> None:
    """导出仪表板配置"""
    import json
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(GRAFANA_DASHBOARD, f, indent=2, ensure_ascii=False)
    print(f"Dashboard exported to {filename}")


def export_prometheus_config(filename: str = 'prometheus.yml') -> None:
    """导出Prometheus配置"""
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(PROMETHEUS_CONFIG)
    print(f"Prometheus config exported to {filename}")


def export_docker_compose(filename: str = 'docker-compose.monitoring.yml') -> None:
    """导出Docker Compose配置"""
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(DOCKER_COMPOSE_MONITORING)
    print(f"Docker Compose config exported to {filename}")
