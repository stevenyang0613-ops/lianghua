"""
4框架定时任务 - 集成到 Celery

任务:
1. 每日收盘后自动批量扫描持仓 (15:30)
2. 每日新闻自动 Serenity Alpha 分析 (实时)
3. 每周一次深度估值扫描 (周五15:30)

集成到 celery_config.py:
    from app.framework.scheduled_tasks import register_4framework_tasks
    register_4framework_tasks(celery_app)
"""

import logging
from datetime import datetime, date
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


def daily_4framework_scan():
    """
    每日4框架扫描任务

    在Celery中注册:
        @celery_app.task
        def daily_4framework_scan_task():
            return daily_4framework_scan()
    """
    from app.framework.auto_trigger import get_trigger

    logger.info("🔔 启动每日4框架扫描")

    try:
        trigger = get_trigger()

        # 1. 获取当前持仓 (从数据库/缓存)
        holdings = _get_current_holdings()
        logger.info(f"   当前持仓: {len(holdings)} 只")

        # 2. 执行每日扫描
        summary = trigger.daily_scan(holdings)

        # 3. 保存扫描结果
        _save_daily_scan_result(summary)

        # 4. 推送异常告警
        if summary.get("risk_alerts"):
            _send_risk_alerts(summary["risk_alerts"])

        logger.info(f"✅ 每日扫描完成: 强买{len(summary.get('strong_buy', []))} "
                   f"买{len(summary.get('buy', []))} "
                   f"持有{len(summary.get('hold', []))} "
                   f"减仓{len(summary.get('trim', []))} "
                   f"卖{len(summary.get('sell', []))} "
                   f"预警{len(summary.get('risk_alerts', []))}条")

        return summary

    except Exception as e:
        logger.error(f"每日4框架扫描失败: {e}")
        return {}


def weekly_deep_valuation_scan():
    """每周一次深度估值扫描"""
    from app.framework.api import analyze_valuation, full_research

    logger.info("🔔 启动每周深度估值扫描")

    try:
        # 获取重点关注池
        watchlist = _get_watchlist_stocks()
        logger.info(f"   关注池: {len(watchlist)} 只")

        results = {}
        for stock in watchlist:
            try:
                v = analyze_valuation(stock)
                results[stock.get('code')] = {
                    'name': stock.get('name'),
                    'verdict': v.valuation_verdict,
                    'tam_adj_peg': v.tam_adj_peg,
                    'quality': v.growth_quality,
                    'recommendation': v.recommendation,
                }
            except Exception as e:
                logger.warning(f"  {stock.get('code')}估值失败: {e}")

        _save_weekly_scan_result(results)
        logger.info(f"✅ 每周扫描完成: {len(results)} 只")
        return results

    except Exception as e:
        logger.error(f"每周深度扫描失败: {e}")
        return {}


def on_news_event(news_text: str, candidates: Optional[List[Dict[str, Any]]] = None):
    """
    新闻事件触发任务

    在Celery中注册:
        @celery_app.task
        def news_event_task(news_text, candidates=None):
            return on_news_event(news_text, candidates)
    """
    from app.framework.auto_trigger import get_trigger

    trigger = get_trigger()
    hypotheses = trigger.on_news(news_text, candidates or [])

    if hypotheses:
        logger.info(f"📰 Serenity分析完成: 顶部假设{hypotheses[0].name}({hypotheses[0].hypothesis_strength})")

    return hypotheses


# ============================================================
# Celery 集成
# ============================================================

def register_4framework_tasks(celery_app):
    """
    注册4框架任务到 Celery

    用法:
        from app.tasks.celery_config import celery_app
        from app.framework.scheduled_tasks import register_4framework_tasks
        register_4framework_tasks(celery_app)
    """
    try:
        from celery.schedules import crontab

        # 注册任务函数
        @celery_app.task(name='app.framework.daily_4framework_scan')
        def daily_task():
            return daily_4framework_scan()

        @celery_app.task(name='app.framework.weekly_deep_valuation')
        def weekly_task():
            return weekly_deep_valuation_scan()

        @celery_app.task(name='app.framework.news_event')
        def news_task(news_text, candidates=None):
            return on_news_event(news_text, candidates)

        # 注册定时调度
        celery_app.conf.beat_schedule.update({
            '4framework-daily-scan': {
                'task': 'app.framework.daily_4framework_scan',
                'schedule': crontab(hour=15, minute=30, day_of_week='1-5'),  # 工作日15:30
            },
            '4framework-weekly-deep-scan': {
                'task': 'app.framework.weekly_deep_valuation',
                'schedule': crontab(hour=15, minute=30, day_of_week='5'),  # 周五15:30
            },
        })

        logger.info("✅ 4框架Celery任务已注册: daily_scan, weekly_scan, news_event")
        return True

    except ImportError:
        logger.warning("Celery未安装,跳过任务注册")
        return False
    except Exception as e:
        logger.error(f"注册Celery任务失败: {e}")
        return False


