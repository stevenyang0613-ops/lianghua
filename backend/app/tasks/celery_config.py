"""
Celery分布式任务配置

任务类型：
- 回测任务异步执行
- 数据更新定时任务
- 邮件/通知发送
- 参数优化并行执行
"""

from celery import Celery
from celery.schedules import crontab
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

# Celery应用配置
celery_app = Celery(
    'lianghua',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/1',
    include=[
        'app.tasks.backtest_tasks',
        'app.tasks.data_tasks',
        'app.tasks.notification_tasks',
        'app.tasks.optimization_tasks',
    ]
)

# Celery配置
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Shanghai',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30分钟超时
    task_soft_time_limit=25 * 60,  # 25分钟软超时
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=100,
    result_expires=3600,  # 结果保留1小时
    # 定时任务
    beat_schedule={
        'update-quotes-every-minute': {
            'task': 'app.tasks.data_tasks.update_quotes',
            'schedule': 60.0,  # 每分钟
        },
        'update-score-ranking': {
            'task': 'app.tasks.data_tasks.update_score_ranking',
            'schedule': 300.0,  # 每5分钟
        },
        'cleanup-old-data': {
            'task': 'app.tasks.data_tasks.cleanup_old_data',
            'schedule': crontab(hour=2, minute=0),  # 每天凌晨2点
        },
        'generate-daily-report': {
            'task': 'app.tasks.notification_tasks.generate_daily_report',
            'schedule': crontab(hour=18, minute=0),  # 每天18点
        },
        'check-events': {
            'task': 'app.tasks.data_tasks.check_new_events',
            'schedule': 300.0,  # 每5分钟检查事件
        },
    },
)


# ==================== 回测任务 ====================

@celery_app.task(bind=True, name='app.tasks.backtest_tasks.run_backtest')
def run_backtest(
    self,
    strategy_id: str,
    params: Dict[str, Any],
    start_date: str,
    end_date: str,
    config: Optional[Dict] = None,
) -> Dict:
    """
    异步执行回测任务
    """
    from app.engine.backtest import BacktestEngine
    from app.strategies import get_strategy

    logger.info(f"[Backtest] Starting backtest for {strategy_id}")

    # 更新任务状态
    self.update_state(
        state='PROGRESS',
        meta={'status': 'initializing', 'progress': 0}
    )

    try:
        # 获取策略
        strategy_cls = get_strategy(strategy_id)
        strategy = strategy_cls(**params)

        # 创建回测引擎
        engine = BacktestEngine(config or {})

        # 执行回测
        self.update_state(
            state='PROGRESS',
            meta={'status': 'running', 'progress': 30}
        )

        result = engine.run(
            strategy=strategy,
            start_date=start_date,
            end_date=end_date,
        )

        self.update_state(
            state='PROGRESS',
            meta={'status': 'finalizing', 'progress': 90}
        )

        logger.info(f"[Backtest] Completed for {strategy_id}")

        return {
            'status': 'completed',
            'result': result.to_dict() if hasattr(result, 'to_dict') else result,
            'execution_time': result.execution_time if hasattr(result, 'execution_time') else 0,
        }

    except Exception as e:
        logger.error(f"[Backtest] Error: {e}")
        return {
            'status': 'failed',
            'error': str(e),
        }


@celery_app.task(bind=True, name='app.tasks.backtest_tasks.run_batch_backtest')
def run_batch_backtest(
    self,
    strategy_configs: list[Dict],
) -> Dict:
    """
    批量执行回测任务
    """
    results = []
    total = len(strategy_configs)

    for i, config in enumerate(strategy_configs):
        self.update_state(
            state='PROGRESS',
            meta={'status': f'running {i+1}/{total}', 'progress': int((i+1)/total*100)}
        )

        result = run_backtest.delay(
            strategy_id=config['strategy_id'],
            params=config.get('params', {}),
            start_date=config['start_date'],
            end_date=config['end_date'],
            config=config.get('config'),
        )
        results.append(result.id)

    return {
        'status': 'completed',
        'task_ids': results,
        'total': total,
    }


