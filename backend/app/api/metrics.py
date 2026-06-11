"""
监控指标API端点
"""

from fastapi import APIRouter, Response
from typing import Dict, Any

router = APIRouter(tags=['monitoring'])


@router.get('/metrics')
async def prometheus_metrics() -> Response:
    """Prometheus指标端点"""
    from app.core.prometheus_config import metrics_endpoint
    return metrics_endpoint()


@router.get('/health/detailed')
async def detailed_health_check() -> Dict[str, Any]:
    """详细健康检查"""
    import psutil
    from datetime import datetime

    process = psutil.Process()

    return {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'system': {
            'cpu_percent': process.cpu_percent(),
            'memory_mb': process.memory_info().rss / 1024 / 1024,
            'memory_percent': process.memory_percent(),
            'threads': process.num_threads(),
        },
        'uptime_seconds': (datetime.now() - datetime.fromtimestamp(process.create_time())).total_seconds(),
    }


@router.get('/performance')
async def get_performance_metrics() -> Dict[str, Any]:
    """获取性能指标"""
    from app.core.metrics import get_metrics_collector

    collector = get_metrics_collector()

    return {
        'counters': {
            k: v for k, v in collector._counters.items()
        },
        'gauges': {
            k: v for k, v in collector._gauges.items()
        },
        'histograms': {
            k: collector.get_histogram_stats(k.split('{')[0])
            for k in collector._histograms.keys()
        },
    }


@router.get('/metrics/export')
async def export_metrics_json() -> Dict[str, Any]:
    """导出指标为JSON格式"""
    from app.core.metrics import get_metrics_collector

    collector = get_metrics_collector()

    result = {}

    # 计数器
    for key, value in collector._counters.items():
        name = key.split('{')[0]
        if name not in result:
            result[name] = {'type': 'counter', 'values': {}}
        result[name]['values'][key] = value

    # 仪表盘
    for key, value in collector._gauges.items():
        name = key.split('{')[0]
        if name not in result:
            result[name] = {'type': 'gauge', 'values': {}}
        result[name]['values'][key] = value

    # 直方图
    for key in collector._histograms.keys():
        name = key.split('{')[0]
        if name not in result:
            result[name] = {'type': 'histogram', 'stats': {}}
        result[name]['stats'] = collector.get_histogram_stats(name)

    return result