# ============================================================
# 数据获取辅助函数(实际使用时需替换为真实数据源)
# ============================================================

def _get_current_holdings() -> List[Dict[str, Any]]:
    """获取当前持仓 - 实际应从数据库获取"""
    # 占位实现 - 实际应从数据库/缓存获取真实持仓数据
    # 返回的每只股票需要包含:
    # code, name, prices (价格序列), ma_20/50/100/200,
    # current_price, eps_growth, revenue_growth, pe,
    # gross_margin, operating_margin, market_cap, industry,
    # eps_ttm, forward_eps, new_info, sentiment_score 等

    # 这里返回模拟数据,实际集成时需要替换
    import random
    random.seed(42)
    holdings = []
    for i in range(5):
        prices = [10.0 + j*0.05 + random.uniform(-0.5, 0.5) for j in range(250)]
        holdings.append({
            "code": f"{600000 + i:06d}",
            "name": f"持仓{i+1}",
            "industry": "其他",
            "market_cap": 200,
            "prices": prices,
            "current_price": prices[-1],
            "ma_20": sum(prices[-20:]) / 20,
            "ma_50": sum(prices[-50:]) / 50,
            "ma_100": sum(prices[-100:]) / 100,
            "ma_200": sum(prices[-200:]) / 200,
            "eps_growth": 15,
            "revenue_growth": 12,
            "pe": 25,
            "eps_ttm": 1.0,
            "forward_eps": 1.15,
            "gross_margin": 30,
            "operating_margin": 15,
            "market_share": 0.05,
            "moat_indicators": {"brand": 5, "tech": 5, "scale": 5, "network": 5},
            "growth_rate": 15,
            "analyst_rating_change": "stable",
            "new_info": {},
            "sentiment_score": 0.0,
        })
    return holdings


def _get_watchlist_stocks() -> List[Dict[str, Any]]:
    """获取关注池"""
    return _get_current_holdings()  # 占位实现


def _save_daily_scan_result(summary: Dict[str, Any]):
    """保存每日扫描结果 - 实际应写入数据库"""
    logger.info(f"保存每日扫描结果: {summary.get('total', 0)} 只标的")

    # 占位实现 - 实际应保存到数据库
    # from app.storage.database import save_daily_scan
    # save_daily_scan(date.today(), summary)


def _save_weekly_scan_result(results: Dict[str, Any]):
    """保存每周扫描结果"""
    logger.info(f"保存每周扫描结果: {len(results)} 只")


def _send_risk_alerts(alerts: List[Dict[str, Any]]):
    """发送风险预警"""
    for alert in alerts:
        logger.warning(f"⚠️ 风险预警: {alert}")


# ============================================================
# 测试入口
# ============================================================

if __name__ == "__main__":
    print("🚀 4框架定时任务测试\n")
    print("=" * 60)
    print("1️⃣ 每日扫描任务")
    print("=" * 60)
    summary = daily_4framework_scan()
    print(f"\n扫描结果摘要: {summary}")

    print("\n" + "=" * 60)
    print("2️⃣ 每周深度估值任务")
    print("=" * 60)
    weekly_results = weekly_deep_valuation_scan()
    print(f"\n估值结果数: {len(weekly_results)}")

    print("\n" + "=" * 60)
    print("3️⃣ 新闻事件任务")
    print("=" * 60)
    candidates = [
        {"code": "002335", "name": "英维克", "industry": "AI数据中心液冷",
         "market_cap": 180, "keywords": ["液冷"]},
    ]
    hypotheses = on_news_event("AI液冷需求加速", candidates)
    if hypotheses:
        print(f"\n假设结果: {hypotheses[0].name} (强度{hypotheses[0].hypothesis_strength})")

    print("\n✅ 定时任务测试完成!")