# ==================== 数据更新任务 ====================

@celery_app.task(name='app.tasks.data_tasks.update_quotes')
def update_quotes() -> Dict:
    """
    更新实时行情数据
    """
    from app.engine.market import MarketEngine
    import asyncio

    logger.info("[Data] Updating quotes...")

    try:
        engine = MarketEngine()
        # 异步调用
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        updated = loop.run_until_complete(engine.update_quotes())
        loop.close()

        return {
            'status': 'completed',
            'updated_count': updated,
            'timestamp': datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"[Data] Update quotes error: {e}")
        return {'status': 'failed', 'error': str(e)}


@celery_app.task(name='app.tasks.data_tasks.update_score_ranking')
def update_score_ranking() -> Dict:
    """
    更新评分排名
    """
    logger.info("[Data] Updating score ranking...")

    try:
        # 调用西部七维打分
        from app.strategies.xibu_seven_dimension import XibuSevenDimensionStrategy

        # 这里需要实际数据
        # result = strategy.calculate(...)

        return {
            'status': 'completed',
            'timestamp': datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"[Data] Update score ranking error: {e}")
        return {'status': 'failed', 'error': str(e)}


@celery_app.task(name='app.tasks.data_tasks.cleanup_old_data')
def cleanup_old_data(days: int = 30) -> Dict:
    """
    清理旧数据
    """
    from app.engine.storage import DataStorage

    logger.info(f"[Data] Cleaning up data older than {days} days...")

    try:
        storage = DataStorage()
        deleted_signals = storage.cleanup_signal_history(days)
        deleted_positions = storage.cleanup_executed_positions(days)

        return {
            'status': 'completed',
            'deleted_signals': deleted_signals,
            'deleted_positions': deleted_positions,
        }
    except Exception as e:
        logger.error(f"[Data] Cleanup error: {e}")
        return {'status': 'failed', 'error': str(e)}


@celery_app.task(name='app.tasks.data_tasks.check_new_events')
def check_new_events() -> Dict:
    """
    检查新事件（下修、强赎等公告）
    """
    from app.strategies.event_data_source import get_event_source
    import asyncio

    logger.info("[Data] Checking new events...")

    try:
        source = get_event_source()
        events = source.get_recent_events(hours=1)

        return {
            'status': 'completed',
            'events_count': len(events),
            'timestamp': datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"[Data] Check events error: {e}")
        return {'status': 'failed', 'error': str(e)}


# ==================== 通知任务 ====================

@celery_app.task(name='app.tasks.notification_tasks.send_email')
def send_email(
    to: str,
    subject: str,
    body: str,
    html: Optional[str] = None,
) -> Dict:
    """
    发送邮件
    """
    logger.info(f"[Notification] Sending email to {to}")

    try:
        # 实际实现需要配置SMTP
        # import smtplib
        # ...

        return {
            'status': 'completed',
            'to': to,
            'subject': subject,
        }
    except Exception as e:
        logger.error(f"[Notification] Send email error: {e}")
        return {'status': 'failed', 'error': str(e)}


@celery_app.task(name='app.tasks.notification_tasks.send_webhook')
def send_webhook(
    url: str,
    payload: Dict,
) -> Dict:
    """
    发送Webhook通知
    """
    import requests

    logger.info(f"[Notification] Sending webhook to {url}")

    try:
        response = requests.post(url, json=payload, timeout=10)

        return {
            'status': 'completed',
            'status_code': response.status_code,
        }
    except Exception as e:
        logger.error(f"[Notification] Send webhook error: {e}")
        return {'status': 'failed', 'error': str(e)}


@celery_app.task(name='app.tasks.notification_tasks.generate_daily_report')
def generate_daily_report() -> Dict:
    """
    生成每日报告
    """
    from app.strategies.attribution import BrisonAttribution
    from app.strategies.cost_tracking import CostTracker

    logger.info("[Notification] Generating daily report...")

    try:
        # 收集数据
        today = datetime.now().strftime('%Y-%m-%d')

        # 获取成本报告
        tracker = CostTracker()
        cost_report = tracker.get_daily_report(today)

        # 生成报告内容
        report_lines = [
            f"# 每日报告 - {today}",
            "",
            "## 交易成本",
            f"- 交易次数: {cost_report.get('total_trades', 0)}",
            f"- 总成本: {cost_report.get('total_cost', 0):.2f}元",
            f"- 成本占比: {cost_report.get('cost_ratio', 0)*100:.4f}%",
            "",
        ]

        report = "\n".join(report_lines)

        return {
            'status': 'completed',
            'report': report,
            'date': today,
        }
    except Exception as e:
        logger.error(f"[Notification] Generate report error: {e}")
        return {'status': 'failed', 'error': str(e)}


# ==================== 参数优化任务 ====================

@celery_app.task(bind=True, name='app.tasks.optimization_tasks.run_optimization')
def run_optimization(
    self,
    strategy_id: str,
    param_ranges: list[Dict],
    train_start: str,
    train_end: str,
    test_start: str,
    test_end: str,
) -> Dict:
    """
    执行参数优化
    """
    from app.strategies.parameter_optimization import ParameterGridOptimizer, ParameterRange

    logger.info(f"[Optimization] Starting optimization for {strategy_id}")

    try:
        # 构建参数范围
        ranges = [
            ParameterRange(
                name=r['name'],
                min_val=r['min_val'],
                max_val=r['max_val'],
                step=r['step'],
            )
            for r in param_ranges
        ]

        # 定义目标函数
        def objective(params):
            # 简化实现，实际需要运行回测
            return sum(params.values()) / len(params)

        # 创建优化器
        optimizer = ParameterGridOptimizer(
            param_ranges=ranges,
            objective_func=objective,
        )

        # 执行优化
        self.update_state(
            state='PROGRESS',
            meta={'status': 'optimizing', 'progress': 50}
        )

        result = optimizer.optimize(max_workers=4)

        return {
            'status': 'completed',
            'best_params': result.best_params,
            'best_score': result.best_score,
            'stability_report': result.stability_report,
            'overfit_report': result.overfit_report,
            'execution_time': result.execution_time,
        }

    except Exception as e:
        logger.error(f"[Optimization] Error: {e}")
        return {'status': 'failed', 'error': str(e)}


# ==================== 任务状态查询 ====================

def get_task_status(task_id: str) -> Dict:
    """获取任务状态"""
    task = celery_app.AsyncResult(task_id)

    if task.state == 'PENDING':
        return {
            'state': task.state,
            'status': 'Pending...',
        }
    elif task.state == 'PROGRESS':
        return {
            'state': task.state,
            'status': task.info.get('status', ''),
            'progress': task.info.get('progress', 0),
        }
    elif task.state == 'SUCCESS':
        return {
            'state': task.state,
            'result': task.result,
        }
    else:  # FAILURE
        return {
            'state': task.state,
            'error': str(task.info),
        }


def cancel_task(task_id: str) -> bool:
    """取消任务"""
    task = celery_app.AsyncResult(task_id)
    task.revoke(terminate=True)
    return True


# ==================== Flower监控扩展 ====================

# 任务指标收集
_task_metrics: Dict[str, Dict] = {}


@celery_app.signals.task_prerun.connect
def task_prerun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, **extra):
    """任务开始前钩子 - 记录指标"""
    import time as time_module
    _task_metrics[task_id] = {
        'start_time': time_module.time(),
        'task_name': task.name if task else 'unknown',
        'args': str(args)[:500] if args else None,
        'kwargs': str(kwargs)[:500] if kwargs else None,
    }
    logger.debug(f"[Celery] Task started: {task_id} - {task.name if task else 'unknown'}")


@celery_app.signals.task_postrun.connect
def task_postrun_handler(sender=None, task_id=None, task=None, retval=None, state=None, **extra):
    """任务完成后钩子 - 记录指标"""
    import time as time_module

    if task_id in _task_metrics:
        metrics = _task_metrics[task_id]
        duration = time_module.time() - metrics['start_time']

        # 记录到Prometheus
        try:
            from app.core.prometheus_config import CELERY_TASK_DURATION
            if CELERY_TASK_DURATION:
                CELERY_TASK_DURATION.labels(
                    task_name=metrics['task_name'],
                    status=state or 'SUCCESS',
                ).observe(duration)
        except ImportError:
            pass

        logger.info(
            f"[Celery] Task completed: {task_id} - {metrics['task_name']} "
            f"duration={duration:.2f}s state={state}"
        )

        del _task_metrics[task_id]


@celery_app.signals.task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, **extra):
    """任务失败钩子 - 记录失败指标"""
    import time as time_module

    if task_id in _task_metrics:
        metrics = _task_metrics[task_id]
        duration = time_module.time() - metrics['start_time']

        logger.error(
            f"[Celery] Task failed: {task_id} - {metrics['task_name']} "
            f"duration={duration:.2f}s error={exception}"
        )

        # 记录失败指标
        try:
            from app.core.prometheus_config import CELERY_TASK_FAILURES
            if CELERY_TASK_FAILURES:
                CELERY_TASK_FAILURES.labels(
                    task_name=metrics['task_name'],
                    error_type=type(exception).__name__,
                ).inc()
        except ImportError:
            pass

        del _task_metrics[task_id]


def get_task_statistics() -> Dict[str, Any]:
    """获取任务统计信息 - 供Flower API使用"""
    inspect = celery_app.control.inspect()

    stats = {
        'active': inspect.active() or {},
        'reserved': inspect.reserved() or {},
        'scheduled': inspect.scheduled() or {},
        'stats': inspect.stats() or {},
        'registered': inspect.registered() or {},
        'workers': len(inspect.stats() or {}),
    }

    # 统计活跃任务数
    active_count = sum(len(tasks) for tasks in stats['active'].values())
    stats['active_count'] = active_count

    # 队列长度
    stats['queue_lengths'] = get_queue_lengths()

    return stats


def get_queue_lengths() -> Dict[str, int]:
    """获取各队列长度"""
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, db=0)

        queues = {}
        for queue in ['celery', 'strategy', 'data', 'alert']:
            length = r.llen(queue)
            queues[queue] = length

        return queues
    except Exception as e:
        logger.warning(f"Failed to get queue lengths: {e}")
        return {}


def health_check() -> Dict[str, Any]:
    """Celery健康检查 - 供监控使用"""
    try:
        stats = get_task_statistics()
        queues = stats['queue_lengths']

        workers_online = stats['workers'] > 0
        total_pending = sum(queues.values())

        # 判断健康状态
        if not workers_online:
            status = 'critical'
        elif total_pending > 100:
            status = 'warning'
        else:
            status = 'healthy'

        return {
            'status': status,
            'workers_online': workers_online,
            'worker_count': stats['workers'],
            'active_tasks': stats['active_count'],
            'queue_lengths': queues,
            'total_pending': total_pending,
            'timestamp': datetime.now().isoformat(),
        }
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat(),
        }


# Flower配置选项
FLOWER_CONFIG = {
    # 端口
    'port': 5555,
    # 认证（可选）
    # 'basic_auth': ['admin:password'],
    # URL前缀
    'url_prefix': '',
    # 刷新间隔（毫秒）
    'inspect_timeout': 1000,
    # 最大任务显示数
    'max_tasks': 10000,
    # 持久化数据库
    # 'db': 'flower.db',
    # 持久化间隔（秒）
    'persistent': True,
    'state_save_interval': 5000,
}
